"""从单一事实源 schema_model.py 生成五份产物。

    python db/gen_schema.py
        → db/schema.sql             MySQL 8.0 DDL（交付契约）
        → db/schema_sqlite.sql      SQLite DDL（本机实跑）
        → db/schema.dbml            DBML（dbdiagram.io）
        → docs/05-数据字典.xlsx      逐字段数据字典
        → docs/05-列映射表.md        53 列逐列映射
        → docs/05-ER.md             E-R 说明（含 Mermaid 源码）

设计意图：字段名只写一次。DDL / DBML / 字典 / 映射表 / ER 图全部由同一份定义渲染，
从机制上杜绝"表字段名与文档不一致"这类扣分点。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_model import (  # noqa: E402
    COLUMN_MAPPING,
    NOT_BUILT,
    RELATIONS,
    TABLES,
    TABLE_COMMENTS_CN,
)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db"
DOCS = ROOT / "docs"
DB_NAME = "bj_house_insight"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def topo_order(tables):
    """按外键依赖排序，让 DDL 自上而下可读。"""
    by_name = {t["name"]: t for t in tables}
    ordered, visiting, done = [], set(), set()

    def visit(name):
        if name in done or name not in by_name:
            return
        if name in visiting:  # 自引用/环：直接返回，交给 FOREIGN_KEY_CHECKS=0 兜底
            return
        visiting.add(name)
        for fk in by_name[name]["fks"]:
            visit(fk["ref_table"])
        visiting.discard(name)
        done.add(name)
        ordered.append(by_name[name])

    for t in tables:
        visit(t["name"])
    return ordered


def strip_type(t):
    """varchar(32) → varchar；enum('a','b') → enum。Mermaid 只接受简单类型名。"""
    return re.sub(r"\(.*", "", t).strip()


def esc(s):
    return str(s).replace("'", "''")


# ---------------------------------------------------------------------------
# 1. MySQL 8.0 DDL
# ---------------------------------------------------------------------------
def gen_mysql() -> str:
    out = []
    a = out.append
    a("-- ===========================================================================")
    a("-- 北京二手房行情洞察系统 · MySQL 8.0 DDL")
    a("-- 本文件由 db/gen_schema.py 从 db/schema_model.py 生成，请勿手工修改。")
    a("--")
    a("-- 设计要点：")
    a("--   1. 金额 DECIMAL(10,2)、面积 DECIMAL(8,2)，全库禁用 FLOAT")
    a("--   2. 朝向为多值字段，拆 house_orientation 实现 M:N")
    a("--   3. house 冗余 district_id/street_id/community_id，换查询性能")
    a("--   4. 主键/外键/时间戳/中文注释齐全；不建触发器与存储过程")
    a("-- ===========================================================================")
    a("")
    a(f"DROP DATABASE IF EXISTS `{DB_NAME}`;")
    a(f"CREATE DATABASE `{DB_NAME}` DEFAULT CHARACTER SET utf8mb4 "
      f"DEFAULT COLLATE utf8mb4_0900_ai_ci;")
    a(f"USE `{DB_NAME}`;")
    a("SET NAMES utf8mb4;")
    a("SET FOREIGN_KEY_CHECKS = 0;")
    a("")

    ordered = topo_order(TABLES)
    for t in reversed(ordered):
        a(f"DROP TABLE IF EXISTS `{t['name']}`;")
    a("")

    for t in ordered:
        a(f"-- {t['comment']}")
        a(f"CREATE TABLE `{t['name']}` (")
        lines = []
        for col in t["columns"]:
            line = f"  `{col['name']}` {col['mysql']}"
            line += f" COMMENT '{esc(col['comment'])}'"
            lines.append(line)
        # CHECK 一律放在表级：MySQL 列定义中 COMMENT 必须早于 check_constraint_definition，
        # 列级混写极易生成非法 DDL，表级写法无歧义。
        for col in t["columns"]:
            chk = col.get("check")
            if chk and not col["mysql"].startswith("ENUM("):
                lines.append(
                    f"  CONSTRAINT `chk_{t['name']}_{col['name']}` CHECK ({chk})"
                )
        lines.append(f"  PRIMARY KEY ({', '.join(f'`{c}`' for c in t['pk'])})")
        for u in t["uniques"]:
            cols = ", ".join(f"`{c}`" for c in u["cols"])
            lines.append(f"  UNIQUE KEY `{u['name']}` ({cols})")
        for ix in t["indexes"]:
            cols = ", ".join(f"`{c}`" for c in ix["cols"])
            lines.append(f"  KEY `{ix['name']}` ({cols})")
        for fk in t["fks"]:
            lines.append(
                f"  CONSTRAINT `fk_{t['name']}_{fk['col']}` FOREIGN KEY (`{fk['col']}`) "
                f"REFERENCES `{fk['ref_table']}` (`{fk['ref_col']}`) "
                f"ON DELETE RESTRICT ON UPDATE CASCADE"
            )
        a(",\n".join(lines))
        a(f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci "
          f"COMMENT='{esc(t['comment'])}';")
        a("")

        for ix in t["indexes"]:
            a(f"-- 索引 {ix['name']}：{ix['comment']}")
        for u in t["uniques"]:
            a(f"-- 唯一键 {u['name']}：{u['comment']}")
        if t["indexes"] or t["uniques"]:
            a("")

    a("SET FOREIGN_KEY_CHECKS = 1;")
    a("")
    a("-- ===========================================================================")
    a("-- 种子数据：字典类基础行（评分/角色）")
    a("-- 业务数据（2890 条房源）由 db/load_sqlite.py 或导入接口写入，不写死在此。")
    a("-- ===========================================================================")
    a("INSERT INTO `role` (`code`, `name`) VALUES")
    a("  ('visitor', '访客'),")
    a("  ('user', '注册用户'),")
    a("  ('admin', '管理员');")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 2. SQLite DDL（本机实跑）
# ---------------------------------------------------------------------------
def gen_sqlite() -> str:
    out = []
    a = out.append
    a("-- ===========================================================================")
    a("-- 北京二手房行情洞察系统 · SQLite DDL（本机实跑用）")
    a("-- 本文件由 db/gen_schema.py 生成，请勿手工修改。")
    a("--")
    a("-- 与 MySQL 版的方言差异：")
    a("--   ENUM(...)      → TEXT + CHECK 约束")
    a("--   DECIMAL(p,s)   → NUMERIC（SQLite 无原生定点类型，精度由应用层与 CHECK 保证）")
    a("--   DATETIME       → TEXT (ISO-8601)")
    a("--   AUTO_INCREMENT → INTEGER PRIMARY KEY AUTOINCREMENT")
    a("--   表/字段 COMMENT → 由 docs/05-数据字典.xlsx 承载")
    a("-- ===========================================================================")
    a("")
    a("PRAGMA foreign_keys = ON;")
    a("")

    ordered = topo_order(TABLES)
    for t in reversed(ordered):
        a(f"DROP TABLE IF EXISTS {t['name']};")
    a("")

    for t in ordered:
        a(f"-- {t['comment']}")
        a(f"CREATE TABLE {t['name']} (")
        lines = []
        for col in t["columns"]:
            lines.append(f"  {col['name']} {col['sqlite']}")
        # SQLite 没有 ENUM，所有枚举都必须靠 CHECK 约束兜住取值
        for col in t["columns"]:
            chk = col.get("check")
            if chk:
                lines.append(f"  CONSTRAINT chk_{t['name']}_{col['name']} CHECK ({chk})")
        if len(t["pk"]) == 1 and t["pk"][0] == "id":
            pass  # 已由 INTEGER PRIMARY KEY AUTOINCREMENT 承载
        else:
            lines.append(f"  PRIMARY KEY ({', '.join(t['pk'])})")
        for u in t["uniques"]:
            lines.append(f"  UNIQUE ({', '.join(u['cols'])})")
        for fk in t["fks"]:
            lines.append(
                f"  FOREIGN KEY ({fk['col']}) REFERENCES {fk['ref_table']} "
                f"({fk['ref_col']}) ON DELETE RESTRICT ON UPDATE CASCADE"
            )
        a(",\n".join(lines))
        a(");")
        for ix in t["indexes"]:
            a(f"CREATE INDEX {ix['name']} ON {t['name']} ({', '.join(ix['cols'])});  "
              f"-- {ix['comment']}")
        a("")

    a("INSERT INTO role (code, name) VALUES")
    a("  ('visitor', '访客'),")
    a("  ('user', '注册用户'),")
    a("  ('admin', '管理员');")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 3. DBML
# ---------------------------------------------------------------------------
def gen_dbml() -> str:
    out = []
    a = out.append
    a("// 北京二手房行情洞察系统 · DBML（粘贴到 dbdiagram.io 可直接出图）")
    a("// 本文件由 db/gen_schema.py 生成，请勿手工修改。")
    a("")
    for t in topo_order(TABLES):
        alias = TABLE_COMMENTS_CN.get(t["name"], t["name"])
        a(f'Table {t["name"]} as "{alias}" [note: \'{esc(t["comment"])}\'] {{')
        for col in t["columns"]:
            attrs = []
            if col["name"] in t["pk"]:
                attrs.append("pk")
            if "AUTO_INCREMENT" in col["mysql"]:
                attrs.append("increment")
            if not col["null"] and "NULL" not in col["mysql"].split()[1:2]:
                attrs.append("not null")
            attrs.append(f"note: '{esc(col['comment'])}'")
            a(f'  {col["name"]} {col["dbml"]} [{", ".join(attrs)}]')
        for u in t["uniques"]:
            a(f'  indexes {{ ({", ".join(u["cols"])}) [unique, name: \'{u["name"]}\'] }}')
        for ix in t["indexes"]:
            a(f'  indexes {{ ({", ".join(ix["cols"])}) [name: \'{ix["name"]}\'] }}')
        a("}")
        a("")
    a("// ---------------- 关系 ----------------")
    for left_t, left_c, right_t, right_c, _card, _label, _n in RELATIONS:
        a(f"Ref: {right_t}.{right_c} > {left_t}.{left_c}")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 4. 数据字典 xlsx
# ---------------------------------------------------------------------------
def gen_dictionary_xlsx(path: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1A4D8F")
    head_font = Font(color="FFFFFF", bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")

    def style_header(ws, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.freeze_panes = "A2"

    # 汇总页
    ws = wb.active
    ws.title = "汇总"
    ws.append(["表名", "中文名", "字段数", "主键", "说明"])
    for t in TABLES:
        ws.append([t["name"], TABLE_COMMENTS_CN.get(t["name"], ""), len(t["columns"]),
                   ", ".join(t["pk"]), t["comment"]])
    style_header(ws, 5)
    for i, w in enumerate([24, 16, 8, 10, 70], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap

    # 逐表页
    for t in TABLES:
        ws = wb.create_sheet(t["name"][:31])
        ws.append(["#", "字段名", "类型（MySQL 8.0）", "类型（SQLite）",
                   "可空", "默认/约束", "注释", "备注"])
        for i, col in enumerate(t["columns"], start=1):
            ws.append([
                i,
                col["name"],
                col["mysql"],
                col["sqlite"],
                "是" if col["null"] else "否",
                col.get("check") or "",
                col["comment"],
                col.get("note") or "",
            ])
        style_header(ws, 8)
        for letter, w in zip("ABCDEFGH", [5, 20, 44, 30, 6, 34, 52, 40]):
            ws.column_dimensions[letter].width = w
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = wrap

    # 53 列映射页
    ws = wb.create_sheet("53列映射")
    ws.append(["#", "分组", "Excel 原列名", "目标表.字段", "转换规则",
               "保留", "理由"])
    for i, m in enumerate(COLUMN_MAPPING, start=1):
        ws.append([i, m["group"], m["excel_column"], m["target"], m["rule"],
                   "保留" if m["keep"] else "丢弃", m["reason"]])
    style_header(ws, 7)
    for letter, w in zip("ABCDEFG", [5, 22, 20, 40, 52, 8, 64]):
        ws.column_dimensions[letter].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap

    # 索引页
    ws = wb.create_sheet("索引方案")
    ws.append(["表", "索引/唯一键名", "类型", "字段顺序", "理由"])
    for t in TABLES:
        for u in t["uniques"]:
            ws.append([t["name"], u["name"], "UNIQUE", " → ".join(u["cols"]),
                       u["comment"]])
        for ix in t["indexes"]:
            ws.append([t["name"], ix["name"], "INDEX", " → ".join(ix["cols"]),
                       ix["comment"]])
    style_header(ws, 5)
    for letter, w in zip("ABCDE", [20, 34, 10, 44, 90]):
        ws.column_dimensions[letter].width = w

    # 不建的表
    ws = wb.create_sheet("不建的表")
    ws.append(["表/实体", "不建的理由"])
    for item in NOT_BUILT:
        ws.append([item["table"], item["reason"]])
    style_header(ws, 2)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 96
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ---------------------------------------------------------------------------
# 5. 53 列映射 Markdown
# ---------------------------------------------------------------------------
def gen_mapping_md() -> str:
    out = []
    a = out.append
    total = len(COLUMN_MAPPING)
    keep = sum(1 for m in COLUMN_MAPPING if m["keep"])
    a("# 05 · 53 列逐列映射表")
    a("")
    a("> 本表由 `db/gen_schema.py` 从 `db/schema_model.py` 生成，与 `schema.sql` / 数据字典同源。")
    a("")
    a(f"共 **{total}** 个 Excel 列：**保留并入库 {keep} 列**，**丢弃 {total - keep} 列**"
      f"（36 个 one-hot + 2 个派生区间列，且 one-hot 中的“其他”按 D2 单独说明）。")
    a("")
    a("## 汇总")
    a("")
    a("| 分组 | 列数 | 保留 | 丢弃 |")
    a("|---|---|---|---|")
    groups = {}
    for m in COLUMN_MAPPING:
        g = groups.setdefault(m["group"], {"n": 0, "keep": 0})
        g["n"] += 1
        g["keep"] += 1 if m["keep"] else 0
    for g, v in groups.items():
        a(f"| {g} | {v['n']} | {v['keep']} | {v['n'] - v['keep']} |")
    a(f"| **合计** | **{total}** | **{keep}** | **{total - keep}** |")
    a("")

    for g in groups:
        a(f"## {g}")
        a("")
        a("| # | Excel 列名 | 目标表.字段 | 转换规则 | 保留 | 理由 |")
        a("|---|---|---|---|---|---|")
        for i, m in enumerate(COLUMN_MAPPING, start=1):
            if m["group"] != g:
                continue
            mark = "✅" if m["keep"] else "❌"
            a(f"| {i} | `{m['excel_column']}` | `{m['target']}` | {m['rule']} | {mark} | "
              f"{m['reason']} |")
        a("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 6. E-R 说明（含 Mermaid）
# ---------------------------------------------------------------------------
TRADEOFFS = [
    ("为什么反范式（house 冗余 district_id / street_id / community_id）",
     "房源列表的核心查询是“按区＋价格区间筛选并按单价排序”。若只留 community_id，"
     "每次检索都要 3 张表 JOIN 才能拿到区级过滤条件，执行计划无法用上 (district_id, unit_price) "
     "复合索引。冗余三列后，区/街道/小区三级筛选都能在最左前缀上命中索引，"
     "代价是导入时统一写入、不做跨表更新——数据是只读快照，一致性风险为零。"),
    ("为什么不存 one-hot（36 列为什么必须丢）",
     "one-hot 把“装修”摊成 4 列后，任何“按装修分组算均价”都要写 4 个分支或 4 次 UNION；"
     "而装修“其他”列更与另三列线性相关（四列和恒为 1，549 行），属冗余基线列，"
     "保留会让任何回归/相关分析出现完全共线。丢弃后回归原文字段，分组聚合重新变成一句话，"
     "且枚举取值天然受约束。"),
    ("为什么朝向要拆成 M:N",
     "朝向是“南 北”这样的多值字符串，1786 条（61.8%）是多值，组合多达 61 种。"
     "不拆的话，“朝南房源的均价”这类分析根本无法表达——它会退化成对 61 个组合字符串做统计。"
     "拆成 house_orientation 后，单个方向成为一等维度，且能以 (direction, house_id) 索引反查，"
     "这正是“朝南/朝北溢价”这张图能成立的前提。"),
    ("为什么 unit_price 用普通列而不是生成列",
     "源数据里 单价 与 总价×10000÷面积 存在 1 元级舍入差异（最大 1.00 元/㎡，超容差 0 条）。"
     "若改为生成列，会把原始挂牌单价覆盖成计算值，等于篡改了源数据；"
     "本系统保留源值并在 ETL 层断言误差上限，既保住真实性又保住可校验性。"),
    ("为什么不建 house_tag 表",
     "房源标签只有“近地铁/不近地铁”两个取值，且与 one-hot 近地铁列差异 0 条，"
     "建表后每行只是重复 house.near_subway，零信息增量。这属于手册自己指出的“为好看而过度拆分”。"),
]


def gen_er_md() -> str:
    out = []
    a = out.append
    a("# 05 · E-R 模型与数据库设计")
    a("")
    a("> 本文件由 `db/gen_schema.py` 从 `db/schema_model.py` 生成；"
      "DDL、DBML、数据字典、列映射表与本文件同源，字段名不存在漂移可能。")
    a("")
    a("## 1. 概念模型")
    a("")
    a(f"共 **{len(TABLES)}** 张表，覆盖查询、分析、对比、估价、导入治理五类场景。"
      "核心链路是 `区 → 街道 → 小区 → 房源`，朝向与收藏以 M:N 拆解。")
    a("")
    a("| 表名 | 中文名 | 行数（实测/预估） | 字段数 | 说明 |")
    a("|---|---|---|---|---|")
    rows_expect = {
        "district": "17", "street": "264", "community": "1865", "house": "2890",
        "house_orientation": "4806", "import_batch": "按导入次数",
        "data_quality_issue": "按问题数", "role": "3", "app_user": "按注册数",
        "favorite": "按收藏数", "operation_log": "按操作数",
        "valuation_record": "按估价次数",
    }
    for t in TABLES:
        a(f"| `{t['name']}` | {TABLE_COMMENTS_CN.get(t['name'], '')} | "
          f"{rows_expect.get(t['name'], '—')} | {len(t['columns'])} | {t['comment']} |")
    a("")

    a("## 2. E-R 图（Mermaid）")
    a("")
    a("只画主键、外键与 3 个核心业务字段，完整字段见数据字典，避免图过密。")
    a("")
    a("```mermaid")
    a("erDiagram")
    for left_t, _lc, right_t, right_c, card, label, _n in RELATIONS:
        a(f'  {left_t} {card} {right_t} : "{label}"')
    a("")
    for t in TABLES:
        fks = {fk["col"] for fk in t["fks"]}
        shown = []
        for col in t["columns"]:
            if col["name"] in t["pk"]:
                shown.append(f"    {strip_type(col['dbml'])} {col['name']} PK")
        for col in t["columns"]:
            if col["name"] in fks:
                shown.append(f"    {strip_type(col['dbml'])} {col['name']} FK")
        business = [c for c in t["columns"]
                    if c["name"] not in t["pk"] and c["name"] not in fks
                    and c["name"] not in ("created_at", "updated_at")]
        for col in business[:3]:
            shown.append(f"    {strip_type(col['dbml'])} {col['name']}")
        a(f"  {t['name']} {{")
        for line in shown:
            a(line)
        a("  }")
    a("```")
    a("")

    a("## 3. 关系与基数")
    a("")
    a("| 主表 | 从表 | 关系 | 基数 | 说明 |")
    a("|---|---|---|---|---|")
    for left_t, left_c, right_t, right_c, _card, label, n in RELATIONS:
        a(f"| `{left_t}.{left_c}` | `{right_t}.{right_c}` | {label} | {n} | "
          f"{TABLE_COMMENTS_CN.get(right_t, right_t)} |")
    a("")
    a("> 无孤立实体：`role` / `import_batch` / `app_user` 均被下游表引用；"
      "字典类小表（`role`）保持独立是因其取值需要人工维护。")
    a("")

    a("## 4. 索引方案与最左前缀依据")
    a("")
    a("| 表 | 索引名 | 类型 | 字段顺序 | 依据 |")
    a("|---|---|---|---|---|")
    for t in TABLES:
        for u in t["uniques"]:
            a(f"| `{t['name']}` | `{u['name']}` | UNIQUE | {' → '.join(u['cols'])} | "
              f"{u['comment']} |")
        for ix in t["indexes"]:
            a(f"| `{t['name']}` | `{ix['name']}` | INDEX | {' → '.join(ix['cols'])} | "
              f"{ix['comment']} |")
    a("")
    a("### 4.1 四类核心查询的索引覆盖")
    a("")
    a("| 核心查询 | 命中索引 | 最左前缀说明 |")
    a("|---|---|---|")
    a("| 按区 + 价格区间筛选并按单价排序 | `idx_house_district_unit` | "
      "`district_id` 命中等值条件，`unit_price` 同时满足 ORDER BY，避免 filesort |")
    a("| 按区 + 街道筛选并排序 | `idx_house_district_street_unit` | 三级最左前缀依次命中 |")
    a("| 按小区聚合均价 / 同小区相似房源 | `idx_house_community_unit` | "
      "`community_id` 等值 + `unit_price` 有序扫描，AVG 走覆盖索引前缀 |")
    a("| 小区名前缀搜索 | `idx_community_name` | `LIKE 'kw%'` 可用索引；"
      "`LIKE '%kw%'` 不可用，故接口层对关键词做前缀匹配并说明 |")
    a("")
    a("### 4.2 深分页")
    a("")
    a("2890 行规模下 `LIMIT offset, n` 无性能问题，但接口层仍按 keyset 方式实现"
      "（`WHERE (unit_price, id) < (?, ?)`）并在注释中说明切换条件，"
      "以应对手册要求扩展到的 100 万行。")
    a("")
    a("### 4.3 覆盖索引与生成列")
    a("")
    a("- 聚合查询所需列（`district_id`、`unit_price`、`total_price`、`area`）已分布在上述复合索引中，"
      "必要时可扩展为覆盖索引，但当前规模收益不明显，故不提前优化。")
    a("- `unit_price` **不改成生成列**，理由见 §6。")
    a("")

    a("## 5. 明确不建的表")
    a("")
    a("| 表/实体 | 不建的理由 |")
    a("|---|---|")
    for item in NOT_BUILT:
        a(f"| {item['table']} | {item['reason']} |")
    a("")

    a("## 6. 设计取舍说明")
    a("")
    for i, (title, body) in enumerate(TRADEOFFS, start=1):
        a(f"### 6.{i} {title}")
        a("")
        a(body)
        a("")

    a("## 7. 方言差异（MySQL 交付 / SQLite 实跑）")
    a("")
    a("| 项 | MySQL 8.0（`schema.sql`） | SQLite（`schema_sqlite.sql`） |")
    a("|---|---|---|")
    a("| 枚举 | `ENUM('低','中',...)` | `TEXT` + `CHECK (... IN (...))` |")
    a("| 定点数 | `DECIMAL(10,2)` 原生精度 | `NUMERIC`（无原生定点，靠 CHECK 与应用层） |")
    a("| 自增 | `AUTO_INCREMENT` | `INTEGER PRIMARY KEY AUTOINCREMENT` |")
    a("| 时间 | `DATETIME(3)` + `ON UPDATE` | `TEXT`(ISO-8601) + `DEFAULT strftime(...)` |")
    a("| 注释 | `COMMENT` 落库 | 由 `05-数据字典.xlsx` 承载 |")
    a("| 外键校验 | 默认开启 | 需 `PRAGMA foreign_keys = ON` |")
    a("")
    a("> MySQL 版作为**交付契约**（老师按此建库）；SQLite 版用于**本机实跑验证**，"
      "两者字段名、外键、索引完全一致，由同一份 `schema_model.py` 生成。")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
def main() -> int:
    DB.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    targets = {
        DB / "schema.sql": gen_mysql(),
        DB / "schema_sqlite.sql": gen_sqlite(),
        DB / "schema.dbml": gen_dbml(),
        DOCS / "05-列映射表.md": gen_mapping_md(),
        DOCS / "05-ER.md": gen_er_md(),
    }
    for path, content in targets.items():
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"生成 {path.relative_to(ROOT)}  ({len(content):,} 字符)")

    xlsx = DOCS / "05-数据字典.xlsx"
    gen_dictionary_xlsx(xlsx)
    print(f"生成 {xlsx.relative_to(ROOT)}  ({xlsx.stat().st_size:,} 字节)")

    n_cols = sum(len(t["columns"]) for t in TABLES)
    n_idx = sum(len(t["indexes"]) + len(t["uniques"]) for t in TABLES)
    n_fk = sum(len(t["fks"]) for t in TABLES)
    print(f"\n汇总：{len(TABLES)} 张表 / {n_cols} 个字段 / {n_idx} 个索引与唯一键 / "
          f"{n_fk} 个外键 / 映射 {len(COLUMN_MAPPING)} 列")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
