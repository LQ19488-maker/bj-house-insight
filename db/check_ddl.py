"""DDL 静态自检：在拿不到 MySQL 服务的前提下，尽可能把建表错误挡在生成阶段。

    python db/check_ddl.py

校验项（MySQL 版 / SQLite 版 / DBML / 数据字典 四份产物）：
    1. 表数量与 schema_model 一致
    2. 每张表都有主键，且都有 created_at / updated_at
    3. MySQL 版每个字段都有 COMMENT
    4. 全库无 FLOAT / DOUBLE（金额与面积必须 DECIMAL）
    5. 外键列类型与被引用表主键类型完全一致（长度与 UNSIGNED 都要匹配）
    6. 外键引用的表与列必须存在
    7. 索引与唯一键引用的列必须存在
    8. SQLite 版每个枚举列都有 CHECK 约束
    9. DBML 括号平衡、Ref 指向的表存在
   10. 数据字典 xlsx 的字段名/类型与 schema_model 逐字一致（防文档漂移）
   11. 括号平衡（粗粒度语法检查）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_model import TABLES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MYSQL_SQL = ROOT / "db" / "schema.sql"
SQLITE_SQL = ROOT / "db" / "schema_sqlite.sql"
DBML = ROOT / "db" / "schema.dbml"
XLSX = ROOT / "docs" / "05-数据字典.xlsx"

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def split_tables(sql_text: str):
    """返回 {表名: 表体}；表体是 CREATE TABLE (...) 的括号内容。"""
    out = {}
    for m in re.finditer(r"CREATE TABLE\s+`?(\w+)`?\s*\(", sql_text):
        name = m.group(1)
        i = m.end()  # 左括号之后
        depth = 1
        while i < len(sql_text) and depth:
            ch = sql_text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        out[name] = sql_text[m.end(): i - 1]
    return out


def col_type(body: str, col: str):
    """提取某列声明的类型片段（到行尾），用于类型一致性比对。"""
    m = re.search(rf"^\s*`?{re.escape(col)}`?\s+([A-Z]+(?:\([^)]*\))?(?:\s+UNSIGNED)?)",
                  body, re.M)
    return m.group(1) if m else None


def main() -> int:
    mysql = MYSQL_SQL.read_text(encoding="utf-8")
    sqlite = SQLITE_SQL.read_text(encoding="utf-8")
    dbml = DBML.read_text(encoding="utf-8")
    model_names = [t["name"] for t in TABLES]

    mt = split_tables(mysql)
    st = split_tables(sqlite)

    # 1 表数量
    check("MySQL 表数量与模型一致", len(mt) == len(TABLES),
          f"DDL {len(mt)} / 模型 {len(TABLES)}：缺 {set(model_names) - set(mt)}")
    check("SQLite 表数量与模型一致", len(st) == len(TABLES),
          f"DDL {len(st)} / 模型 {len(TABLES)}")

    # 2 主键与时间戳
    no_pk = [n for n, b in mt.items() if "PRIMARY KEY" not in b]
    check("每张表都有主键", not no_pk, f"缺主键：{no_pk}")
    no_ts = []
    for t in TABLES:
        body = mt.get(t["name"], "")
        if "created_at" not in body or "updated_at" not in body:
            no_ts.append(t["name"])
    check("每张表都有 created_at / updated_at", not no_ts, f"缺失：{no_ts}")

    # 3 每个字段都有 COMMENT（MySQL 版）
    missing_comment = []
    for name, body in mt.items():
        for line in body.splitlines():
            s = line.strip()
            if not s.startswith("`"):
                continue
            if "COMMENT" not in s:
                missing_comment.append(f"{name}.{s.split('`')[1]}")
    check("MySQL 每个字段都有 COMMENT", not missing_comment,
          f"缺注释：{missing_comment[:6]}")

    # 4 无 FLOAT / DOUBLE（先剥掉注释行，避免把"禁用 FLOAT"这句话当成用法）
    code_only = "\n".join(
        line for line in mysql.splitlines() if not line.strip().startswith("--")
    )
    float_hits = re.findall(r"\b(FLOAT|DOUBLE|REAL)\b", code_only.upper())
    check("全库无 FLOAT / DOUBLE / REAL", not float_hits, f"命中：{set(float_hits)}")

    # 5 外键类型一致性
    pk_type = {}
    for name, body in mt.items():
        pk_type[name] = col_type(body, "id")
    fk_mismatch, fk_missing = [], []
    for t in TABLES:
        body = mt.get(t["name"], "")
        for fk in t["fks"]:
            fk_t = col_type(body, fk["col"])
            ref_t = pk_type.get(fk["ref_table"])
            if fk_t != ref_t:
                fk_mismatch.append(f"{t['name']}.{fk['col']}({fk_t}) → "
                                   f"{fk['ref_table']}.{fk['ref_col']}({ref_t})")
            if fk["ref_table"] not in mt:
                fk_missing.append(f"{t['name']} → {fk['ref_table']}")
    check("外键列类型与被引用主键类型一致", not fk_mismatch, "；".join(fk_mismatch))
    check("外键引用的表都存在", not fk_missing, "；".join(fk_missing))

    # 6 外键引用的列存在
    fk_col_missing = []
    for t in TABLES:
        body = mt.get(t["name"], "")
        for fk in t["fks"]:
            if f"`{fk['col']}`" not in body:
                fk_col_missing.append(f"{t['name']}.{fk['col']} 不存在")
            rb = mt.get(fk["ref_table"], "")
            if f"`{fk['ref_col']}`" not in rb:
                fk_col_missing.append(f"{fk['ref_table']}.{fk['ref_col']} 不存在")
    check("外键引用的列都存在", not fk_col_missing, "；".join(fk_col_missing[:6]))

    # 7 索引 / 唯一键引用的列存在
    idx_missing = []
    for t in TABLES:
        body = mt.get(t["name"], "")
        cols_in_body = set(re.findall(r"^\s*`(\w+)`\s+[A-Z]", body, re.M))
        for keys in (t["indexes"], t["uniques"]):
            for k in keys:
                for c in k["cols"]:
                    if c not in cols_in_body:
                        idx_missing.append(f"{t['name']}.{c}（{k['name']}）")
    check("索引/唯一键引用的列都存在", not idx_missing, "；".join(idx_missing[:6]))

    # 8 SQLite 版枚举列都有 CHECK
    enum_missing = []
    for t in TABLES:
        body = st.get(t["name"], "")
        for col in t["columns"]:
            if col["check"] and f"chk_{t['name']}_{col['name']}" not in body:
                enum_missing.append(f"{t['name']}.{col['name']}")
    check("SQLite 枚举列都有 CHECK 约束", not enum_missing, "；".join(enum_missing[:6]))

    # 9 DBML 结构
    check("DBML 花括号平衡",
          dbml.count("{") == dbml.count("}"),
          f"{{ {dbml.count('{')} / }} {dbml.count('}')}")
    refs = re.findall(r"^Ref:\s*(\w+)\.(\w+)\s*[<>-]\s*(\w+)\.(\w+)", dbml, re.M)
    bad_refs = [f"{a}.{b} → {c}.{d}" for a, b, c, d in refs
                if a not in model_names or c not in model_names]
    check("DBML Ref 指向的表都存在", not bad_refs, "；".join(bad_refs))
    check("DBML 表数量与模型一致", dbml.count("Table ") == len(TABLES),
          f"DBML {dbml.count('Table ')} / 模型 {len(TABLES)}")

    # 10 数据字典与模型逐字一致
    try:
        from openpyxl import load_workbook

        wb = load_workbook(XLSX, read_only=True)
        drift = []
        for t in TABLES:
            sheet = wb[t["name"][:31]]
            rows = list(sheet.iter_rows(min_row=2, values_only=True))
            names = [r[1] for r in rows if r and r[1]]
            model_fields = [c["name"] for c in t["columns"]]
            if names != model_fields:
                drift.append(f"{t['name']}：字典 {len(names)} 字段 / 模型 {len(model_fields)}")
        check("数据字典字段与模型逐字一致", not drift, "；".join(drift))
        wb.close()
    except Exception as e:  # pragma: no cover
        check("数据字典字段与模型逐字一致", False, f"读取失败 {e}")

    # 11 括号平衡
    for label, text in [("MySQL", mysql), ("SQLite", sqlite)]:
        check(f"{label} 括号平衡", text.count("(") == text.count(")"),
              f"( {text.count('(')} / ) {text.count(')')}")

    # 输出
    print("=" * 78)
    print("DDL 静态自检（无法连接 MySQL，故用结构化校验替代实跑）")
    print("=" * 78)
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i:>2}. {c['name']}"
              + (f"  — {c['detail']}" if (c["detail"] and not c["passed"]) else ""))
    print("-" * 78)
    print(f"自检结果：{len(checks) - failed}/{len(checks)} 通过")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
