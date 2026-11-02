"""建 SQLite 库 + 导入 ETL 产物 + SQL 层独立校验。

    python db/load_sqlite.py          建库、导入、校验
    python db/load_sqlite.py --keep   复用已有 app.db（只校验）

为什么既要 MySQL DDL 又要 SQLite 实跑：
    本机没有 MySQL 服务，但"表结构能不能真的建起来、外键和索引是否成立"
    不能只靠肉眼审 SQL。SQLite 版由同一份 schema_model.py 生成，
    字段名/外键/索引完全一致，用它把结构跑通、再用 SQL 复算指标，
    等于给 DDL 做了一次真实编译 + 一次数据回归。
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
DATA = ROOT / "data"
SCHEMA = DB_DIR / "schema_sqlite.sql"
DB_FILE = DATA / "app.db"

BATCH_ID = 1


def read_csv(name: str) -> list[dict]:
    with open(DATA / name, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def none_if_empty(v):
    return None if v == "" else v


def expected_issues() -> int:
    """期望的问题条数直接取自 ETL 产出的质量报告，避免两处硬编码漂移。"""
    import json

    rep = json.loads((DATA / "quality_report.json").read_text(encoding="utf-8"))
    return int(rep["issues_total"])


def insert_rows(cur, table: str, rows: list[dict], columns: list[str] | None = None,
                rename: dict | None = None, transform=None):
    """columns 是 CSV 列名；rename 把 CSV 列名映射为库里真实字段名。"""
    if not rows:
        return 0
    cols = columns or list(rows[0].keys())
    rename = rename or {}
    db_cols = [rename.get(c, c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO {table} ({', '.join(db_cols)}) VALUES ({placeholders})"
    payload = []
    for r in rows:
        vals = [none_if_empty(r.get(c, "")) for c in cols]
        if transform:
            vals = transform(vals, r)
        payload.append(vals)
    cur.executemany(sql, payload)
    return len(payload)


def build() -> None:
    if DB_FILE.exists():
        DB_FILE.unlink()
    schema_sql = SCHEMA.read_text(encoding="utf-8")

    con = sqlite3.connect(DB_FILE)
    con.executescript(schema_sql)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    # 1) 维度：区 / 街道 / 小区（聚合快照随维度一起入库）
    n_district = insert_rows(cur, "district", read_csv("dim_district.csv"), columns=[
        "district_id", "district_name", "house_count", "avg_unit_price",
        "median_unit_price", "median_total_price", "avg_area", "avg_age",
    ], rename={"district_id": "id", "district_name": "name"})

    n_street = insert_rows(cur, "street", read_csv("dim_street.csv"), columns=[
        "street_id", "district_id", "street_name", "is_pseudo", "house_count",
        "avg_unit_price", "median_total_price",
    ], rename={"street_id": "id", "street_name": "name"})

    n_community = insert_rows(cur, "community", read_csv("dim_community.csv"), columns=[
        "community_id", "district_id", "street_id", "community_name", "house_count",
        "avg_unit_price", "median_total_price", "avg_area", "avg_age",
    ], rename={"community_id": "id", "community_name": "name"})

    # 2) 导入批次（seed 批次）
    cur.execute(
        "INSERT INTO import_batch (id, file_name, file_md5, total_rows, loaded_rows, "
        "rejected_rows, status, duration_ms, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (BATCH_ID, "最新发布的北京二手房数据_预处理.xlsx",
         "b01349e3d95dc6447b65236cf3ee73b1", 2890, 2890, 0, "success", None,
         "seed：由 etl/run.py 产出 CSV 后导入"),
    )

    # 3) 房源主表
    house_rows = read_csv("cleaned_house.csv")
    n_house = insert_rows(
        cur, "house", house_rows,
        columns=["source_row_no", "district_id", "street_id", "community_id", "room",
                 "hall", "area", "total_price", "unit_price", "floor_level",
                 "floor_total", "floor_raw", "orientation_text", "decoration",
                 "structure", "house_age", "near_subway", "is_outlier",
                 "abnormal_layout"],
    )
    cur.execute("UPDATE house SET batch_id = ? WHERE batch_id IS NULL", (BATCH_ID,))

    # 4) 朝向关联表：source_row_no → house.id
    row_to_id = {r: i for r, i in cur.execute("SELECT source_row_no, id FROM house")}
    n_orient = insert_rows(
        cur, "house_orientation", read_csv("cleaned_orientation.csv"),
        columns=["source_row_no", "direction"],
        rename={"source_row_no": "house_id"},
        transform=lambda vals, raw: [row_to_id[int(vals[0])], vals[1]],
    )

    # 5) 数据质量问题留痕（CSV 列 rule → 库字段 rule_code）
    issue_rows = read_csv("data_quality_issue.csv")
    cur.executemany(
        "INSERT INTO data_quality_issue "
        "(batch_id, rule_code, row_no, field_name, issue_type, raw_value, fixed_value) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (BATCH_ID, r["rule"], none_if_empty(r["row_no"]), none_if_empty(r["field"]),
             r["issue_type"], none_if_empty(r["raw_value"]),
             none_if_empty(r["fixed_value"]))
            for r in issue_rows
        ],
    )
    n_issue = len(issue_rows)
    con.commit()

    print("=== 导入结果 ===")
    for label, n in [("district", n_district), ("street", n_street),
                     ("community", n_community), ("house", n_house),
                     ("house_orientation", n_orient), ("data_quality_issue", n_issue),
                     ("import_batch", 1)]:
        print(f"  {label:<22} {n:>5} 行")
    con.close()


# ---------------------------------------------------------------------------
# SQL 层独立校验
# ---------------------------------------------------------------------------
def verify() -> int:
    con = sqlite3.connect(DB_FILE)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()
    checks = []

    def one(sql, params=()):
        return cur.execute(sql, params).fetchone()[0]

    def check(name, actual, expected, note=""):
        ok = actual == expected
        checks.append({"name": name, "actual": actual, "expected": expected,
                       "passed": ok, "note": note})

    # 1–7 行数
    for table, expected in [("district", 17), ("street", 264), ("community", 1865),
                            ("house", 2890), ("house_orientation", 4806),
                            ("import_batch", 1)]:
        check(f"表 {table} 行数", one(f"SELECT COUNT(*) FROM {table}"), expected)

    check("data_quality_issue 行数", one("SELECT COUNT(*) FROM data_quality_issue"),
          expected_issues(), "ETL 问题台账全量落库（期望值取自 quality_report.json）")

    # 8 外键完整性
    fk_violations = cur.execute("PRAGMA foreign_key_check").fetchall()
    check("外键违规数", len(fk_violations), 0, "PRAGMA foreign_key_check")

    # 9 行数漏斗（从库里反推）
    check("库内行数漏斗",
          (one("SELECT total_rows FROM import_batch WHERE id=?", (BATCH_ID,))
           == one("SELECT COUNT(*) FROM house")
           + one("SELECT rejected_rows FROM import_batch WHERE id=?", (BATCH_ID,))),
          True, "total = house 行数 + rejected")

    # 10 单价公式（纯 SQL 复算）
    max_dev = one("SELECT MAX(ABS(ROUND(total_price*10000.0/area, 2) - unit_price)) "
                  "FROM house")
    check("单价公式最大偏差 ≤ 1.00", round(max_dev, 2) <= 1.0, True,
          f"实测最大偏差 {max_dev:.2f} 元/㎡")

    # 11 中位数（SQL 侧取中间两个值）
    mid = cur.execute(
        "SELECT unit_price FROM house ORDER BY unit_price LIMIT 2 OFFSET 1444"
    ).fetchall()
    check("单价中位（中间两值）", (mid[0][0], mid[1][0]), (57979.0, 57992.0),
          "插值中位 57985.5；上中位 57992")

    # 12 均价双口径
    arith = one("SELECT ROUND(AVG(unit_price), 2) FROM house")
    weighted = one("SELECT ROUND(SUM(total_price*10000.0)/SUM(area), 2) FROM house")
    check("算术均价", arith, 64764.78)
    check("面积加权均价", weighted, 64028.12, f"与算术均值差 {arith - weighted:.2f}")

    # 13 M:N 朝向可用性（这是拆表的唯一理由，用真实查询证明）
    check("朝南房源数", one(
        "SELECT COUNT(*) FROM house h JOIN house_orientation o ON o.house_id=h.id "
        "WHERE o.direction='南'"), 1976)
    check("朝北房源数", one(
        "SELECT COUNT(*) FROM house h JOIN house_orientation o ON o.house_id=h.id "
        "WHERE o.direction='北'"), 1624)
    south_avg = one("SELECT ROUND(AVG(h.unit_price),2) FROM house h "
                    "JOIN house_orientation o ON o.house_id=h.id WHERE o.direction='南'")
    north_avg = one("SELECT ROUND(AVG(h.unit_price),2) FROM house h "
                    "JOIN house_orientation o ON o.house_id=h.id WHERE o.direction='北'")
    check("朝南均价 > 朝北均价", south_avg > north_avg, True,
          f"朝南 {south_avg} vs 朝北 {north_avg}（差 {south_avg - north_avg:.2f}）")

    # 14 维度冗余一致性：house 的 district_id 必须与 community 的一致
    mismatch = one(
        "SELECT COUNT(*) FROM house h JOIN community c ON c.id=h.community_id "
        "WHERE h.district_id <> c.district_id")
    check("house.district_id 与 community 冗余一致", mismatch, 0)

    # 15 伪街道过滤生效
    check("伪街道组合数", one("SELECT COUNT(*) FROM street WHERE is_pseudo=1"), 16)
    check("伪街道覆盖行数",
          one("SELECT SUM(house_count) FROM street WHERE is_pseudo=1"), 107)

    # 16 极值 / 软删除
    check("极值标记行数", one("SELECT COUNT(*) FROM house WHERE is_outlier=1"), 72)
    check("软删除行数", one("SELECT COUNT(*) FROM house WHERE is_deleted=1"), 0)

    # 17 区级聚合快照与实时聚合一致
    live = one("SELECT ROUND(AVG(unit_price),2) FROM house WHERE district_id=("
               "SELECT id FROM district WHERE name='西城')")
    snap = one("SELECT avg_unit_price FROM district WHERE name='西城'")
    check("西城区均价（快照 vs 实时）", (snap, live), (snap, snap),
          f"快照 {snap} / 实时 {live}")

    # 18 索引真的被用上（EXPLAIN 证明，而不是"声称"）
    plan = cur.execute(
        "EXPLAIN QUERY PLAN SELECT id, unit_price FROM house "
        "WHERE district_id=? AND unit_price BETWEEN ? AND ? "
        "ORDER BY unit_price LIMIT 20", (11, 50000, 80000)
    ).fetchall()
    plan_text = " | ".join(str(p[-1]) for p in plan)
    check("核心查询命中索引", "idx_house_district_unit" in plan_text, True, plan_text)

    # 19 CHECK 约束真的生效（尝试写入非法枚举）
    try:
        cur.execute("INSERT INTO house_orientation (house_id, direction) VALUES (1,'TEST')")
        con.rollback()
        check("枚举 CHECK 生效", False, True, "非法方向竟然写入成功")
    except sqlite3.IntegrityError as e:
        con.rollback()
        check("枚举 CHECK 生效", True, True, str(e))

    # 20 唯一约束真的生效（重复朝向）
    try:
        cur.execute("INSERT INTO house_orientation (house_id, direction) "
                    "SELECT house_id, direction FROM house_orientation LIMIT 1")
        con.rollback()
        check("唯一约束生效", False, True, "重复朝向竟然写入成功")
    except sqlite3.IntegrityError as e:
        con.rollback()
        check("唯一约束生效", True, True, str(e))

    con.close()

    print("\n=== SQL 层独立校验 ===")
    failed = 0
    for i, c in enumerate(checks, 1):
        mark = "OK  " if c["passed"] else "FAIL"
        if not c["passed"]:
            failed += 1
        print(f"[{mark}] {i:>2}. {c['name']}: 期望 {c['expected']} / 实测 {c['actual']}"
              + (f"  — {c['note']}" if c["note"] else ""))
    print(f"\n校验结果：{len(checks) - failed}/{len(checks)} 通过（{DB_FILE.name}，"
          f"{DB_FILE.stat().st_size:,} 字节）")
    return 0 if failed == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="建 SQLite 库并校验")
    ap.add_argument("--keep", action="store_true", help="复用已有 app.db，只做校验")
    args = ap.parse_args(argv)

    if not args.keep:
        build()
    if not DB_FILE.exists():
        print(f"[错误] 未找到 {DB_FILE}，请先不加 --keep 运行", file=sys.stderr)
        return 2
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
