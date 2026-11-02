"""数据库结构定义 —— 全项目唯一事实源。

一份定义，生成五份产物（避免字段名在 DDL / DBML / 数据字典 / 映射表 / E-R 之间漂移）：
    db/schema.sql            MySQL 8.0 DDL（交付契约）
    db/schema_sqlite.sql     SQLite DDL（本机实跑验证）
    db/schema.dbml           DBML（dbdiagram.io 出图）
    docs/05-数据字典.xlsx     逐字段数据字典
    docs/05-列映射表.md       53 列 → 目标字段逐列映射
    docs/05-ER 图（Mermaid 源码）

字段类型约定（手册硬约束）：
    金额     DECIMAL(10,2)  万元 / 元每平米      —— 全库禁用 FLOAT
    面积     DECIMAL(8,2)
    房龄     TINYINT UNSIGNED
    楼层层级 ENUM('低','中','高','顶层','底层','地下','上叠','未知')
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 列构造helper：一次写四个方言（MySQL / SQLite / DBML / 注释 + 约束）
# ---------------------------------------------------------------------------
def C(name, mysql, sqlite, dbml, comment, *, null=False, default=None, check=None, note=None):
    return {
        "name": name,
        "mysql": mysql,
        "sqlite": sqlite,
        "dbml": dbml,
        "comment": comment,
        "null": null,
        "default": default,
        "check": check,
        "note": note,
    }


def pk(name="id", big=True):
    """自增主键。"""
    if big:
        return C(
            name,
            "BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            "bigint",
            "主键，自增",
        )
    return C(
        name,
        "INT UNSIGNED NOT NULL AUTO_INCREMENT",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "int",
        "主键，自增",
    )


def fk_col(name, comment, *, null=False):
    return C(
        name,
        "BIGINT UNSIGNED NOT NULL" if not null else "BIGINT UNSIGNED NULL",
        "INTEGER NOT NULL" if not null else "INTEGER",
        "bigint",
        comment,
        null=null,
    )


def timestamps():
    return [
        C("created_at", "DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)",
          "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
          "datetime", "创建时间"),
        C("updated_at", "DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) "
                        "ON UPDATE CURRENT_TIMESTAMP(3)",
          "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
          "datetime", "更新时间"),
    ]


DECORATION = ["毛坯", "简装", "精装", "其他"]
STRUCTURE = ["板楼", "塔楼", "板塔结合", "独栋别墅", "平房"]
FLOOR_LEVEL = ["低", "中", "高", "顶层", "底层", "地下", "上叠", "未知"]
DIRECTION = ["东", "南", "西", "北", "东北", "东南", "西南", "西北"]


def _enum_list(values):
    return ", ".join(f"'{v}'" for v in values)


# ---------------------------------------------------------------------------
# 表定义
# ---------------------------------------------------------------------------
TABLES = [
    {
        "name": "district",
        "comment": "行政区（17 行，含亦庄开发区）",
        "columns": [
            pk("id"),
            C("name", "VARCHAR(32) NOT NULL", "TEXT NOT NULL", "varchar(32)",
              "区名，唯一；取原始“所在区”原文", note="17 个区"),
            C("house_count", "INT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "int", "在售套数（聚合快照，ETL 批次刷新）"),
            C("avg_unit_price", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "区均价 元/㎡（算术均值）", null=True),
            C("median_unit_price", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "区中位单价 元/㎡", null=True),
            C("median_total_price", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "区中位总价 万元", null=True),
            C("avg_area", "DECIMAL(8,2) NULL", "NUMERIC", "decimal(8,2)",
              "区平均面积 ㎡", null=True),
            C("avg_age", "DECIMAL(5,2) NULL", "NUMERIC", "decimal(5,2)",
              "区平均房龄 年", null=True),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_district_name", "cols": ["name"],
                     "comment": "区名唯一"}],
        "indexes": [],
        "fks": [],
    },
    {
        "name": "street",
        "comment": "街道/镇（264 行；街道名去重仅 237，故必须与区联合唯一）",
        "columns": [
            pk("id"),
            fk_col("district_id", "所属区 id"),
            C("name", "VARCHAR(64) NOT NULL", "TEXT NOT NULL", "varchar(64)",
              "街道名，取原始“所在街道或镇”原文", note="26 个街道名跨区重名"),
            C("is_pseudo", "TINYINT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "tinyint", "伪街道标记：1=“XX其他”聚合桶，共 16 个组合/107 行",
              check="is_pseudo IN (0,1)"),
            C("house_count", "INT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "int", "在售套数（聚合快照）"),
            C("avg_unit_price", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "街道均价 元/㎡（聚合快照）", null=True),
            C("median_total_price", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "街道中位总价 万元（聚合快照）", null=True),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_street_district_name", "cols": ["district_id", "name"],
                     "comment": "联合唯一：同名街道可属不同区"}],
        "indexes": [{"name": "idx_street_district", "cols": ["district_id"],
                     "comment": "按区展开街道列表（检索页联动）"}],
        "fks": [{"col": "district_id", "ref_table": "district", "ref_col": "id"}],
    },
    {
        "name": "community",
        "comment": "小区（1865 行；小区名去重 1864，绿地中央广场跨昌平/通州）",
        "columns": [
            pk("id", big=True),
            fk_col("district_id", "所属区 id"),
            fk_col("street_id", "所属街道 id（同小区多街道时取众数）"),
            C("name", "VARCHAR(128) NOT NULL", "TEXT NOT NULL", "varchar(128)",
              "小区名，已去除尾随空格"),
            C("house_count", "INT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "int", "在售套数（聚合快照，中位 1、最大 12）"),
            C("avg_unit_price", "DECIMAL(10,2) NULL", "NUMERIC NULL", "decimal(10,2)",
              "小区均价 元/㎡（聚合快照）"),
            C("median_total_price", "DECIMAL(10,2) NULL", "NUMERIC NULL", "decimal(10,2)",
              "小区中位总价 万元（聚合快照）"),
            C("avg_area", "DECIMAL(8,2) NULL", "NUMERIC NULL", "decimal(8,2)",
              "小区平均面积 ㎡"),
            C("avg_age", "DECIMAL(5,2) NULL", "NUMERIC NULL", "decimal(5,2)",
              "小区平均房龄 年"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_community_district_name", "cols": ["district_id", "name"],
                     "comment": "联合唯一：同名小区可属不同区（1 例）"}],
        "indexes": [
            {"name": "idx_community_street", "cols": ["street_id"],
             "comment": "同街道小区排行（小区画像页）"},
            {"name": "idx_community_name", "cols": ["name"],
             "comment": "小区名前缀搜索；LIKE 'kw%' 可用索引，LIKE '%kw%' 不可"},
        ],
        "fks": [
            {"col": "district_id", "ref_table": "district", "ref_col": "id"},
            {"col": "street_id", "ref_table": "street", "ref_col": "id"},
        ],
    },
    {
        "name": "house",
        "comment": "房源主表（2890 行；district/street/community 三列为反范式冗余）",
        "columns": [
            pk("id", big=True),
            fk_col("district_id", "区 id（冗余，换查询性能）"),
            fk_col("street_id", "街道 id（冗余）"),
            fk_col("community_id", "小区 id（冗余）"),
            C("batch_id", "BIGINT UNSIGNED NULL", "INTEGER", "bigint",
              "导入批次 id；seed 数据为空", null=True),
            C("source_row_no", "INT UNSIGNED NOT NULL", "INTEGER NOT NULL", "int",
              "源文件数据行号（1 基，不含表头），用于全链路回溯",
              note="与 batch_id 组成唯一，保证可追溯"),
            C("room", "TINYINT UNSIGNED NOT NULL", "INTEGER NOT NULL", "tinyint",
              "室（1–12）", check="room BETWEEN 1 AND 20"),
            C("hall", "TINYINT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "tinyint", "厅（0–4）；厅=0 为开间，合法，共 101 条",
              check="hall BETWEEN 0 AND 10"),
            C("area", "DECIMAL(8,2) NOT NULL", "NUMERIC NOT NULL", "decimal(8,2)",
              "建筑面积 ㎡（16.07–747.23）", check="area > 0 AND area <= 1000"),
            C("total_price", "DECIMAL(10,2) NOT NULL", "NUMERIC NOT NULL", "decimal(10,2)",
              "挂牌总价 万元（36–8000）", check="total_price > 0"),
            C("unit_price", "DECIMAL(10,2) NOT NULL", "NUMERIC NOT NULL", "decimal(10,2)",
              "挂牌单价 元/㎡（12742–179843）；与总价/面积误差 ≤1 元",
              note="保留源值而非生成列：源值存在 1 元级舍入差异，生成列会覆盖原始值"),
            C("floor_level", f"ENUM({_enum_list(FLOOR_LEVEL)}) NOT NULL DEFAULT '未知'",
              "TEXT NOT NULL DEFAULT '未知'",
              "enum('低','中','高','顶层','底层','地下','上叠','未知')",
              "解析后楼层层级；缺层级（纯数字）记为“未知”",
              check=f"floor_level IN ({_enum_list(FLOOR_LEVEL)})"),
            C("floor_total", "TINYINT UNSIGNED NULL", "INTEGER", "tinyint",
              "总层数；解析失败为 NULL", null=True),
            C("floor_raw", "VARCHAR(32) NULL", "TEXT", "varchar(32)",
              "楼层原文，保留以便回溯", null=True),
            C("orientation_text", "VARCHAR(32) NULL", "TEXT", "varchar(32)",
              "朝向标准化原文（固定顺序，空格分隔）；明细见 house_orientation", null=True),
            C("decoration", f"ENUM({_enum_list(DECORATION)}) NULL",
              "TEXT", "enum('毛坯','简装','精装','其他')",
              "装修：精装1313/简装970/其他549/毛坯58", null=True,
              check=f"decoration IN ({_enum_list(DECORATION)})"),
            C("structure", f"ENUM({_enum_list(STRUCTURE)}) NULL",
              "TEXT", "enum('板楼','塔楼','板塔结合','独栋别墅','平房')",
              "建筑结构：板楼1806/塔楼629/板塔结合453/独栋1/平房1", null=True,
              check=f"structure IN ({_enum_list(STRUCTURE)})"),
            C("house_age", "TINYINT UNSIGNED NULL", "INTEGER", "tinyint",
              "房龄 年（3–50，以 2024 为基准年）", null=True),
            C("near_subway", "TINYINT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "tinyint", "是否近地铁（1=近，1308 条）；由“房源标签”归并而来",
              check="near_subway IN (0,1)"),
            C("is_outlier", "TINYINT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "tinyint", "极值标记（P0.5–P99.5 三指标并集，72 行）；只标记不删除",
              check="is_outlier IN (0,1)"),
            C("abnormal_layout", "TINYINT UNSIGNED NOT NULL DEFAULT 0",
              "INTEGER NOT NULL DEFAULT 0", "tinyint",
              "非常规户型标记（1室2厅，12 条）；保留不清洗",
              check="abnormal_layout IN (0,1)"),
            C("is_deleted", "TINYINT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "tinyint", "软删除标记", check="is_deleted IN (0,1)"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_house_batch_row", "cols": ["batch_id", "source_row_no"],
                     "comment": "同批次内源行号唯一，保证可追溯且可重复导入不重复"}],
        "indexes": [
            {"name": "idx_house_district_unit", "cols": ["district_id", "unit_price"],
             "comment": "核心查询①按区筛选并按单价排序：最左前缀 district_id 命中 WHERE，"
                        "第二列直接满足 ORDER BY，避免 filesort"},
            {"name": "idx_house_district_street_unit",
             "cols": ["district_id", "street_id", "unit_price"],
             "comment": "核心查询②区+街道筛选并排序：三级最左前缀"},
            {"name": "idx_house_community_unit", "cols": ["community_id", "unit_price"],
             "comment": "核心查询③同小区相似房源召回（估价降级链第一级）"},
            {"name": "idx_house_price_filter", "cols": ["total_price", "area"],
             "comment": "总价/面积区间筛选（双滑块）"},
            {"name": "idx_house_age", "cols": ["house_age"],
             "comment": "房龄段统计（看板分组）"},
            {"name": "idx_house_decoration", "cols": ["decoration"],
             "comment": "装修溢价聚合"},
            {"name": "idx_house_is_outlier", "cols": ["is_outlier"],
             "comment": "分析层默认排除/包含极值的开关"},
        ],
        "fks": [
            {"col": "district_id", "ref_table": "district", "ref_col": "id"},
            {"col": "street_id", "ref_table": "street", "ref_col": "id"},
            {"col": "community_id", "ref_table": "community", "ref_col": "id"},
            {"col": "batch_id", "ref_table": "import_batch", "ref_col": "id"},
        ],
    },
    {
        "name": "house_orientation",
        "comment": "房源-朝向关联表（4806 行）：朝向是“南 北”式多值，必须拆 M:N",
        "columns": [
            pk("id", big=True),
            fk_col("house_id", "房源 id"),
            C("direction", f"ENUM({_enum_list(DIRECTION)}) NOT NULL",
              "TEXT NOT NULL", "enum('东','南','西','北','东北','东南','西南','西北')",
              "标准方向；南1976/北1624/东368/西363/西南160/东南159/西北84/东北72",
              check=f"direction IN ({_enum_list(DIRECTION)})"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_orientation_house_direction",
                     "cols": ["house_id", "direction"], "comment": "同一房源同一方向只出现一次"}],
        "indexes": [
            {"name": "idx_orientation_direction", "cols": ["direction", "house_id"],
             "comment": "“朝南房源均价”这类反查：以方向为最左前缀"},
        ],
        "fks": [{"col": "house_id", "ref_table": "house", "ref_col": "id"}],
    },
    {
        "name": "import_batch",
        "comment": "导入批次（每次 Excel 导入一行，支撑质量报告与审计）",
        "columns": [
            pk("id", big=True),
            C("file_name", "VARCHAR(255) NOT NULL", "TEXT NOT NULL", "varchar(255)",
              "原始文件名"),
            C("file_md5", "CHAR(32) NOT NULL", "TEXT NOT NULL", "char(32)",
              "文件 MD5，用于识别重复导入"),
            C("total_rows", "INT UNSIGNED NOT NULL", "INTEGER NOT NULL", "int", "原始行数"),
            C("loaded_rows", "INT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "int", "入库行数"),
            C("rejected_rows", "INT UNSIGNED NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0",
              "int", "拒收行数"),
            C("status", "ENUM('pending','running','success','partial','failed') "
                        "NOT NULL DEFAULT 'pending'",
              "TEXT NOT NULL DEFAULT 'pending'",
              "enum('pending','running','success','partial','failed')", "批次状态",
              check="status IN ('pending','running','success','partial','failed')"),
            C("operator_id", "BIGINT UNSIGNED NULL", "INTEGER", "bigint",
              "操作人（管理员）id", null=True),
            C("duration_ms", "INT UNSIGNED NULL", "INTEGER", "int", "耗时毫秒", null=True),
            C("note", "VARCHAR(500) NULL", "TEXT", "varchar(500)", "备注/失败原因",
              null=True),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [],
        "indexes": [{"name": "idx_batch_created", "cols": ["created_at"],
                     "comment": "批次列表按时间倒序"}],
        "fks": [],
    },
    {
        "name": "data_quality_issue",
        "comment": "数据质量问题留痕（ETL 的问题台账直接落这张表）",
        "columns": [
            pk("id", big=True),
            fk_col("batch_id", "所属批次 id", null=True),
            C("rule_code", "VARCHAR(8) NOT NULL", "TEXT NOT NULL", "varchar(8)",
              "规则编号 R1–R12"),
            C("row_no", "INT UNSIGNED NULL", "INTEGER", "int", "源文件行号", null=True),
            C("field_name", "VARCHAR(64) NULL", "TEXT", "varchar(64)", "涉及字段", null=True),
            C("issue_type", "VARCHAR(64) NOT NULL", "TEXT NOT NULL", "varchar(64)",
              "问题类型，如 trailing_space / outlier_high / bucket_mismatch"),
            C("raw_value", "VARCHAR(255) NULL", "TEXT", "varchar(255)", "原值", null=True),
            C("fixed_value", "VARCHAR(255) NULL", "TEXT", "varchar(255)", "修正值",
              null=True),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [],
        "indexes": [
            {"name": "idx_issue_batch", "cols": ["batch_id"], "comment": "按批次查问题"},
            {"name": "idx_issue_rule", "cols": ["rule_code"], "comment": "按规则统计触发次数"},
        ],
        "fks": [{"col": "batch_id", "ref_table": "import_batch", "ref_col": "id"}],
    },
    {
        "name": "role",
        "comment": "角色（访客/注册用户/管理员）",
        "columns": [
            pk("id"),
            C("code", "VARCHAR(32) NOT NULL", "TEXT NOT NULL", "varchar(32)",
              "角色编码：visitor/user/admin", ),
            C("name", "VARCHAR(32) NOT NULL", "TEXT NOT NULL", "varchar(32)", "角色名称"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_role_code", "cols": ["code"], "comment": "角色编码唯一"}],
        "indexes": [],
        "fks": [],
    },
    {
        "name": "app_user",
        "comment": "用户（密码用 PBKDF2-HMAC-SHA256，非明文、非 MD5）",
        "columns": [
            pk("id", big=True),
            C("username", "VARCHAR(64) NOT NULL", "TEXT NOT NULL", "varchar(64)", "登录名"),
            C("password_hash", "VARCHAR(255) NOT NULL", "TEXT NOT NULL", "varchar(255)",
              "格式 salt$pbkdf2_sha256$迭代数$摘要"),
            fk_col("role_id", "角色 id"),
            C("status", "TINYINT UNSIGNED NOT NULL DEFAULT 1", "INTEGER NOT NULL DEFAULT 1",
              "tinyint", "1=启用 0=禁用", check="status IN (0,1)"),
            C("fail_count", "TINYINT UNSIGNED NOT NULL DEFAULT 0",
              "INTEGER NOT NULL DEFAULT 0", "tinyint", "连续登录失败次数（5 次锁定）"),
            C("lock_until", "DATETIME(3) NULL", "TEXT", "datetime", "锁定到期时间", null=True),
            C("last_login_at", "DATETIME(3) NULL", "TEXT", "datetime", "最后登录时间",
              null=True),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_user_username", "cols": ["username"], "comment": "登录名唯一"}],
        "indexes": [{"name": "idx_user_role", "cols": ["role_id"], "comment": "按角色查用户"}],
        "fks": [{"col": "role_id", "ref_table": "role", "ref_col": "id"}],
    },
    {
        "name": "favorite",
        "comment": "收藏（用户 × 房源 M:N 拆解，联合唯一保证幂等）",
        "columns": [
            pk("id", big=True),
            fk_col("user_id", "用户 id"),
            fk_col("house_id", "房源 id"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [{"name": "uk_favorite_user_house", "cols": ["user_id", "house_id"],
                     "comment": "重复收藏返回成功但 already=true"}],
        "indexes": [{"name": "idx_favorite_house", "cols": ["house_id"],
                     "comment": "统计房源被收藏数"}],
        "fks": [
            {"col": "user_id", "ref_table": "app_user", "ref_col": "id"},
            {"col": "house_id", "ref_table": "house", "ref_col": "id"},
        ],
    },
    {
        "name": "operation_log",
        "comment": "操作审计日志",
        "columns": [
            pk("id", big=True),
            C("user_id", "BIGINT UNSIGNED NULL", "INTEGER", "bigint", "操作人；匿名操作留空",
              null=True),
            C("action", "VARCHAR(64) NOT NULL", "TEXT NOT NULL", "varchar(64)",
              "动作：login/import/favorite/delete…"),
            C("target_type", "VARCHAR(32) NULL", "TEXT", "varchar(32)",
              "对象类型：house/batch/user", null=True),
            C("target_id", "VARCHAR(64) NULL", "TEXT", "varchar(64)", "对象 id", null=True),
            C("ip", "VARCHAR(45) NULL", "TEXT", "varchar(45)", "客户端 IP（兼容 IPv6）",
              null=True),
            C("result", "VARCHAR(16) NOT NULL DEFAULT 'ok'", "TEXT NOT NULL DEFAULT 'ok'",
              "varchar(16)", "ok / fail"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [],
        "indexes": [
            {"name": "idx_oplog_user_time", "cols": ["user_id", "created_at"],
             "comment": "按用户查操作历史"},
        ],
        "fks": [],
    },
    {
        "name": "valuation_record",
        "comment": "估价留痕（相似房源加权均价法的每次调用）",
        "columns": [
            pk("id", big=True),
            C("user_id", "BIGINT UNSIGNED NULL", "INTEGER", "bigint", "调用人", null=True),
            C("input_json", "JSON NOT NULL", "TEXT NOT NULL", "json",
              "入参：区/街道/面积/室/厅/房龄/装修/楼层/近地铁"),
            C("est_unit_price", "DECIMAL(10,2) NOT NULL", "NUMERIC NOT NULL",
              "decimal(10,2)", "估算单价 元/㎡"),
            C("est_total_price", "DECIMAL(10,2) NOT NULL", "NUMERIC NOT NULL",
              "decimal(10,2)", "估算总价 万元"),
            C("price_low", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "区间下限（±8%）", null=True),
            C("price_high", "DECIMAL(10,2) NULL", "NUMERIC", "decimal(10,2)",
              "区间上限（±8%）", null=True),
            C("sample_count", "INT UNSIGNED NOT NULL", "INTEGER NOT NULL", "int",
              "参与加权的相似房源数"),
            C("fallback_level", "ENUM('community','street','district','none') "
                                "NOT NULL DEFAULT 'none'",
              "TEXT NOT NULL DEFAULT 'none'",
              "enum('community','street','district','none')",
              "降级层级：同小区→同街道→同区→无样本",
              check="fallback_level IN ('community','street','district','none')"),
            C("confidence", "ENUM('high','medium','low') NOT NULL DEFAULT 'low'",
              "TEXT NOT NULL DEFAULT 'low'", "enum('high','medium','low')",
              "置信度；样本<5 强制 low",
              check="confidence IN ('high','medium','low')"),
            C("model_version", "VARCHAR(32) NOT NULL DEFAULT 'wa-1.0'",
              "TEXT NOT NULL DEFAULT 'wa-1.0'", "varchar(32)",
              "算法版本：相似房源加权均价"),
            *timestamps(),
        ],
        "pk": ["id"],
        "uniques": [],
        "indexes": [{"name": "idx_valuation_time", "cols": ["created_at"],
                     "comment": "估价记录按时间倒序"}],
        "fks": [],
    },
]

# ---------------------------------------------------------------------------
# 明确不建的表（写进文档，避免"漏了"和"过度拆分"两种质疑）
# ---------------------------------------------------------------------------
NOT_BUILT = [
    {
        "table": "house_tag",
        "reason": "房源标签只有“近地铁/不近地铁”两值，且与 one-hot 近地铁列差异 0 条，"
                  "零信息增量；已并入 house.near_subway，避免过度拆分。",
    },
    {
        "table": "area_bucket / total_bucket（区间字典表）",
        "reason": "面积区间/总价区间为派生字段，且原始列缺 5 行（正是最大的 5 条记录）；"
                  "改由前端/接口按需分桶，口径写死在 rules.toml [buckets]。",
    },
    {
        "table": "price_snapshot（价格快照）",
        "reason": "数据是 2024-08 单一快照，无时间维度，无法建立价格时序表。",
    },
]

# ---------------------------------------------------------------------------
# 53 列逐列映射（Excel 原列 → 目标字段 → 转换规则 → 保留/丢弃 → 理由）
# ---------------------------------------------------------------------------
_DISTRICTS = ["东城", "丰台", "亦庄开发区", "大兴", "密云", "平谷", "延庆", "怀柔",
              "房山", "昌平", "朝阳", "海淀", "石景山", "西城", "通州", "门头沟", "顺义"]


def _onehot_rows(columns, group, target, rule, reason):
    rows = []
    for col in columns:
        rows.append({
            "excel_column": col,
            "target": target,
            "rule": rule,
            "keep": False,
            "reason": reason,
            "group": group,
        })
    return rows


COLUMN_MAPPING = [
    # A. 原始业务字段（13）
    {"excel_column": "小区名", "target": "community.name", "rule": "R1 strip → R10 按 (district, 名称) 建维表",
     "keep": True, "reason": "2890/2890 带尾随空格（D1）；1865 个组合", "group": "原始业务字段"},
    {"excel_column": "所在街道或镇", "target": "street.name", "rule": "R1 strip → R10 按 (district, 名称) 建维表；R11 标 is_pseudo",
     "keep": True, "reason": "街道名去重 237，组合 264；含 12 个伪街道", "group": "原始业务字段"},
    {"excel_column": "所在区", "target": "district.name", "rule": "R1 strip → R10 建维表",
     "keep": True, "reason": "17 个区", "group": "原始业务字段"},
    {"excel_column": "户型", "target": "house.room + house.hall", "rule": "R6 正则 ^(\\d+)室(\\d+)厅$ 拆两列",
     "keep": True, "reason": "25 种；与“室”“厅”列交叉校验 0 条不一致", "group": "原始业务字段"},
    {"excel_column": "面积（平方米）", "target": "house.area", "rule": "R7 转 DECIMAL(8,2)，范围 (0,1000]",
     "keep": True, "reason": "金额/面积禁用 FLOAT；16.07–747.23", "group": "原始业务字段"},
    {"excel_column": "朝向", "target": "house.orientation_text + house_orientation.direction",
     "rule": "R4 按空白拆分、去重、按固定顺序标准化 → M:N 拆表",
     "keep": True, "reason": "1786 条多值，61 种组合；不拆无法做“朝南房源均价”", "group": "原始业务字段"},
    {"excel_column": "装修", "target": "house.decoration", "rule": "R1 strip → ENUM(毛坯/简装/精装/其他)",
     "keep": True, "reason": "4 类，分布 1313/970/549/58", "group": "原始业务字段"},
    {"excel_column": "楼层", "target": "house.floor_level + house.floor_total + house.floor_raw",
     "rule": "R5 五种形态正则解析；失败置 floor_level='未知'",
     "keep": True, "reason": "364 条（12.6%）只有纯数字，缺层级（D3）", "group": "原始业务字段"},
    {"excel_column": "房龄", "target": "house.house_age", "rule": "R7 转 TINYINT，范围 0–100",
     "keep": True, "reason": "以 2024 为基准年；3–50", "group": "原始业务字段"},
    {"excel_column": "结构", "target": "house.structure", "rule": "R1 strip → ENUM(板楼/塔楼/板塔结合/独栋别墅/平房)",
     "keep": True, "reason": "“独栋别墅 ”带尾随空格，R1 修正 1 条", "group": "原始业务字段"},
    {"excel_column": "总价（万元）", "target": "house.total_price", "rule": "R7 转 DECIMAL(10,2)，范围 >0",
     "keep": True, "reason": "36–8000 万元；禁用 FLOAT", "group": "原始业务字段"},
    {"excel_column": "单价（元/平方米）", "target": "house.unit_price",
     "rule": "R7 转 DECIMAL(10,2)；与 总价×10000÷面积 校验，容差 1 元",
     "keep": True, "reason": "D6 自洽，超容差 0 条；保留源值而非生成列", "group": "原始业务字段"},
    {"excel_column": "房源标签", "target": "house.near_subway", "rule": "R12 归并为 0/1；与 one-hot 交叉校验",
     "keep": True, "reason": "仅两值，与近地铁 one-hot 差异 0 条 → 不建 house_tag 表", "group": "原始业务字段"},
    # B. 派生字段（4）
    {"excel_column": "室", "target": "house.room", "rule": "R6 与户型正则交叉校验后采用",
     "keep": True, "reason": "0 条不一致；室 1–12", "group": "课程预处理派生字段"},
    {"excel_column": "厅", "target": "house.hall", "rule": "R6 与户型正则交叉校验后采用",
     "keep": True, "reason": "0 条不一致；厅 0–4，厅=0 有 101 条（开间，非缺失）", "group": "课程预处理派生字段"},
    {"excel_column": "面积区间", "target": "（不入库）", "rule": "R9 复算校验口径（left_open），命中率 100%",
     "keep": False, "reason": "派生字段，可随时由 area 重算；原列缺 3 行（正是最大的 3 条）", "group": "课程预处理派生字段"},
    {"excel_column": "总价区间", "target": "（不入库）", "rule": "R9 复算校验口径（left_open），命中率 100%",
     "keep": False, "reason": "派生字段，可随时由 total_price 重算；原列缺 2 行", "group": "课程预处理派生字段"},
]
COLUMN_MAPPING += _onehot_rows(
    _DISTRICTS, "one-hot", "（丢弃）", "R3 丢弃，回归 district.name",
    "17 列 one-hot 与“所在区”原文完全等价，保留会迫使任何分组聚合写 17 个分支",
)
COLUMN_MAPPING += _onehot_rows(
    ["其他", "毛坯", "简装", "精装"], "one-hot", "（丢弃）", "R2/R3 丢弃，回归 house.decoration",
    "“其他”为冗余基线列（549 行，四列和恒为 1，D2），与另三列线性相关，整列丢弃",
)
COLUMN_MAPPING += _onehot_rows(
    ["塔楼", "平房", "板塔结合", "板楼", "独栋别墅"], "one-hot", "（丢弃）",
    "R3 丢弃，回归 house.structure", "5 列 one-hot 与“结构”原文等价",
)
COLUMN_MAPPING += _onehot_rows(
    ["不近地铁", "近地铁"], "one-hot", "（丢弃）", "R3 丢弃，回归 house.near_subway",
    "2 列 one-hot 与“房源标签”完全等价（差异 0 条）",
)
COLUMN_MAPPING += _onehot_rows(
    ["东", "南", "西", "北", "东北", "东南", "西南", "西北"], "one-hot", "（丢弃）",
    "R3 丢弃，回归“朝向”原文后由 R4 拆 M:N",
    "8 列 one-hot 无法表达“南 北”这类组合语义，且无法按单方向反查",
)

# ---------------------------------------------------------------------------
# E-R 关系（用于 Mermaid 与 DBML）
# ---------------------------------------------------------------------------
RELATIONS = [
    ("district", "id", "street", "district_id", "||--o{", "下辖", "1:N"),
    ("district", "id", "community", "district_id", "||--o{", "下辖", "1:N"),
    ("street", "id", "community", "street_id", "||--o{", "包含", "1:N"),
    ("district", "id", "house", "district_id", "||--o{", "冗余关联", "1:N"),
    ("street", "id", "house", "street_id", "||--o{", "冗余关联", "1:N"),
    ("community", "id", "house", "community_id", "||--o{", "在售", "1:N"),
    ("import_batch", "id", "house", "batch_id", "||--o{", "导入", "1:N"),
    ("import_batch", "id", "data_quality_issue", "batch_id", "||--o{", "留痕", "1:N"),
    ("house", "id", "house_orientation", "house_id", "||--o{", "多朝向", "1:N"),
    ("role", "id", "app_user", "role_id", "||--o{", "授予", "1:N"),
    ("app_user", "id", "favorite", "user_id", "||--o{", "收藏", "1:N"),
    ("house", "id", "favorite", "house_id", "||--o{", "被收藏", "1:N"),
    ("app_user", "id", "operation_log", "user_id", "||--o{", "产生", "1:N"),
    ("app_user", "id", "valuation_record", "user_id", "||--o{", "调用", "1:N"),
]

TABLE_COMMENTS_CN = {
    "district": "行政区",
    "street": "街道/镇",
    "community": "小区",
    "house": "房源",
    "house_orientation": "房源-朝向",
    "import_batch": "导入批次",
    "data_quality_issue": "数据质量问题",
    "role": "角色",
    "app_user": "用户",
    "favorite": "收藏",
    "operation_log": "操作日志",
    "valuation_record": "估价记录",
}
