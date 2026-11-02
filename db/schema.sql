-- ===========================================================================
-- 北京二手房行情洞察系统 · MySQL 8.0 DDL
-- 本文件由 db/gen_schema.py 从 db/schema_model.py 生成，请勿手工修改。
--
-- 设计要点：
--   1. 金额 DECIMAL(10,2)、面积 DECIMAL(8,2)，全库禁用 FLOAT
--   2. 朝向为多值字段，拆 house_orientation 实现 M:N
--   3. house 冗余 district_id/street_id/community_id，换查询性能
--   4. 主键/外键/时间戳/中文注释齐全；不建触发器与存储过程
-- ===========================================================================

DROP DATABASE IF EXISTS `bj_house_insight`;
CREATE DATABASE `bj_house_insight` DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci;
USE `bj_house_insight`;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `valuation_record`;
DROP TABLE IF EXISTS `operation_log`;
DROP TABLE IF EXISTS `favorite`;
DROP TABLE IF EXISTS `app_user`;
DROP TABLE IF EXISTS `role`;
DROP TABLE IF EXISTS `data_quality_issue`;
DROP TABLE IF EXISTS `house_orientation`;
DROP TABLE IF EXISTS `house`;
DROP TABLE IF EXISTS `import_batch`;
DROP TABLE IF EXISTS `community`;
DROP TABLE IF EXISTS `street`;
DROP TABLE IF EXISTS `district`;

-- 行政区（17 行，含亦庄开发区）
CREATE TABLE `district` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `name` VARCHAR(32) NOT NULL COMMENT '区名，唯一；取原始“所在区”原文',
  `house_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '在售套数（聚合快照，ETL 批次刷新）',
  `avg_unit_price` DECIMAL(10,2) NULL COMMENT '区均价 元/㎡（算术均值）',
  `median_unit_price` DECIMAL(10,2) NULL COMMENT '区中位单价 元/㎡',
  `median_total_price` DECIMAL(10,2) NULL COMMENT '区中位总价 万元',
  `avg_area` DECIMAL(8,2) NULL COMMENT '区平均面积 ㎡',
  `avg_age` DECIMAL(5,2) NULL COMMENT '区平均房龄 年',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_district_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='行政区（17 行，含亦庄开发区）';

-- 唯一键 uk_district_name：区名唯一

-- 街道/镇（264 行；街道名去重仅 237，故必须与区联合唯一）
CREATE TABLE `street` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `district_id` BIGINT UNSIGNED NOT NULL COMMENT '所属区 id',
  `name` VARCHAR(64) NOT NULL COMMENT '街道名，取原始“所在街道或镇”原文',
  `is_pseudo` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '伪街道标记：1=“XX其他”聚合桶，共 16 个组合/107 行',
  `house_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '在售套数（聚合快照）',
  `avg_unit_price` DECIMAL(10,2) NULL COMMENT '街道均价 元/㎡（聚合快照）',
  `median_total_price` DECIMAL(10,2) NULL COMMENT '街道中位总价 万元（聚合快照）',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  CONSTRAINT `chk_street_is_pseudo` CHECK (is_pseudo IN (0,1)),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_street_district_name` (`district_id`, `name`),
  KEY `idx_street_district` (`district_id`),
  CONSTRAINT `fk_street_district_id` FOREIGN KEY (`district_id`) REFERENCES `district` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='街道/镇（264 行；街道名去重仅 237，故必须与区联合唯一）';

-- 索引 idx_street_district：按区展开街道列表（检索页联动）
-- 唯一键 uk_street_district_name：联合唯一：同名街道可属不同区

-- 小区（1865 行；小区名去重 1864，绿地中央广场跨昌平/通州）
CREATE TABLE `community` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `district_id` BIGINT UNSIGNED NOT NULL COMMENT '所属区 id',
  `street_id` BIGINT UNSIGNED NOT NULL COMMENT '所属街道 id（同小区多街道时取众数）',
  `name` VARCHAR(128) NOT NULL COMMENT '小区名，已去除尾随空格',
  `house_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '在售套数（聚合快照，中位 1、最大 12）',
  `avg_unit_price` DECIMAL(10,2) NULL COMMENT '小区均价 元/㎡（聚合快照）',
  `median_total_price` DECIMAL(10,2) NULL COMMENT '小区中位总价 万元（聚合快照）',
  `avg_area` DECIMAL(8,2) NULL COMMENT '小区平均面积 ㎡',
  `avg_age` DECIMAL(5,2) NULL COMMENT '小区平均房龄 年',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_community_district_name` (`district_id`, `name`),
  KEY `idx_community_street` (`street_id`),
  KEY `idx_community_name` (`name`),
  CONSTRAINT `fk_community_district_id` FOREIGN KEY (`district_id`) REFERENCES `district` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_community_street_id` FOREIGN KEY (`street_id`) REFERENCES `street` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='小区（1865 行；小区名去重 1864，绿地中央广场跨昌平/通州）';

-- 索引 idx_community_street：同街道小区排行（小区画像页）
-- 索引 idx_community_name：小区名前缀搜索；LIKE 'kw%' 可用索引，LIKE '%kw%' 不可
-- 唯一键 uk_community_district_name：联合唯一：同名小区可属不同区（1 例）

-- 导入批次（每次 Excel 导入一行，支撑质量报告与审计）
CREATE TABLE `import_batch` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `file_name` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `file_md5` CHAR(32) NOT NULL COMMENT '文件 MD5，用于识别重复导入',
  `total_rows` INT UNSIGNED NOT NULL COMMENT '原始行数',
  `loaded_rows` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '入库行数',
  `rejected_rows` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '拒收行数',
  `status` ENUM('pending','running','success','partial','failed') NOT NULL DEFAULT 'pending' COMMENT '批次状态',
  `operator_id` BIGINT UNSIGNED NULL COMMENT '操作人（管理员）id',
  `duration_ms` INT UNSIGNED NULL COMMENT '耗时毫秒',
  `note` VARCHAR(500) NULL COMMENT '备注/失败原因',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_batch_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='导入批次（每次 Excel 导入一行，支撑质量报告与审计）';

-- 索引 idx_batch_created：批次列表按时间倒序

-- 房源主表（2890 行；district/street/community 三列为反范式冗余）
CREATE TABLE `house` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `district_id` BIGINT UNSIGNED NOT NULL COMMENT '区 id（冗余，换查询性能）',
  `street_id` BIGINT UNSIGNED NOT NULL COMMENT '街道 id（冗余）',
  `community_id` BIGINT UNSIGNED NOT NULL COMMENT '小区 id（冗余）',
  `batch_id` BIGINT UNSIGNED NULL COMMENT '导入批次 id；seed 数据为空',
  `source_row_no` INT UNSIGNED NOT NULL COMMENT '源文件数据行号（1 基，不含表头），用于全链路回溯',
  `room` TINYINT UNSIGNED NOT NULL COMMENT '室（1–12）',
  `hall` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '厅（0–4）；厅=0 为开间，合法，共 101 条',
  `area` DECIMAL(8,2) NOT NULL COMMENT '建筑面积 ㎡（16.07–747.23）',
  `total_price` DECIMAL(10,2) NOT NULL COMMENT '挂牌总价 万元（36–8000）',
  `unit_price` DECIMAL(10,2) NOT NULL COMMENT '挂牌单价 元/㎡（12742–179843）；与总价/面积误差 ≤1 元',
  `floor_level` ENUM('低', '中', '高', '顶层', '底层', '地下', '上叠', '未知') NOT NULL DEFAULT '未知' COMMENT '解析后楼层层级；缺层级（纯数字）记为“未知”',
  `floor_total` TINYINT UNSIGNED NULL COMMENT '总层数；解析失败为 NULL',
  `floor_raw` VARCHAR(32) NULL COMMENT '楼层原文，保留以便回溯',
  `orientation_text` VARCHAR(32) NULL COMMENT '朝向标准化原文（固定顺序，空格分隔）；明细见 house_orientation',
  `decoration` ENUM('毛坯', '简装', '精装', '其他') NULL COMMENT '装修：精装1313/简装970/其他549/毛坯58',
  `structure` ENUM('板楼', '塔楼', '板塔结合', '独栋别墅', '平房') NULL COMMENT '建筑结构：板楼1806/塔楼629/板塔结合453/独栋1/平房1',
  `house_age` TINYINT UNSIGNED NULL COMMENT '房龄 年（3–50，以 2024 为基准年）',
  `near_subway` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否近地铁（1=近，1308 条）；由“房源标签”归并而来',
  `is_outlier` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '极值标记（P0.5–P99.5 三指标并集，72 行）；只标记不删除',
  `abnormal_layout` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '非常规户型标记（1室2厅，12 条）；保留不清洗',
  `is_deleted` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '软删除标记',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  CONSTRAINT `chk_house_room` CHECK (room BETWEEN 1 AND 20),
  CONSTRAINT `chk_house_hall` CHECK (hall BETWEEN 0 AND 10),
  CONSTRAINT `chk_house_area` CHECK (area > 0 AND area <= 1000),
  CONSTRAINT `chk_house_total_price` CHECK (total_price > 0),
  CONSTRAINT `chk_house_near_subway` CHECK (near_subway IN (0,1)),
  CONSTRAINT `chk_house_is_outlier` CHECK (is_outlier IN (0,1)),
  CONSTRAINT `chk_house_abnormal_layout` CHECK (abnormal_layout IN (0,1)),
  CONSTRAINT `chk_house_is_deleted` CHECK (is_deleted IN (0,1)),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_house_batch_row` (`batch_id`, `source_row_no`),
  KEY `idx_house_district_unit` (`district_id`, `unit_price`),
  KEY `idx_house_district_street_unit` (`district_id`, `street_id`, `unit_price`),
  KEY `idx_house_community_unit` (`community_id`, `unit_price`),
  KEY `idx_house_price_filter` (`total_price`, `area`),
  KEY `idx_house_age` (`house_age`),
  KEY `idx_house_decoration` (`decoration`),
  KEY `idx_house_is_outlier` (`is_outlier`),
  CONSTRAINT `fk_house_district_id` FOREIGN KEY (`district_id`) REFERENCES `district` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_house_street_id` FOREIGN KEY (`street_id`) REFERENCES `street` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_house_community_id` FOREIGN KEY (`community_id`) REFERENCES `community` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_house_batch_id` FOREIGN KEY (`batch_id`) REFERENCES `import_batch` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='房源主表（2890 行；district/street/community 三列为反范式冗余）';

-- 索引 idx_house_district_unit：核心查询①按区筛选并按单价排序：最左前缀 district_id 命中 WHERE，第二列直接满足 ORDER BY，避免 filesort
-- 索引 idx_house_district_street_unit：核心查询②区+街道筛选并排序：三级最左前缀
-- 索引 idx_house_community_unit：核心查询③同小区相似房源召回（估价降级链第一级）
-- 索引 idx_house_price_filter：总价/面积区间筛选（双滑块）
-- 索引 idx_house_age：房龄段统计（看板分组）
-- 索引 idx_house_decoration：装修溢价聚合
-- 索引 idx_house_is_outlier：分析层默认排除/包含极值的开关
-- 唯一键 uk_house_batch_row：同批次内源行号唯一，保证可追溯且可重复导入不重复

-- 房源-朝向关联表（4806 行）：朝向是“南 北”式多值，必须拆 M:N
CREATE TABLE `house_orientation` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `house_id` BIGINT UNSIGNED NOT NULL COMMENT '房源 id',
  `direction` ENUM('东', '南', '西', '北', '东北', '东南', '西南', '西北') NOT NULL COMMENT '标准方向；南1976/北1624/东368/西363/西南160/东南159/西北84/东北72',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_orientation_house_direction` (`house_id`, `direction`),
  KEY `idx_orientation_direction` (`direction`, `house_id`),
  CONSTRAINT `fk_house_orientation_house_id` FOREIGN KEY (`house_id`) REFERENCES `house` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='房源-朝向关联表（4806 行）：朝向是“南 北”式多值，必须拆 M:N';

-- 索引 idx_orientation_direction：“朝南房源均价”这类反查：以方向为最左前缀
-- 唯一键 uk_orientation_house_direction：同一房源同一方向只出现一次

-- 数据质量问题留痕（ETL 的问题台账直接落这张表）
CREATE TABLE `data_quality_issue` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `batch_id` BIGINT UNSIGNED NULL COMMENT '所属批次 id',
  `rule_code` VARCHAR(8) NOT NULL COMMENT '规则编号 R1–R12',
  `row_no` INT UNSIGNED NULL COMMENT '源文件行号',
  `field_name` VARCHAR(64) NULL COMMENT '涉及字段',
  `issue_type` VARCHAR(64) NOT NULL COMMENT '问题类型，如 trailing_space / outlier_high / bucket_mismatch',
  `raw_value` VARCHAR(255) NULL COMMENT '原值',
  `fixed_value` VARCHAR(255) NULL COMMENT '修正值',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_issue_batch` (`batch_id`),
  KEY `idx_issue_rule` (`rule_code`),
  CONSTRAINT `fk_data_quality_issue_batch_id` FOREIGN KEY (`batch_id`) REFERENCES `import_batch` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据质量问题留痕（ETL 的问题台账直接落这张表）';

-- 索引 idx_issue_batch：按批次查问题
-- 索引 idx_issue_rule：按规则统计触发次数

-- 角色（访客/注册用户/管理员）
CREATE TABLE `role` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `code` VARCHAR(32) NOT NULL COMMENT '角色编码：visitor/user/admin',
  `name` VARCHAR(32) NOT NULL COMMENT '角色名称',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_role_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色（访客/注册用户/管理员）';

-- 唯一键 uk_role_code：角色编码唯一

-- 用户（密码用 PBKDF2-HMAC-SHA256，非明文、非 MD5）
CREATE TABLE `app_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `username` VARCHAR(64) NOT NULL COMMENT '登录名',
  `password_hash` VARCHAR(255) NOT NULL COMMENT '格式 salt$pbkdf2_sha256$迭代数$摘要',
  `role_id` BIGINT UNSIGNED NOT NULL COMMENT '角色 id',
  `status` TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '1=启用 0=禁用',
  `fail_count` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '连续登录失败次数（5 次锁定）',
  `lock_until` DATETIME(3) NULL COMMENT '锁定到期时间',
  `last_login_at` DATETIME(3) NULL COMMENT '最后登录时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  CONSTRAINT `chk_app_user_status` CHECK (status IN (0,1)),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_username` (`username`),
  KEY `idx_user_role` (`role_id`),
  CONSTRAINT `fk_app_user_role_id` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户（密码用 PBKDF2-HMAC-SHA256，非明文、非 MD5）';

-- 索引 idx_user_role：按角色查用户
-- 唯一键 uk_user_username：登录名唯一

-- 收藏（用户 × 房源 M:N 拆解，联合唯一保证幂等）
CREATE TABLE `favorite` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户 id',
  `house_id` BIGINT UNSIGNED NOT NULL COMMENT '房源 id',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_favorite_user_house` (`user_id`, `house_id`),
  KEY `idx_favorite_house` (`house_id`),
  CONSTRAINT `fk_favorite_user_id` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_favorite_house_id` FOREIGN KEY (`house_id`) REFERENCES `house` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='收藏（用户 × 房源 M:N 拆解，联合唯一保证幂等）';

-- 索引 idx_favorite_house：统计房源被收藏数
-- 唯一键 uk_favorite_user_house：重复收藏返回成功但 already=true

-- 操作审计日志
CREATE TABLE `operation_log` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `user_id` BIGINT UNSIGNED NULL COMMENT '操作人；匿名操作留空',
  `action` VARCHAR(64) NOT NULL COMMENT '动作：login/import/favorite/delete…',
  `target_type` VARCHAR(32) NULL COMMENT '对象类型：house/batch/user',
  `target_id` VARCHAR(64) NULL COMMENT '对象 id',
  `ip` VARCHAR(45) NULL COMMENT '客户端 IP（兼容 IPv6）',
  `result` VARCHAR(16) NOT NULL DEFAULT 'ok' COMMENT 'ok / fail',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_oplog_user_time` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='操作审计日志';

-- 索引 idx_oplog_user_time：按用户查操作历史

-- 估价留痕（相似房源加权均价法的每次调用）
CREATE TABLE `valuation_record` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `user_id` BIGINT UNSIGNED NULL COMMENT '调用人',
  `input_json` JSON NOT NULL COMMENT '入参：区/街道/面积/室/厅/房龄/装修/楼层/近地铁',
  `est_unit_price` DECIMAL(10,2) NOT NULL COMMENT '估算单价 元/㎡',
  `est_total_price` DECIMAL(10,2) NOT NULL COMMENT '估算总价 万元',
  `price_low` DECIMAL(10,2) NULL COMMENT '区间下限（±8%）',
  `price_high` DECIMAL(10,2) NULL COMMENT '区间上限（±8%）',
  `sample_count` INT UNSIGNED NOT NULL COMMENT '参与加权的相似房源数',
  `fallback_level` ENUM('community','street','district','none') NOT NULL DEFAULT 'none' COMMENT '降级层级：同小区→同街道→同区→无样本',
  `confidence` ENUM('high','medium','low') NOT NULL DEFAULT 'low' COMMENT '置信度；样本<5 强制 low',
  `model_version` VARCHAR(32) NOT NULL DEFAULT 'wa-1.0' COMMENT '算法版本：相似房源加权均价',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_valuation_time` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='估价留痕（相似房源加权均价法的每次调用）';

-- 索引 idx_valuation_time：估价记录按时间倒序

SET FOREIGN_KEY_CHECKS = 1;

-- ===========================================================================
-- 种子数据：字典类基础行（评分/角色）
-- 业务数据（2890 条房源）由 db/load_sqlite.py 或导入接口写入，不写死在此。
-- ===========================================================================
INSERT INTO `role` (`code`, `name`) VALUES
  ('visitor', '访客'),
  ('user', '注册用户'),
  ('admin', '管理员');
