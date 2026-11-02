-- ===========================================================================
-- 北京二手房行情洞察系统 · SQLite DDL（本机实跑用）
-- 本文件由 db/gen_schema.py 生成，请勿手工修改。
--
-- 与 MySQL 版的方言差异：
--   ENUM(...)      → TEXT + CHECK 约束
--   DECIMAL(p,s)   → NUMERIC（SQLite 无原生定点类型，精度由应用层与 CHECK 保证）
--   DATETIME       → TEXT (ISO-8601)
--   AUTO_INCREMENT → INTEGER PRIMARY KEY AUTOINCREMENT
--   表/字段 COMMENT → 由 docs/05-数据字典.xlsx 承载
-- ===========================================================================

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS valuation_record;
DROP TABLE IF EXISTS operation_log;
DROP TABLE IF EXISTS favorite;
DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS role;
DROP TABLE IF EXISTS data_quality_issue;
DROP TABLE IF EXISTS house_orientation;
DROP TABLE IF EXISTS house;
DROP TABLE IF EXISTS import_batch;
DROP TABLE IF EXISTS community;
DROP TABLE IF EXISTS street;
DROP TABLE IF EXISTS district;

-- 行政区（17 行，含亦庄开发区）
CREATE TABLE district (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  house_count INTEGER NOT NULL DEFAULT 0,
  avg_unit_price NUMERIC,
  median_unit_price NUMERIC,
  median_total_price NUMERIC,
  avg_area NUMERIC,
  avg_age NUMERIC,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (name)
);

-- 街道/镇（264 行；街道名去重仅 237，故必须与区联合唯一）
CREATE TABLE street (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  district_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  is_pseudo INTEGER NOT NULL DEFAULT 0,
  house_count INTEGER NOT NULL DEFAULT 0,
  avg_unit_price NUMERIC,
  median_total_price NUMERIC,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CONSTRAINT chk_street_is_pseudo CHECK (is_pseudo IN (0,1)),
  UNIQUE (district_id, name),
  FOREIGN KEY (district_id) REFERENCES district (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_street_district ON street (district_id);  -- 按区展开街道列表（检索页联动）

-- 小区（1865 行；小区名去重 1864，绿地中央广场跨昌平/通州）
CREATE TABLE community (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  district_id INTEGER NOT NULL,
  street_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  house_count INTEGER NOT NULL DEFAULT 0,
  avg_unit_price NUMERIC NULL,
  median_total_price NUMERIC NULL,
  avg_area NUMERIC NULL,
  avg_age NUMERIC NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (district_id, name),
  FOREIGN KEY (district_id) REFERENCES district (id) ON DELETE RESTRICT ON UPDATE CASCADE,
  FOREIGN KEY (street_id) REFERENCES street (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_community_street ON community (street_id);  -- 同街道小区排行（小区画像页）
CREATE INDEX idx_community_name ON community (name);  -- 小区名前缀搜索；LIKE 'kw%' 可用索引，LIKE '%kw%' 不可

-- 导入批次（每次 Excel 导入一行，支撑质量报告与审计）
CREATE TABLE import_batch (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_name TEXT NOT NULL,
  file_md5 TEXT NOT NULL,
  total_rows INTEGER NOT NULL,
  loaded_rows INTEGER NOT NULL DEFAULT 0,
  rejected_rows INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  operator_id INTEGER,
  duration_ms INTEGER,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CONSTRAINT chk_import_batch_status CHECK (status IN ('pending','running','success','partial','failed'))
);
CREATE INDEX idx_batch_created ON import_batch (created_at);  -- 批次列表按时间倒序

-- 房源主表（2890 行；district/street/community 三列为反范式冗余）
CREATE TABLE house (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  district_id INTEGER NOT NULL,
  street_id INTEGER NOT NULL,
  community_id INTEGER NOT NULL,
  batch_id INTEGER,
  source_row_no INTEGER NOT NULL,
  room INTEGER NOT NULL,
  hall INTEGER NOT NULL DEFAULT 0,
  area NUMERIC NOT NULL,
  total_price NUMERIC NOT NULL,
  unit_price NUMERIC NOT NULL,
  floor_level TEXT NOT NULL DEFAULT '未知',
  floor_total INTEGER,
  floor_raw TEXT,
  orientation_text TEXT,
  decoration TEXT,
  structure TEXT,
  house_age INTEGER,
  near_subway INTEGER NOT NULL DEFAULT 0,
  is_outlier INTEGER NOT NULL DEFAULT 0,
  abnormal_layout INTEGER NOT NULL DEFAULT 0,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CONSTRAINT chk_house_room CHECK (room BETWEEN 1 AND 20),
  CONSTRAINT chk_house_hall CHECK (hall BETWEEN 0 AND 10),
  CONSTRAINT chk_house_area CHECK (area > 0 AND area <= 1000),
  CONSTRAINT chk_house_total_price CHECK (total_price > 0),
  CONSTRAINT chk_house_floor_level CHECK (floor_level IN ('低', '中', '高', '顶层', '底层', '地下', '上叠', '未知')),
  CONSTRAINT chk_house_decoration CHECK (decoration IN ('毛坯', '简装', '精装', '其他')),
  CONSTRAINT chk_house_structure CHECK (structure IN ('板楼', '塔楼', '板塔结合', '独栋别墅', '平房')),
  CONSTRAINT chk_house_near_subway CHECK (near_subway IN (0,1)),
  CONSTRAINT chk_house_is_outlier CHECK (is_outlier IN (0,1)),
  CONSTRAINT chk_house_abnormal_layout CHECK (abnormal_layout IN (0,1)),
  CONSTRAINT chk_house_is_deleted CHECK (is_deleted IN (0,1)),
  UNIQUE (batch_id, source_row_no),
  FOREIGN KEY (district_id) REFERENCES district (id) ON DELETE RESTRICT ON UPDATE CASCADE,
  FOREIGN KEY (street_id) REFERENCES street (id) ON DELETE RESTRICT ON UPDATE CASCADE,
  FOREIGN KEY (community_id) REFERENCES community (id) ON DELETE RESTRICT ON UPDATE CASCADE,
  FOREIGN KEY (batch_id) REFERENCES import_batch (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_house_district_unit ON house (district_id, unit_price);  -- 核心查询①按区筛选并按单价排序：最左前缀 district_id 命中 WHERE，第二列直接满足 ORDER BY，避免 filesort
CREATE INDEX idx_house_district_street_unit ON house (district_id, street_id, unit_price);  -- 核心查询②区+街道筛选并排序：三级最左前缀
CREATE INDEX idx_house_community_unit ON house (community_id, unit_price);  -- 核心查询③同小区相似房源召回（估价降级链第一级）
CREATE INDEX idx_house_price_filter ON house (total_price, area);  -- 总价/面积区间筛选（双滑块）
CREATE INDEX idx_house_age ON house (house_age);  -- 房龄段统计（看板分组）
CREATE INDEX idx_house_decoration ON house (decoration);  -- 装修溢价聚合
CREATE INDEX idx_house_is_outlier ON house (is_outlier);  -- 分析层默认排除/包含极值的开关

-- 房源-朝向关联表（4806 行）：朝向是“南 北”式多值，必须拆 M:N
CREATE TABLE house_orientation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  house_id INTEGER NOT NULL,
  direction TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CONSTRAINT chk_house_orientation_direction CHECK (direction IN ('东', '南', '西', '北', '东北', '东南', '西南', '西北')),
  UNIQUE (house_id, direction),
  FOREIGN KEY (house_id) REFERENCES house (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_orientation_direction ON house_orientation (direction, house_id);  -- “朝南房源均价”这类反查：以方向为最左前缀

-- 数据质量问题留痕（ETL 的问题台账直接落这张表）
CREATE TABLE data_quality_issue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER,
  rule_code TEXT NOT NULL,
  row_no INTEGER,
  field_name TEXT,
  issue_type TEXT NOT NULL,
  raw_value TEXT,
  fixed_value TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (batch_id) REFERENCES import_batch (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_issue_batch ON data_quality_issue (batch_id);  -- 按批次查问题
CREATE INDEX idx_issue_rule ON data_quality_issue (rule_code);  -- 按规则统计触发次数

-- 角色（访客/注册用户/管理员）
CREATE TABLE role (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (code)
);

-- 用户（密码用 PBKDF2-HMAC-SHA256，非明文、非 MD5）
CREATE TABLE app_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role_id INTEGER NOT NULL,
  status INTEGER NOT NULL DEFAULT 1,
  fail_count INTEGER NOT NULL DEFAULT 0,
  lock_until TEXT,
  last_login_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CONSTRAINT chk_app_user_status CHECK (status IN (0,1)),
  UNIQUE (username),
  FOREIGN KEY (role_id) REFERENCES role (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_user_role ON app_user (role_id);  -- 按角色查用户

-- 收藏（用户 × 房源 M:N 拆解，联合唯一保证幂等）
CREATE TABLE favorite (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  house_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (user_id, house_id),
  FOREIGN KEY (user_id) REFERENCES app_user (id) ON DELETE RESTRICT ON UPDATE CASCADE,
  FOREIGN KEY (house_id) REFERENCES house (id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX idx_favorite_house ON favorite (house_id);  -- 统计房源被收藏数

-- 操作审计日志
CREATE TABLE operation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  ip TEXT,
  result TEXT NOT NULL DEFAULT 'ok',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_oplog_user_time ON operation_log (user_id, created_at);  -- 按用户查操作历史

-- 估价留痕（相似房源加权均价法的每次调用）
CREATE TABLE valuation_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  input_json TEXT NOT NULL,
  est_unit_price NUMERIC NOT NULL,
  est_total_price NUMERIC NOT NULL,
  price_low NUMERIC,
  price_high NUMERIC,
  sample_count INTEGER NOT NULL,
  fallback_level TEXT NOT NULL DEFAULT 'none',
  confidence TEXT NOT NULL DEFAULT 'low',
  model_version TEXT NOT NULL DEFAULT 'wa-1.0',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CONSTRAINT chk_valuation_record_fallback_level CHECK (fallback_level IN ('community','street','district','none')),
  CONSTRAINT chk_valuation_record_confidence CHECK (confidence IN ('high','medium','low'))
);
CREATE INDEX idx_valuation_time ON valuation_record (created_at);  -- 估价记录按时间倒序

INSERT INTO role (code, name) VALUES
  ('visitor', '访客'),
  ('user', '注册用户'),
  ('admin', '管理员');
