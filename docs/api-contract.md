# 接口契约（api-contract）

| 项 | 值 |
|---|---|
| 版本 | **v1（冻结）** |
| 基准路径 | `/api/v1`（前端一律走相对路径，开发期由 Vite 代理，生产期同源） |
| 字段来源 | `db/schema_model.py`（唯一事实源）——**本契约中出现的每个字段名都必须是其中真实存在的列或维度表列** |
| 用途 | 批 4（后端实现）与批 5（前端对接）以此为唯一依据；接口变更必须同步改本文件 |
| 手册步骤 | 步骤二 ↔ 步骤七 之间的接口契约（"契约先行"） |

> **冻结声明**：本文件一经确认，后端按此实现、前端按此对接。
> 任何字段增删都必须改本文件并同步 `frontend/src/api/*`，禁止口头改字段。

---

## 0. 通用约定

### 0.1 统一响应体

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "request_id": "3f9c1a2b"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | int | `0` 表示成功，非 0 见 §0.3 |
| `message` | string | 成功为 `ok`，失败为可直接展示的中文文案 |
| `data` | object/array/null | 业务数据；失败时为 `null` |
| `request_id` | string | 8 位请求标识，写入日志，便于排障 |

### 0.2 分页约定

| 参数 | 类型 | 默认 | 校验 |
|---|---|---|---|
| `page` | int | 1 | ≥1，越界返回空列表而非报错 |
| `page_size` | int | 20 | 1–100，超过返回 `1003` |

分页响应统一结构：

```json
{ "list": [], "total": 2890, "page": 1, "page_size": 20, "took_ms": 12 }
```

> `total` 必须与 `list` **共用同一个 where 构造器**（`build_filter()`），否则会出现"共 2890 条但翻到第 3 页就空"的经典 bug。

### 0.3 错误码表（12 条）

| code | 含义 | HTTP | 触发场景 |
|---|---|---|---|
| 0 | 成功 | 200 | — |
| 1001 | 参数校验失败 | 400 | 缺必填、类型错、范围越界（含估价面积不在 10–1000） |
| 1002 | 非法排序字段 | 400 | `sort` 不在白名单 |
| 1003 | 分页超限 | 400 | `page_size > 100` |
| 2001 | 未登录 | 401 | 缺少或格式错误的 `Authorization` |
| 2002 | 凭证过期 | 401 | JWT `exp` 已过 |
| 2003 | 权限不足 | 403 | 非 admin 访问 `/admin/*` |
| 2004 | 账号锁定 | 423 | 连续失败 5 次，15 分钟内 |
| 3001 | 资源不存在 | 404 | `house_id` / `community_id` / `batch_id` 查无 |
| 4001 | 文件类型不支持 | 400 | 导入非 `.xlsx` |
| 4002 | 文件过大 | 400 | 导入 > 20 MB |
| 5000 | 服务器内部错误 | 500 | 未捕获异常（**不返回堆栈**，只回 request_id） |

### 0.4 统计口径（**必须一字不差地实现**）

| 口径 | 定义 |
|---|---|
| 均价 `avg_unit_price` | **算术平均** `AVG(unit_price)`，保留 2 位 |
| 中位 `median_*` | **线性插值中位数**（偶数样本取中间两值平均） |
| 溢价率 `premium_pct` | `(组均价 − 基准组均价) / 基准组均价 × 100`，保留 2 位 |
| 分位 `percentile` | `0–100` 的百分位；`小于该值的行数 / 总数 × 100`，保留 1 位 |
| 极值 | `house.is_outlier = 1`；**默认不过滤**，涉及统计时须显式传参 |
| 伪街道 | `street.is_pseudo = 1`；**排行类接口默认排除** |
| 样本阈值 | 计算任何分组均价时,`n < 3` 的分组返回 `null` 并置 `insufficient_sample = true` |

### 0.5 鉴权

| 项 | 规定 |
|---|---|
| 传输 | 请求头 `Authorization: Bearer <token>` |
| 签名 | JWT HS256，载荷含 `user_id`、`role`、`exp` |
| 有效期 | 2 小时 |
| 白名单 | `/api/v1/health`、`/api/v1/auth/login`、`/api/v1/auth/register`、全部 GET 业务接口（访客可读） |
| 需要登录 | `POST /valuation`（可选，匿名可用但限流）、`/favorites/*`、`/admin/*` |

---

## 1. DTO 定义（字段名即契约，不得更改）

### 1.1 `HouseCard` —— 列表项

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `house_id` | int | `house.id` | 房源主键 |
| `district_id` | int | `house.district_id` | 区 id |
| `district_name` | string | `district.name` | 区名 |
| `street_id` | int | `house.street_id` | 街道 id |
| `street_name` | string | `street.name` | 街道名 |
| `community_id` | int | `house.community_id` | 小区 id |
| `community_name` | string | `community.name` | 小区名 |
| `room` | int | `house.room` | 室 |
| `hall` | int | `house.hall` | 厅（可为 0） |
| `area` | number | `house.area` | 面积 ㎡ |
| `total_price` | number | `house.total_price` | 总价 万元 |
| `unit_price` | number | `house.unit_price` | 单价 元/㎡ |
| `floor_level` | enum | `house.floor_level` | 低/中/高/顶层/底层/地下/上叠/未知 |
| `floor_total` | int\|null | `house.floor_total` | 总层数 |
| `house_age` | int | `house.house_age` | 房龄（2024 为基准年） |
| `decoration` | enum | `house.decoration` | 毛坯/简装/精装/其他 |
| `structure` | enum | `house.structure` | 板楼/塔楼/板塔结合/独栋别墅/平房 |
| `near_subway` | 0\|1 | `house.near_subway` | 是否近地铁 |
| `orientation_text` | string | `house.orientation_text` | 标准化朝向原文，如 `"南 北"` |
| `is_outlier` | 0\|1 | `house.is_outlier` | 极值标记（前端用浅色角标） |
| `abnormal_layout` | 0\|1 | `house.abnormal_layout` | 非常规户型标记 |

### 1.2 `HouseDetail` —— 详情 = `HouseCard` + 以下扩展

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `directions` | string[] | `house_orientation.direction` | 展开后的方向数组 |
| `floor_raw` | string | `house.floor_raw` | 楼层原文（便于解释"未知"） |
| `source_row_no` | int | `house.source_row_no` | 源文件行号（可追溯） |
| `community` | object | `community.*` | `{house_count, avg_unit_price, median_total_price, avg_area, avg_age}` |
| `district_percentile` | number | 计算 | 该房单价在同区分布中的分位（0–100） |
| `district_sample_size` | int | 计算 | 同区样本数 |
| `similar` | `SimilarItem[]` | 计算 | 相似房源，见 §1.3 |

### 1.3 `SimilarItem`

| 字段 | 类型 | 说明 |
|---|---|---|
| `house_id` | int | 房源 id |
| `community_name` | string | 小区名 |
| `street_name` | string | 街道名 |
| `area` / `total_price` / `unit_price` | number | 三项价格与面积 |
| `house_age` | int | 房龄 |
| `match_level` | enum | `community` / `street` / `district`（降级层级） |
| `area_diff_pct` | number | 面积差异百分比 |
| `age_diff` | int | 房龄差异（年） |

### 1.4 `PremiumResult` —— 溢价（双口径）

```json
{
  "metric": "metro",
  "control": "district",
  "base_group": "不近地铁",
  "groups": [
    { "group": "近地铁", "n": 1308, "avg_unit_price": 73419.60,
      "premium_pct": 27.44, "insufficient_sample": false }
  ],
  "by_district": [
    { "district_id": 11, "district_name": "朝阳", "base_avg": 66000.0,
      "target_avg": 78000.0, "premium_pct": 18.18, "n_base": 320, "n_target": 420 }
  ],
  "caliber": "算术均值；溢价率 =(组均价-基准均价)/基准均价×100；n<3 不参与计算"
}
```

> `control=none` 时只返回 `groups`；`control=district` 时额外返回 `by_district`。
> **`caliber` 字段必须回传**，前端把它显示在图表的"口径说明"里。

---

## 2. 接口总表（30 个）

| # | 方法 | 路径 | 鉴权 | 模块 | 功能点 | 一句话 |
|---|---|---|---|---|---|---|
| 1 | GET | `/health` | 公开 | M8 | FP-M8-05 | 健康检查 |
| 2 | GET | `/meta/districts` | 公开 | M2 | FP-M2-02 | 区字典 |
| 3 | GET | `/meta/streets` | 公开 | M2 | FP-M2-02 | 街道字典（按区联动） |
| 4 | GET | `/meta/filters` | 公开 | M2 | FP-M2-05 | 筛选项枚举与取值范围 |
| 5 | GET | `/houses` | 公开 | M2 | FP-M2-01~06 | 多条件检索 |
| 6 | GET | `/houses/{id}` | 公开 | M3 | FP-M3-01~03 | 房源详情 |
| 7 | GET | `/houses/{id}/similar` | 公开 | M3 | FP-M3-03 | 相似房源（可单独调用） |
| 8 | GET | `/houses/compare` | 公开 | M3 | FP-M3-05~06 | 多房源对比 |
| 9 | GET | `/analytics/district-summary` | 公开 | M4 | FP-M4-01 | 区级汇总 |
| 10 | GET | `/analytics/price-distribution` | 公开 | M4 | FP-M4-02 | 价格分布直方图 |
| 11 | GET | `/analytics/area-price-scatter` | 公开 | M4 | FP-M4-03 | 面积-总价散点 |
| 12 | GET | `/analytics/age-price-trend` | 公开 | M4 | FP-M4-04 | 全市房龄-单价 |
| 13 | GET | `/analytics/age-price-by-district` | 公开 | M4 | FP-M4-05 | **分区房龄-单价对照** |
| 14 | GET | `/analytics/premium` | 公开 | M4 | FP-M4-06 | 溢价双口径 |
| 15 | GET | `/analytics/floor-orientation` | 公开 | M4 | FP-M4-07 | 楼层与朝向 |
| 16 | GET | `/analytics/value-anomaly` | 公开 | M4/M3 | FP-M3-02 | 性价比异常房源 |
| 17 | GET | `/communities/{id}` | 公开 | M5 | FP-M5-01~03 | 小区画像 |
| 18 | GET | `/rankings` | 公开 | M5 | FP-M5-04~05 | 小区/街道排行 |
| 19 | POST | `/valuation` | 可选 | M6 | FP-M6-01~05 | 估价参考 |
| 20 | POST | `/auth/register` | 公开 | M8 | FP-M8-01 | 注册 |
| 21 | POST | `/auth/login` | 公开 | M8 | FP-M8-02 | 登录 |
| 22 | GET | `/auth/me` | 登录 | M8 | FP-M8-03 | 当前用户 |
| 23 | POST | `/favorites/{house_id}` | 登录 | M7 | FP-M7-01 | 收藏 |
| 24 | DELETE | `/favorites/{house_id}` | 登录 | M7 | FP-M7-01 | 取消收藏 |
| 25 | GET | `/favorites` | 登录 | M7 | FP-M7-02 | 收藏列表 |
| 26 | POST | `/admin/import` | admin | M1 | FP-M1-01~04 | 导入数据 |
| 27 | GET | `/admin/batches` | admin | M1 | FP-M1-06 | 批次列表 |
| 28 | GET | `/admin/batches/{id}/report` | admin | M1 | FP-M1-05 | 质量报告 |
| 29 | GET | `/admin/logs` | admin | M8 | FP-M8-04 | 操作日志 |
| 30 | GET | `/analytics/layout-distribution` | 公开 | M4 | FP-M4-09 | 户型构成与各户型均价 |

---

## 3. 接口明细

### 3.1 元数据

#### GET `/api/v1/meta/districts`

无参数。返回 17 行（顺序固定为 `district_id` 升序）。

```json
{ "list": [ { "district_id": 1, "district_name": "东城", "house_count": 115 } ] }
```

#### GET `/api/v1/meta/streets`

| 参数 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| `district_id` | int | 否 | — | 存在性校验（否则 `3001`） |
| `include_pseudo` | bool | 否 | `false` | — |

```json
{ "list": [ { "street_id": 1, "district_id": 1, "street_name": "东四",
              "is_pseudo": 0, "house_count": 4 } ] }
```

#### GET `/api/v1/meta/filters`

返回前端筛选项枚举与数据实际取值范围（供双滑块用）。

```json
{
  "decoration": ["精装", "简装", "其他", "毛坯"],
  "structure": ["板楼", "塔楼", "板塔结合", "独栋别墅", "平房"],
  "direction": ["东", "南", "西", "北", "东北", "东南", "西南", "西北"],
  "floor_level": ["低", "中", "高", "顶层", "底层", "地下", "上叠", "未知"],
  "ranges": { "total_price": [36, 8000], "area": [16.07, 747.23],
              "house_age": [3, 50], "room": [1, 12], "hall": [0, 4] }
}
```

### 3.2 检索

#### GET `/api/v1/houses`

| 参数 | 类型 | 必填 | 默认 | 校验 / 说明 |
|---|---|---|---|---|
| `keyword` | string | 否 | — | 小区名前缀匹配，长度 1–32 |
| `district_id` | int | 否 | — | 存在性校验 |
| `street_id` | int | 否 | — | 存在性校验 |
| `community_id` | int | 否 | — | 存在性校验 |
| `price_min` / `price_max` | number | 否 | — | 万元；`min ≤ max`，越界 `1001` |
| `area_min` / `area_max` | number | 否 | — | ㎡；同上 |
| `room` | int | 否 | — | 1–20 |
| `hall` | int | 否 | — | 0–10（**0 是合法值**） |
| `age_max` | int | 否 | — | 0–50 |
| `decoration[]` | string[] | 否 | — | 重复参数或逗号分隔 |
| `structure[]` | string[] | 否 | — | 同上 |
| `direction[]` | string[] | 否 | — | 走 `house_orientation` 联查 |
| `near_subway` | 0\|1 | 否 | — | — |
| `include_outlier` | bool | 否 | `true` | 设 `false` 则排除 `is_outlier=1` |
| `sort` | enum | 否 | `unit_price` | 白名单：`unit_price`/`total_price`/`area`/`house_age`/`house_id`；非法 `1002` |
| `order` | enum | 否 | `asc` | `asc`/`desc` |
| `page` / `page_size` | int | 否 | 1 / 20 | 见 §0.2 |

组合逻辑：不同参数之间 **AND**；同一数组参数内部 **IN（即 OR）**。

```json
{
  "code": 0, "message": "ok", "request_id": "3f9c1a2b",
  "data": {
    "list": [ /* HouseCard */ ],
    "total": 128, "page": 1, "page_size": 20, "took_ms": 18
  }
}
```

`total` 与 `list` 必须共用同一 where 构造器；排序时以 `house_id` 作次级排序键保证分页稳定。

### 3.3 详情 / 相似 / 对比

#### GET `/api/v1/houses/{id}`

返回 `HouseDetail`。`id` 不存在返回 `3001`。

```json
{
  "data": {
    "house_id": 1605, "community_name": "台湖银河湾", "district_name": "通州",
    "street_name": "通州其他", "room": 3, "hall": 1, "area": 79.74,
    "total_price": 550.0, "unit_price": 68975.0,
    "floor_level": "中", "floor_total": 18, "floor_raw": "中楼层(共18层)",
    "house_age": 6, "decoration": "精装", "structure": "板楼", "near_subway": 0,
    "orientation_text": "南 北", "directions": ["南", "北"],
    "is_outlier": 0, "abnormal_layout": 0, "source_row_no": 1,
    "community": { "house_count": 2, "avg_unit_price": 66291.0,
                   "median_total_price": 537.5, "avg_area": 79.15, "avg_age": 9.5 },
    "district_percentile": 71.4, "district_sample_size": 288,
    "similar": [ /* SimilarItem，最多 5 条 */ ]
  }
}
```

#### GET `/api/v1/houses/{id}/similar`

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `limit` | int | 否 | 5（1–20） |

召回规则（与 M6 估价共用同一实现）：
1. 同小区 → 面积 ±20% → 房龄 ±5 年
2. 样本 < 3 则降级到同街道
3. 仍不足则降级到同区
4. 回传 `match_level` 与 `fallback_level`，**不得静默返回空**

#### GET `/api/v1/houses/compare`

| 参数 | 类型 | 必填 | 校验 |
|---|---|---|---|
| `ids` | string | 是 | 逗号分隔 1–4 个；>4 返回 `1001`；任一 id 不存在 `3001` |

```json
{
  "data": {
    "attributes": [
      { "key": "unit_price", "label": "单价(元/㎡)",
        "values": [68975.0, 78226.0], "diff": true, "best_index": 0 }
    ],
    "radar": {
      "dimensions": ["面积", "单价", "房龄", "地铁", "装修"],
      "normalize_range": { "面积": [16.07, 747.23], "单价": [12742, 179843],
                           "房龄": [3, 50] },
      "series": [ { "house_id": 1605, "scores": [11, 33, 94, 0, 75] } ]
    }
  }
}
```

> `normalize_range` **必须回传**：没有归一化范围，两个雷达图的形状不可比。
> `scores` 为 0–100；房龄与装修为"越优分越高"（新房龄小分高、精装分高）。

### 3.4 分析看板

#### GET `/api/v1/analytics/district-summary`

无参数。

```json
{ "list": [ { "district_id": 1, "district_name": "东城", "house_count": 115,
  "avg_unit_price": 113391.86, "median_unit_price": 113954.0,
  "median_total_price": 768.0, "avg_area": 91.2, "avg_age": 24.1,
  "insufficient_sample": false } ] }
```

> 优先读 `district` 聚合快照；实现时须有一条自检保证快照与实时聚合一致。

#### GET `/api/v1/analytics/price-distribution`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `metric` | enum | 否 | `total` | `total`(总价) / `unit`(单价) / `area`(面积) |
| `district_id` | int | 否 | — | 可选范围限定 |
| `bins` | int | 否 | 10 | 3–50 |
| `binning` | enum | 否 | `quantile` | `quantile`(分位分桶，**推荐**) / `linear` |

```json
{ "data": { "metric": "total", "binning": "quantile", "total": 2890,
  "bins": [ { "low": 36, "high": 218, "count": 289 } ],
  "stats": { "min": 36, "p25": 320, "median": 470, "p75": 698, "max": 8000 } } }
```

> **默认必须是分位分桶**：总价 36–8000 用等宽 10 桶会把 60% 样本挤进第一桶。

#### GET `/api/v1/analytics/area-price-scatter`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `district_id` | int | 否 | — | — |
| `limit` | int | 否 | 500 | 1–2890；超量按 `house_id` 均匀抽样保证可复现 |

```json
{ "data": { "points": [ { "x": 79.74, "y": 550.0, "is_outlier": 0, "house_id": 1605 } ],
  "pearson_r": 0.719, "n": 2890,
  "regression": { "slope": 5.94, "intercept": 42.5 } } }
```

`points` 中 `x` 为面积、`y` 为总价（**不是单价**，见 SRS Q3）。

#### GET `/api/v1/analytics/age-price-trend`

无必需参数；可选 `district_id`。房龄段固定为 `(0,5] (5,10] (10,15] (15,20] (20,25] (25,30] (30,40] (40,50]`。

```json
{ "data": { "buckets": [ { "bucket": "(30,40]", "avg_unit_price": 77852.30,
  "n": 422, "insufficient_sample": false } ], "pearson_r": 0.260 } }
```

#### GET `/api/v1/analytics/age-price-by-district`　★ 核心图

| 参数 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| `top_n` | int | 否 | 6 | 1–17；按区内套数降序取前 n 个区 |

```json
{ "data": {
  "buckets": ["(0,5]", "(5,10]", "...", "(40,50]"],
  "series": [ { "district_id": 11, "district_name": "朝阳",
                "points": [ { "bucket": "(0,5]", "avg_unit_price": 61000.0, "n": 12 } ] } ],
  "caliber": "分区后各房龄段的算术均价；n<3 的点不输出" } }
```

> 这张图存在的原因：全市口径下房龄与单价正相关（r=+0.260）是区位混杂的假象。
> 接口必须同时提供全市（接口 12）与分区（本接口）两组数据，缺一不可。

#### GET `/api/v1/analytics/premium`

| 参数 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| `metric` | enum | 是 | — | `metro` / `decoration` / `structure` |
| `control` | enum | 否 | `district` | `none` / `district` |
| `base_group` | string | 否 | 见下 | 默认：metro→`不近地铁`；decoration→`简装`；structure→`板楼` |

```json
{ "data": { /* PremiumResult，见 §1.4 */ } }
```

实现约束：
- `structure` 的 `平房`(1 条) 与 `独栋别墅`(1 条) 样本量 < 3，必须返回 `insufficient_sample=true`（不得剔除，以保留可解释性）
- `decoration` 建议同时支持 `by_area_band`（附加参数 `stratify=area_band`），因为毛坯中位总价 549.5 万高于精装 515 万，不分层会得出"毛坯更贵"

#### GET `/api/v1/analytics/floor-orientation`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `metric` | enum | 否 | `both` | `floor` / `orientation` / `both` |

```json
{ "data": {
  "floor": [ { "level": "中", "avg_unit_price": 63400.0, "n": 870 } ],
  "orientation": [ { "direction": "南", "avg_unit_price": 61403.83, "n": 1976 } ],
  "orientation_spread": { "south_minus_north_pct": 1.80, "south_n": 1976, "north_n": 1624 } } }
```

> `floor_level='未知'`（364 条）必须单独一组，不得与其他层级合并。

#### GET `/api/v1/analytics/value-anomaly`

| 参数 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| `district_id` | int | 否 | — | — |
| `area_band` | enum | 否 | `60-90` | `lt60`/`60-90`/`90-120`/`120-150`/`150-180`/`180-210`/`gt210` |
| `threshold` | number | 否 | 0.20 | 低于同组中位价的比例，0.05–0.5 |
| `limit` | int | 否 | 20 | 1–100 |

```json
{ "data": { "group": { "district_id": 11, "area_band": "60-90", "n": 260,
    "median_unit_price": 66000.0 },
  "list": [ { "house_id": 812, "community_name": "苹果派", "unit_price": 28269.0,
              "deviation_pct": -57.2, "is_outlier": 1 } ] } }
```

> **必须限定"同区 + 同面积段"**：全市口径下东西城会整片被判为异常。

### 3.5 小区画像与排行

#### GET `/api/v1/communities/{id}`

```json
{ "data": {
  "community_id": 1605, "community_name": "台湖银河湾",
  "district_id": 15, "district_name": "通州", "street_id": 249, "street_name": "通州其他",
  "house_count": 2, "avg_unit_price": 66291.0, "median_total_price": 537.5,
  "avg_area": 79.15, "avg_age": 9.5,
  "street_percentile": 62.5, "street_community_count": 8,
  "houses": [ /* HouseCard，该小区在售 */ ],
  "street_rank": [ { "community_id": 12, "community_name": "某小区",
                     "avg_unit_price": 71000.0, "house_count": 3 } ] } }
```

> `house_count` 中位为 1、**67.4% 的小区仅 1 套**：前端不得对该小区画箱线图，只能画"在同街道中的位置"。

#### GET `/api/v1/rankings`

| 参数 | 类型 | 必填 | 默认 | 校验 |
|---|---|---|---|---|
| `scope` | enum | 是 | — | `community` / `street` |
| `by` | enum | 否 | `avg_unit_price` | `avg_unit_price` / `house_count` |
| `order` | enum | 否 | `desc` | `asc`/`desc` |
| `min_count` | int | 否 | 3 | 1–100；**小于该样本量的条目被排除** |
| `include_pseudo` | bool | 否 | `false` | `street` 范围时生效 |
| `limit` | int | 否 | 20 | 1–100 |

```json
{ "data": { "list": [ { "id": 1, "name": "东四", "district_name": "东城",
  "house_count": 4, "avg_unit_price": 105843.5, "median_total_price": 782.0 } ],
  "excluded_by_min_count": 1257, "excluded_pseudo": 16 } }
```

### 3.6 估价

#### POST `/api/v1/valuation`

```json
{ "district_id": 11, "street_id": 138, "area": 80.0, "room": 2, "hall": 1,
  "age": 10, "decoration": "精装", "floor_level": "中", "near_subway": 1 }
```

| 参数 | 类型 | 必填 | 校验 |
|---|---|---|---|
| `district_id` | int | 是 | 存在性 |
| `street_id` | int | 否 | 存在性且属于该区 |
| `area` | number | 是 | **10–1000**，越界 `1001` |
| `room` / `hall` | int | 是 | 1–20 / 0–10 |
| `age` | int | 是 | 0–50 |
| `decoration` / `floor_level` | enum | 否 | 枚举校验 |
| `near_subway` | 0\|1 | 否 | — |

```json
{ "data": {
  "est_unit_price": 68400.12, "est_total_price": 547.20,
  "price_range": { "low": 503.42, "high": 590.98, "pct": 8 },
  "sample_count": 37, "fallback_level": "street",
  "confidence": "medium",
  "disclaimer": "本结果基于相似房源加权均价，仅供参考，不构成评估报告",
  "model_version": "wa-1.0" } }
```

算法（必须逐条实现，不得自创）：
1. 召回：同小区 → 面积 ±20% 且房龄 ±5 年
2. 权重：`w = 1/(1+面积差比) × 1/(1+房龄差/10)`
3. 估算单价：`Σ(w×unit_price) / Σw`；总价 = 单价 × area / 10000
4. 区间：±8%
5. 降级：样本 <5 降街道（confidence=medium）→ <3 降区（low）→ 0 条返回 `insufficient_sample=true`、`est_*` 为 `null`

### 3.7 认证与收藏

| 接口 | 入参 | 出参要点 |
|---|---|---|
| POST `/auth/register` | `username`(3–32)、`password`(8–64) | `user_id`、`username`、`role` |
| POST `/auth/login` | `username`、`password` | `token`、`expires_in`(秒)、`user{user_id,username,role}`；失败 `2001`，锁定 `2004`（含 `lock_until`） |
| GET `/auth/me` | — | `user{user_id,username,role,last_login_at}` |
| POST `/favorites/{house_id}` | — | `{favorited:true, already:false}`；重复收藏 `already:true` 且仍返回成功 |
| DELETE `/favorites/{house_id}` | — | `{favorited:false}`（不存在也返回成功，幂等） |
| GET `/favorites` | `page`/`page_size` | 分页 `HouseCard` 列表 |

### 3.8 管理与健康检查

| 接口 | 入参 | 出参要点 |
|---|---|---|
| GET `/health` | — | `{status:"ok", db:"up", version:"0.1.0", house_rows:2890}` |
| POST `/admin/import` | `file`(multipart, .xlsx, ≤20MB)、`dry_run`(bool，默认 false) | `{batch_id, total_rows, loaded_rows, rejected_rows, duration_ms, rules_triggered, report_url}` |
| GET `/admin/batches` | 分页 | 批次列表：`{batch_id, file_name, total_rows, loaded_rows, rejected_rows, status, duration_ms, created_at, operator}` |
| GET `/admin/batches/{id}/report` | — | `{batch, rules_triggered, issues_by_type, samples[≤50], failures[]}` |
| GET `/admin/logs` | 分页 + `action`(可选) | 操作日志列表 |

导入实现约束：
- 逐行校验复用 `etl/validate.py`，**与命令行同一份代码**，不另写一套
- 批量插入每 500 行一批，整批事务；失败可整批回滚
- 失败行写 `data_quality_issue`，成功行入库
- `dry_run=true` 时只产出报告、整体回滚

---

## 4. 与数据库的字段对应（防漂移锚点）

| 契约字段 | 表.字段 | 类型一致性 |
|---|---|---|
| `house_id` | `house.id` | BIGINT |
| `source_row_no` | `house.source_row_no` | INT |
| `district_id` | `house.district_id` | BIGINT |
| `street_id` | `house.street_id` | BIGINT |
| `community_id` | `house.community_id` | BIGINT |
| `district_name` | `district.name` | VARCHAR(32) |
| `street_name` | `street.name` | VARCHAR(64) |
| `community_name` | `community.name` | VARCHAR(128) |
| `room` | `house.room` | TINYINT |
| `hall` | `house.hall` | TINYINT（0 合法） |
| `area` | `house.area` | DECIMAL(8,2) |
| `total_price` | `house.total_price` | DECIMAL(10,2) |
| `unit_price` | `house.unit_price` | DECIMAL(10,2) |
| `floor_level` | `house.floor_level` | ENUM 8 值 |
| `floor_total` | `house.floor_total` | TINYINT（可空） |
| `floor_raw` | `house.floor_raw` | VARCHAR(32) |
| `house_age` | `house.house_age` | TINYINT |
| `decoration` | `house.decoration` | ENUM 4 值 |
| `structure` | `house.structure` | ENUM 5 值 |
| `orientation_text` | `house.orientation_text` | VARCHAR(32) |
| `directions` | `house_orientation.direction` | ENUM 8 值（M:N） |
| `near_subway` | `house.near_subway` | TINYINT 0/1 |
| `is_outlier` | `house.is_outlier` | TINYINT 0/1 |
| `abnormal_layout` | `house.abnormal_layout` | TINYINT 0/1 |
| `is_pseudo` | `street.is_pseudo` | TINYINT 0/1 |
| `house_count` | `community.house_count` / `street.house_count` | INT UNSIGNED |
| `avg_unit_price` | `district.avg_unit_price` / `street.avg_unit_price` / `community.avg_unit_price` | DECIMAL(10,2) |
| `median_total_price` | `district.median_total_price` / `community.median_total_price` | DECIMAL(10,2) |
| `batch_id` | `import_batch.id` | BIGINT |
| `total_rows` / `loaded_rows` / `rejected_rows` | `import_batch.*` | INT UNSIGNED |
| `rule_code` | `data_quality_issue.rule_code` | VARCHAR(8) |
| `lock_until` | `app_user.lock_until` | DATETIME(3) |
| `est_unit_price` / `est_total_price` | `valuation_record.est_unit_price` / `.est_total_price` | DECIMAL(10,2) |
| `confidence` / `fallback_level` | `valuation_record.confidence` / `.fallback_level` | ENUM |
| `district_percentile` | —（计算值：同区单价分位） | 0–100，1 位小数 |
| `premium_pct` | —（计算值：溢价率） | 百分比，2 位小数 |
| `pearson_r` | —（计算值：皮尔逊相关系数） | −1…1，3 位小数 |

**校验机制**：批 4 完成后由 `tools/check_contract.py` 自动比对
「后端路由表 ↔ 本文件接口表 ↔ `frontend/src/api/*.js` ↔ `schema_model.py`」四处，
不一致即报错。当前 `tools/check_docs.py` 已先行校验"本文件出现的每个 `表.字段` 均真实存在"。

---

## 5. 契约变更记录

| 版本 | 日期 | 变更 | 影响 |
|---|---|---|---|
| v1 | 2026-10 | 首版冻结，29 个接口 | 批 4 后端、批 5 前端以此为准 |
| v1.1 | 2026-11 | 新增第 30 个接口 `/analytics/layout-distribution`（补 Q8 的实现缺口）；`/health` 增加均价双口径字段 | 前端 P5 户型构成图不再由前端自行聚合 |
