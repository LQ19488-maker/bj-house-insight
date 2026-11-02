/**
 * 静态数据源：GitHub Pages 用。
 *
 * 只依赖两个 JSON（构建时由 tools/export_static.py 生成）：
 *   public/data/houses.json  —— 2890 条房源（约 70 KB gzip）
 *   public/data/meta.json    —— 区/街道字典 + 筛选项
 *
 * 所有查询、聚合、分位、溢价、估价都在**浏览器内存**里算。
 * 算法与后端 service 层逐条对齐（口径见 docs/api-contract.md §0.4），
 * 因此同一个页面在 http 与 static 两种模式下得到的数字一致。
 */

// Vite 注入 BASE_URL；在 Node 里直接跑一致性测试时该值为 undefined，故用可选链兜底
const BASE = import.meta.env?.BASE_URL || '/'
const DATA_URL = `${BASE}data/`

const SAMPLE_MIN = 3
const FLOOR_LEVELS = ['低', '中', '高', '顶层', '底层', '地下', '上叠', '未知']
const AGE_BUCKETS = ['0-5', '5-10', '10-15', '15-20', '20-25', '25-30', '30-40', '40-50']
const AREA_BANDS = ['lt60', '60-90', '90-120', '120-150', '150-180', '180-210', 'gt210']
const DECO_SCORE = { 精装: 100, 简装: 66, 其他: 33, 毛坯: 0 }

// ---------------------------------------------------------------------------
// 加载与解包（只做一次，后续走内存）
// ---------------------------------------------------------------------------
let cache = null

async function load() {
  if (cache) return cache
  const [houseResp, meta] = await Promise.all([
    fetch(`${DATA_URL}houses.json`).then((r) => {
      if (!r.ok) throw new Error(`加载 houses.json 失败（HTTP ${r.status}）`)
      return r.json()
    }),
    fetch(`${DATA_URL}meta.json`).then((r) => r.json())
  ])

  const cols = houseResp.cols
  const houses = houseResp.rows.map((row) => {
    const h = {}
    cols.forEach((c, i) => { h[c] = row[i] })
    // 与契约字段名对齐
    const card = {
      house_id: h.id,
      district_id: h.did,
      district_name: h.dname,
      street_id: h.sid,
      street_name: h.sname,
      community_id: h.cid,
      community_name: h.cname,
      room: h.room,
      hall: h.hall,
      area: h.area,
      total_price: h.total,
      unit_price: h.unit,
      floor_level: h.floor_level,
      floor_total: h.floor_total,
      house_age: h.age,
      decoration: h.deco,
      structure: h.struct,
      near_subway: h.subway,
      orientation_text: h.orient,
      is_outlier: h.outlier,
      abnormal_layout: h.abnormal
    }
    const directions = h.orient ? String(h.orient).split(' ').filter(Boolean) : []
    return { ...card, directions }
  })

  cache = { houses, meta, byId: new Map(houses.map((h) => [h.house_id, h])) }
  return cache
}

// ---------------------------------------------------------------------------
// 统计工具（与后端口径一致）
// ---------------------------------------------------------------------------
const round = (v, n = 2) => (v === null || v === undefined || Number.isNaN(v)
  ? null
  : Math.round(v * 10 ** n) / 10 ** n)

function quantile(sorted, q) {
  if (!sorted.length) return null
  const pos = (sorted.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  if (lo === hi) return sorted[lo]
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

const median = (vals) => {
  const s = [...vals].sort((a, b) => a - b)
  return quantile(s, 0.5)
}
const mean = (vals) => (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null)

function pearson(xs, ys) {
  const n = xs.length
  if (n < 3) return null
  const sx = xs.reduce((a, b) => a + b, 0)
  const sy = ys.reduce((a, b) => a + b, 0)
  const sxy = xs.reduce((a, x, i) => a + x * ys[i], 0)
  const sxx = xs.reduce((a, x) => a + x * x, 0)
  const syy = ys.reduce((a, y) => a + y * y, 0)
  const den = Math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
  return den ? round((n * sxy - sx * sy) / den, 4) : null
}

function ageBucket(age) {
  if (age === null || age === undefined) return null
  for (const label of AGE_BUCKETS) {
    const hi = Number(label.split('-')[1])
    if (age <= hi) return label
  }
  return AGE_BUCKETS[AGE_BUCKETS.length - 1]
}

function areaBand(area) {
  if (area < 60) return 'lt60'
  if (area < 90) return '60-90'
  if (area < 120) return '90-120'
  if (area < 150) return '120-150'
  if (area < 180) return '150-180'
  if (area < 210) return '180-210'
  return 'gt210'
}

const avgUnit = (list) => round(mean(list.map((h) => h.unit_price)))

function insufficient(rows, key = 'n') {
  return rows.map((r) => ({ ...r, insufficient_sample: (r[key] || 0) < SAMPLE_MIN }))
}

// ---------------------------------------------------------------------------
// 检索
// ---------------------------------------------------------------------------
function matches(h, p) {
  if (p.keyword && !(h.community_name || '').startsWith(String(p.keyword))) return false
  if (p.district_id != null && h.district_id !== Number(p.district_id)) return false
  if (p.street_id != null && h.street_id !== Number(p.street_id)) return false
  if (p.community_id != null && h.community_id !== Number(p.community_id)) return false
  if (p.price_min != null && h.total_price < p.price_min) return false
  if (p.price_max != null && h.total_price > p.price_max) return false
  if (p.area_min != null && h.area < p.area_min) return false
  if (p.area_max != null && h.area > p.area_max) return false
  if (p.room != null && h.room !== Number(p.room)) return false
  if (p.hall != null && h.hall !== Number(p.hall)) return false
  if (p.age_max != null && (h.house_age ?? 0) > Number(p.age_max)) return false
  if (p.decoration?.length && !p.decoration.includes(h.decoration)) return false
  if (p.structure?.length && !p.structure.includes(h.structure)) return false
  if (p.near_subway != null && h.near_subway !== Number(p.near_subway)) return false
  if (p.direction?.length && !p.direction.some((d) => h.directions.includes(d))) return false
  if (p.include_outlier === false && h.is_outlier === 1) return false
  return true
}

const SORT_KEY = {
  unit_price: (h) => h.unit_price,
  total_price: (h) => h.total_price,
  area: (h) => h.area,
  house_age: (h) => h.house_age ?? 0,
  house_id: (h) => h.house_id
}

export async function getHouses(params = {}) {
  const t0 = performance.now()
  const { houses } = await load()
  const filtered = houses.filter((h) => matches(h, params))

  const key = SORT_KEY[params.sort] || SORT_KEY.unit_price
  const dir = String(params.order || 'asc').toLowerCase() === 'desc' ? -1 : 1
  filtered.sort((a, b) => {
    const d = (key(a) - key(b)) * dir
    return d !== 0 ? d : a.house_id - b.house_id   // 次级排序键保证分页稳定
  })

  const page = Math.max(1, Number(params.page) || 1)
  const size = Math.min(100, Math.max(1, Number(params.page_size) || 20))
  const start = (page - 1) * size
  const list = filtered.slice(start, start + size).map(({ directions, ...card }) => card)

  return {
    list,
    total: filtered.length,
    page,
    page_size: size,
    took_ms: round(performance.now() - t0, 1)
  }
}

export async function getHouse(id) {
  const { houses, byId } = await load()
  const h = byId.get(Number(id))
  if (!h) throw new Error(`房源 ${id} 不存在`)

  const districtHouses = houses.filter((x) => x.district_id === h.district_id)
  const prices = districtHouses.map((x) => x.unit_price).sort((a, b) => a - b)
  const below = districtHouses.filter((x) => x.unit_price < h.unit_price).length

  const communityHouses = houses.filter((x) => x.community_id === h.community_id)
  const community = {
    house_count: communityHouses.length,
    avg_unit_price: avgUnit(communityHouses),
    median_total_price: round(median(communityHouses.map((x) => x.total_price))),
    avg_area: round(mean(communityHouses.map((x) => x.area))),
    avg_age: round(mean(communityHouses.map((x) => x.house_age ?? 0)))
  }

  const { list: similar } = await getSimilar(h.house_id, 5)

  return {
    ...h,
    floor_raw: h.floor_level === '未知'
      ? `${h.floor_total}层`
      : `${h.floor_level}楼层(共${h.floor_total}层)`,
    source_row_no: h.house_id,
    community,
    district_percentile: prices.length ? round((below / prices.length) * 100, 1) : null,
    district_sample_size: prices.length,
    district_quantiles: {
      p25: round(quantile(prices, 0.25)),
      p50: round(quantile(prices, 0.5)),
      p75: round(quantile(prices, 0.75))
    },
    similar
  }
}

export async function getSimilar(id, limit = 5) {
  const { houses, byId } = await load()
  const h = byId.get(Number(id))
  if (!h) throw new Error(`房源 ${id} 不存在`)

  const AREA_PCT = 0.2
  const AGE_DIFF = 5

  const scopes = [
    ['community', (x) => x.community_id === h.community_id],
    ['street', (x) => x.street_id === h.street_id],
    ['district', (x) => x.district_id === h.district_id]
  ]

  let chosen = []
  let level = 'none'
  for (const [name, pred] of scopes) {
    const rows = houses
      .filter((x) => x.house_id !== h.house_id && pred(x))
      .filter((x) => Math.abs(x.area - h.area) <= h.area * AREA_PCT)
      .filter((x) => Math.abs((x.house_age ?? 0) - (h.house_age ?? 0)) <= AGE_DIFF)
      .sort((a, b) => Math.abs(a.area - h.area) - Math.abs(b.area - h.area))
      .slice(0, limit)

    if (rows.length) { chosen = rows; level = name }
    if (rows.length >= SAMPLE_MIN) break
  }

  const list = chosen.map((x) => ({
    house_id: x.house_id,
    community_name: x.community_name,
    street_name: x.street_name,
    area: round(x.area),
    total_price: round(x.total_price),
    unit_price: round(x.unit_price),
    house_age: x.house_age,
    match_level: level,
    area_diff_pct: round(((x.area - h.area) / h.area) * 100),
    age_diff: (x.house_age ?? 0) - (h.house_age ?? 0)
  }))

  return { house_id: h.house_id, fallback_level: level, sample_count: list.length, list }
}

// ---------------------------------------------------------------------------
// 对比
// ---------------------------------------------------------------------------
const COMPARE_ATTRS = [
  ['unit_price', '单价(元/㎡)', true, 'lower'],
  ['total_price', '总价(万元)', true, 'lower'],
  ['area', '面积(㎡)', true, 'higher'],
  ['layout', '户型', false, null],
  ['house_age', '房龄(年)', true, 'lower'],
  ['decoration', '装修', false, null],
  ['structure', '结构', false, null],
  ['floor_level', '楼层', false, null],
  ['orientation_text', '朝向', false, null],
  ['near_subway', '近地铁', true, 'higher'],
  ['is_outlier', '极值标记', false, null],
  ['abnormal_layout', '非常规户型', false, null]
]

export async function getCompare(ids = []) {
  const { houses, byId } = await load()
  if (!ids.length) throw new Error('ids 不能为空')
  if (ids.length > 4) throw new Error('最多只支持 4 套房源对比')

  const picked = ids.map((id) => byId.get(Number(id)))
  const missing = ids.filter((id, i) => !picked[i])
  if (missing.length) throw new Error(`房源不存在：${missing.join(',')}`)

  const pool = houses
  const rng = (key) => {
    let lo = Infinity
    let hi = -Infinity
    pool.forEach((h) => {
      const v = h[key]
      if (v == null) return
      if (v < lo) lo = v
      if (v > hi) hi = v
    })
    return [lo, hi]
  }
  const rangeArea = rng('area')
  const rangeUnit = rng('unit_price')
  const rangeAge = rng('house_age')

  const valueOf = (h, key) => (key === 'layout' ? `${h.room}室${h.hall}厅` : h[key])

  const attributes = COMPARE_ATTRS.map(([key, label, comparable, better]) => {
    const values = picked.map((h) => valueOf(h, key))
    const diff = new Set(values.map(String)).size > 1
    let best_index = null
    if (comparable && diff) {
      const nums = values.map(Number)
      best_index = better === 'lower'
        ? nums.indexOf(Math.min(...nums))
        : nums.indexOf(Math.max(...nums))
    }
    return { key, label, values, diff, best_index }
  })

  const norm = (v, [lo, hi], higherBetter = true) => {
    if (hi == null || lo == null || hi === lo) return 0
    const s = Math.max(0, Math.min(100, ((Number(v) - lo) / (hi - lo)) * 100))
    return round(higherBetter ? s : 100 - s, 1)
  }

  return {
    attributes,
    radar: {
      dimensions: ['面积', '单价', '房龄', '地铁', '装修'],
      normalize_range: {
        面积: rangeArea, 单价: rangeUnit, 房龄: rangeAge, 地铁: [0, 1], 装修: [0, 100]
      },
      series: picked.map((h) => ({
        house_id: h.house_id,
        scores: [
          norm(h.area, rangeArea, true),
          norm(h.unit_price, rangeUnit, false),
          norm(h.house_age ?? 0, rangeAge, false),
          round(h.near_subway * 100, 1),
          round(DECO_SCORE[h.decoration] ?? 0, 1)
        ]
      })),
      note: '房龄与单价为“越低越好”，得分已反向；装修按 精装100/简装66/其他33/毛坯0 折算'
    }
  }
}

// ---------------------------------------------------------------------------
// 分析
// ---------------------------------------------------------------------------
export async function getDistrictSummary() {
  const { meta } = await load()
  return meta.districts.map((d) => ({ ...d, insufficient_sample: d.house_count < SAMPLE_MIN }))
}

export async function getPriceDistribution({ metric = 'total', district_id, bins = 10, binning = 'quantile' } = {}) {
  const { houses } = await load()
  const key = { total: 'total_price', unit: 'unit_price', area: 'area' }[metric] || 'total_price'
  const scoped = district_id
    ? houses.filter((h) => h.district_id === Number(district_id))
    : houses
  const vals = scoped.map((h) => h[key]).filter((v) => v != null).sort((a, b) => a - b)
  if (!vals.length) return { metric, binning, total: 0, bins: [], stats: {} }

  let edges
  if (binning === 'quantile') {
    edges = Array.from({ length: bins + 1 }, (_, i) => quantile(vals, i / bins))
  } else {
    const lo = vals[0]
    const hi = vals[vals.length - 1]
    const step = hi > lo ? (hi - lo) / bins : 1
    edges = Array.from({ length: bins }, (_, i) => lo + step * i).concat([hi])
  }

  const counts = new Array(bins).fill(0)
  vals.forEach((v) => {
    for (let i = 0; i < bins; i += 1) {
      const last = i === bins - 1
      if ((v >= edges[i] && v < edges[i + 1]) || (last && v === edges[i + 1])) {
        counts[i] += 1
        break
      }
    }
  })

  return {
    metric,
    binning,
    total: vals.length,
    bins: counts.map((c, i) => ({ low: round(edges[i]), high: round(edges[i + 1]), count: c })),
    stats: {
      min: round(vals[0]),
      p25: round(quantile(vals, 0.25)),
      median: round(quantile(vals, 0.5)),
      p75: round(quantile(vals, 0.75)),
      max: round(vals[vals.length - 1])
    },
    caliber: '分位分桶（等宽分桶会把多数样本挤进第一桶）'
  }
}

export async function getScatter({ district_id, limit = 500 } = {}) {
  const { houses } = await load()
  const scoped = district_id
    ? houses.filter((h) => h.district_id === Number(district_id))
    : houses

  const xs = scoped.map((h) => h.area)
  const ys = scoped.map((h) => h.total_price)
  const r = pearson(xs, ys)

  const n = scoped.length
  const mx = mean(xs)
  const my = mean(ys)
  let sxy = 0
  let sxx = 0
  scoped.forEach((h) => {
    sxy += (h.area - mx) * (h.total_price - my)
    sxx += (h.area - mx) ** 2
  })
  const slope = sxx ? sxy / sxx : 0
  const intercept = my - slope * mx

  const step = Math.max(1, Math.floor(n / limit))
  const points = scoped
    .filter((_, i) => i % step === 0)
    .slice(0, limit)
    .map((h) => ({
      x: round(h.area), y: round(h.total_price),
      is_outlier: h.is_outlier, house_id: h.house_id
    }))

  return {
    points,
    pearson_r: r,
    n,
    regression: { slope: round(slope, 4), intercept: round(intercept, 4) },
    caliber: '横轴面积、纵轴总价；pearson_r 由全量样本计算（不是抽样点）'
  }
}

export async function getAgeTrend({ district_id } = {}) {
  const { houses } = await load()
  const scoped = district_id
    ? houses.filter((h) => h.district_id === Number(district_id))
    : houses

  const buckets = AGE_BUCKETS.map((label) => {
    const rows = scoped.filter((h) => ageBucket(h.house_age) === label)
    return rows.length
      ? { bucket: label, n: rows.length, avg_unit_price: avgUnit(rows) }
      : null
  }).filter(Boolean)

  return {
    buckets,
    pearson_r: pearson(
      scoped.map((h) => h.house_age ?? 0),
      scoped.map((h) => h.unit_price)
    ),
    caliber: '分区后各房龄段的算术均价；n<3 的点不输出；房龄以 2024 为基准年'
  }
}

export async function getAgeByDistrict({ top_n = 6 } = {}) {
  const { houses, meta } = await load()
  const tops = [...meta.districts]
    .sort((a, b) => b.house_count - a.house_count)
    .slice(0, top_n)

  const series = tops.map((d) => {
    const scoped = houses.filter((h) => h.district_id === d.district_id)
    const points = AGE_BUCKETS.map((label) => {
      const rows = scoped.filter((h) => ageBucket(h.house_age) === label)
      return rows.length
        ? { bucket: label, n: rows.length, avg_unit_price: avgUnit(rows) }
        : null
    }).filter((p) => p && p.n >= SAMPLE_MIN)

    return { district_id: d.district_id, district_name: d.district_name, points }
  })

  return {
    buckets: AGE_BUCKETS,
    series,
    caliber: '分区后各房龄段的算术均价；n<3 的点不输出',
    why: '全市口径下房龄与单价正相关是区位混杂造成的假象，本接口提供分区对照'
  }
}

const GROUP_FN = {
  metro: (h) => (h.near_subway === 1 ? '近地铁' : '不近地铁'),
  decoration: (h) => h.decoration,
  structure: (h) => h.structure
}
const DEFAULT_BASE = { metro: '不近地铁', decoration: '简装', structure: '板楼' }

function groupStats(list, fn) {
  const map = new Map()
  list.forEach((h) => {
    const g = fn(h)
    if (!map.has(g)) map.set(g, [])
    map.get(g).push(h)
  })
  return [...map.entries()]
    .map(([group, rows]) => ({ group, n: rows.length, avg_unit_price: avgUnit(rows) }))
    .sort((a, b) => b.n - a.n)
}

export async function getPremium({ metric = 'metro', control = 'district', base_group, stratify } = {}) {
  const { houses, meta } = await load()
  const fn = GROUP_FN[metric]
  const base = base_group || DEFAULT_BASE[metric]

  const groups = groupStats(houses, fn)
  const baseRow = groups.find((g) => g.group === base)
  const baseAvg = baseRow?.avg_unit_price
  groups.forEach((g) => {
    g.premium_pct = baseAvg ? round(((g.avg_unit_price - baseAvg) / baseAvg) * 100) : null
  })

  const out = {
    metric, control, base_group: base,
    groups: insufficient(groups),
    caliber: '算术均值；溢价率 =(组均价-基准组均价)/基准组均价×100，保留 2 位；n<3 不参与计算'
  }

  if (control === 'district') {
    const byDistrict = []
    // 与后端一致：按区内套数降序（不是按 district_id）
    const ordered = [...meta.districts].sort((a, b) => b.house_count - a.house_count)
    ordered.forEach((d) => {
      const scoped = houses.filter((h) => h.district_id === d.district_id)
      const stats = groupStats(scoped, fn)
      const b = stats.find((s) => s.group === base)
      if (!b) return
      stats.forEach((s) => {
        if (s.group === base) return
        byDistrict.push({
          district_id: d.district_id,
          district_name: d.district_name,
          group: s.group,
          base_avg: b.avg_unit_price,
          target_avg: s.avg_unit_price,
          premium_pct: b.avg_unit_price
            ? round(((s.avg_unit_price - b.avg_unit_price) / b.avg_unit_price) * 100)
            : null,
          n_base: b.n,
          n_target: s.n,
          insufficient_sample: b.n < SAMPLE_MIN || s.n < SAMPLE_MIN
        })
      })
    })
    out.by_district = byDistrict
  }

  if (stratify === 'area_band') {
    const byBand = {}
    AREA_BANDS.forEach((band) => {
      const scoped = houses.filter((h) => areaBand(h.area) === band)
      byBand[band] = insufficient(groupStats(scoped, fn))
    })
    out.by_area_band = byBand
  }

  return out
}

export async function getFloorOrientation({ metric = 'both' } = {}) {
  const { houses } = await load()
  const out = { caliber: '朝向经 M:N 展开后按方向聚合；楼层层级“未知”单独成组' }

  if (metric === 'floor' || metric === 'both') {
    const map = new Map()
    houses.forEach((h) => {
      const k = h.floor_level || '未知'
      if (!map.has(k)) map.set(k, [])
      map.get(k).push(h)
    })
    out.floor = insufficient(
      [...map.entries()]
        .map(([level, rows]) => ({ level, n: rows.length, avg_unit_price: avgUnit(rows) }))
        .sort((a, b) => b.n - a.n)
    )
  }

  if (metric === 'orientation' || metric === 'both') {
    const map = new Map()
    houses.forEach((h) => {
      h.directions.forEach((d) => {
        if (!map.has(d)) map.set(d, [])
        map.get(d).push(h)
      })
    })
    out.orientation = insufficient(
      [...map.entries()]
        .map(([direction, rows]) => ({
          direction, n: rows.length, avg_unit_price: avgUnit(rows)
        }))
        .sort((a, b) => b.n - a.n)
    )
    const south = out.orientation.find((o) => o.direction === '南')
    const north = out.orientation.find((o) => o.direction === '北')
    if (south && north && north.avg_unit_price) {
      out.orientation_spread = {
        south_minus_north_pct: round(
          ((south.avg_unit_price - north.avg_unit_price) / north.avg_unit_price) * 100
        ),
        south_n: south.n,
        north_n: north.n
      }
    }
  }

  return out
}

export async function getValueAnomaly({ district_id, area_band = '60-90', threshold = 0.2, limit = 20 } = {}) {
  const { houses, meta } = await load()
  const did = district_id
    ? Number(district_id)
    : [...meta.districts].sort((a, b) => b.house_count - a.house_count)[0].district_id

  const scoped = houses.filter(
    (h) => h.district_id === did && areaBand(h.area) === area_band
  )
  if (!scoped.length) {
    return { group: { district_id: did, area_band, n: 0, median_unit_price: null }, list: [] }
  }

  const med = median(scoped.map((h) => h.unit_price))
  const dname = meta.districts.find((d) => d.district_id === did)?.district_name || ''
  const list = scoped
    .filter((h) => h.unit_price <= med * (1 - threshold))
    .sort((a, b) => a.unit_price - b.unit_price)
    .slice(0, limit)
    .map(({ directions, ...card }) => ({
      ...card,
      deviation_pct: round(((card.unit_price - med) / med) * 100)
    }))

  return {
    group: { district_id: did, district_name: dname, area_band, n: scoped.length, median_unit_price: round(med) },
    threshold,
    list,
    caliber: '基准=同区+同面积段的单价中位数；deviation_pct 为相对基准的偏离百分比'
  }
}

// ---------------------------------------------------------------------------
// 小区与排行
// ---------------------------------------------------------------------------
function communityAgg(houses, communityId) {
  const rows = houses.filter((h) => h.community_id === communityId)
  if (!rows.length) return null
  return {
    community_id: communityId,
    community_name: rows[0].community_name,
    district_id: rows[0].district_id,
    district_name: rows[0].district_name,
    street_id: rows[0].street_id,
    street_name: rows[0].street_name,
    house_count: rows.length,
    avg_unit_price: avgUnit(rows),
    median_total_price: round(median(rows.map((h) => h.total_price))),
    avg_area: round(mean(rows.map((h) => h.area))),
    avg_age: round(mean(rows.map((h) => h.house_age ?? 0)))
  }
}

export async function getCommunity(id) {
  const { houses } = await load()
  const cid = Number(id)
  const agg = communityAgg(houses, cid)
  if (!agg) throw new Error(`小区 ${id} 不存在`)

  const peers = [...new Set(
    houses.filter((h) => h.street_id === agg.street_id).map((h) => h.community_id)
  )].map((c) => communityAgg(houses, c))
    .filter(Boolean)
    .sort((a, b) => (b.avg_unit_price || 0) - (a.avg_unit_price || 0))

  const lower = peers.filter((p) => (p.avg_unit_price || 0) < (agg.avg_unit_price || 0)).length
  const streetRows = houses.filter((h) => h.street_id === agg.street_id)

  return {
    ...agg,
    street_percentile: peers.length ? round((lower / peers.length) * 100, 1) : null,
    street_community_count: peers.length,
    street_avg_unit_price: avgUnit(streetRows),
    street_house_count: streetRows.length,
    houses: streetRows
      ? houses
        .filter((h) => h.community_id === cid)
        .sort((a, b) => a.unit_price - b.unit_price)
        .slice(0, 50)
        .map(({ directions, ...card }) => card)
      : [],
    street_rank: peers.map((p) => ({
      community_id: p.community_id,
      community_name: p.community_name,
      house_count: p.house_count,
      avg_unit_price: p.avg_unit_price,
      median_total_price: p.median_total_price
    })),
    note: '67.4% 的小区只有 1 套在售，因此只提供“在同街道中的位置”，不提供小区内价格波动分析'
  }
}

export async function getRankings({ scope = 'community', by = 'avg_unit_price', order = 'desc', min_count = 3, include_pseudo = false, limit = 20 } = {}) {
  const { houses, meta } = await load()
  const dir = String(order).toLowerCase() === 'desc' ? -1 : 1
  const key = by === 'house_count' ? 'house_count' : 'avg_unit_price'

  if (scope === 'street') {
    const rows = meta.streets
      .filter((s) => (include_pseudo ? true : s.is_pseudo === 0))
      .filter((s) => s.house_count >= min_count)
      .map((s) => ({
        id: s.street_id,
        name: s.street_name,
        district_name: meta.districts.find((d) => d.district_id === s.district_id)?.district_name || '',
        house_count: s.house_count,
        avg_unit_price: s.avg_unit_price,
        median_total_price: s.median_total_price,
        is_pseudo: s.is_pseudo
      }))
      .sort((a, b) => {
        const d = ((a[key] ?? 0) - (b[key] ?? 0)) * dir
        return d !== 0 ? d : a.id - b.id      // 次级排序键与后端一致，避免同值顺序漂移
      })

    return {
      scope,
      list: rows.slice(0, limit),
      excluded_by_min_count: meta.streets.filter((s) => s.house_count < min_count).length,
      excluded_pseudo: meta.streets.filter((s) => s.is_pseudo === 1).length,
      caliber: `仅统计 house_count >= ${min_count} 的条目；街道排行默认排除 is_pseudo=1 的伪街道`
    }
  }

  const aggMap = new Map()
  houses.forEach((h) => {
    if (!aggMap.has(h.community_id)) aggMap.set(h.community_id, [])
    aggMap.get(h.community_id).push(h)
  })
  const all = [...aggMap.entries()].map(([cid, rows]) => ({
    id: cid,
    name: rows[0].community_name,
    district_name: rows[0].district_name,
    house_count: rows.length,
    avg_unit_price: avgUnit(rows),
    median_total_price: round(median(rows.map((h) => h.total_price))),
    is_pseudo: 0
  }))

  const rows = all
    .filter((r) => r.house_count >= min_count)
    .sort((a, b) => {
      const d = ((a[key] ?? 0) - (b[key] ?? 0)) * dir
      return d !== 0 ? d : a.id - b.id
    })

  return {
    scope,
    list: rows.slice(0, limit),
    excluded_by_min_count: all.filter((r) => r.house_count < min_count).length,
    excluded_pseudo: meta.streets.filter((s) => s.is_pseudo === 1).length,
    caliber: `仅统计 house_count >= ${min_count} 的条目`
  }
}

// ---------------------------------------------------------------------------
// 估价（算法与后端 valuation_service 逐条对齐）
// ---------------------------------------------------------------------------
export async function postValuation(req) {
  const { houses } = await load()
  const AREA_PCT = 0.2
  const AGE_DIFF = 5
  const RANGE_PCT = 0.08

  const layers = []
  if (req.street_id) layers.push(['street', (h) => h.street_id === Number(req.street_id)])
  layers.push(['district', (h) => h.district_id === Number(req.district_id)])

  let samples = []
  let level = 'none'
  for (const [name, pred] of layers) {
    const rows = houses
      .filter(pred)
      .filter((h) => Math.abs(h.area - req.area) <= req.area * AREA_PCT)
      .filter((h) => Math.abs((h.house_age ?? 0) - req.age) <= AGE_DIFF)
    if (rows.length) { samples = rows; level = name }
    const needed = name === 'street' ? 3 : 5
    if (rows.length >= needed) break
  }

  if (!samples.length) {
    return {
      est_unit_price: null, est_total_price: null, price_range: null,
      sample_count: 0, fallback_level: 'none', confidence: 'low',
      insufficient_sample: true,
      disclaimer: '本结果基于相似房源加权均价，仅供参考，不构成评估报告',
      model_version: 'wa-1.0',
      message: '同区同面积段无可用样本，无法给出参考价'
    }
  }

  let num = 0
  let den = 0
  samples.forEach((h) => {
    const areaRatio = Math.abs(h.area - req.area) / req.area
    const ageGap = Math.abs((h.house_age ?? 0) - req.age)
    const w = (1 / (1 + areaRatio)) * (1 / (1 + ageGap / 10))
    num += w * h.unit_price
    den += w
  })
  const estUnit = num / den
  const estTotal = (estUnit * req.area) / 10000
  const n = samples.length
  let confidence = 'medium'
  if (n < 5) confidence = n >= 3 ? 'medium' : 'low'

  return {
    est_unit_price: round(estUnit),
    est_total_price: round(estTotal),
    price_range: {
      low: round(estTotal * (1 - RANGE_PCT)),
      high: round(estTotal * (1 + RANGE_PCT)),
      pct: 8
    },
    sample_count: n,
    fallback_level: level,
    confidence,
    insufficient_sample: n < 3,
    disclaimer: '本结果基于相似房源加权均价，仅供参考，不构成评估报告',
    model_version: 'wa-1.0',
    caliber: '权重 = 1/(1+面积差比) × 1/(1+房龄差/10)；样本<5 强制低置信，<3 标记 insufficient_sample'
  }
}

// ---------------------------------------------------------------------------
export async function getLayoutDistribution(top = 8) {
  const { houses } = await load()
  const map = new Map()
  houses.forEach((h) => {
    const key = `${h.room}室${h.hall}厅`
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(h)
  })
  const list = [...map.entries()]
    .map(([layout, rows]) => ({
      layout,
      n: rows.length,
      avg_unit_price: avgUnit(rows),
      min_unit_price: round(Math.min(...rows.map((r) => r.unit_price))),
      max_unit_price: round(Math.max(...rows.map((r) => r.unit_price)))
    }))
    .sort((a, b) => b.n - a.n)
    .slice(0, top)

  return {
    list,
    caliber: 'house.room + hall 组合；厅=0（开间）为合法户型；n<3 的条目不参与结论'
  }
}

export async function getMetaFilters() {
  const { meta } = await load()
  return meta.filters
}

export async function getDistricts() {
  const { meta } = await load()
  return meta.districts.map((d) => ({
    district_id: d.district_id, district_name: d.district_name, house_count: d.house_count
  }))
}

export async function getStreets(districtId, includePseudo = false) {
  const { meta } = await load()
  return meta.streets
    .filter((s) => (districtId ? s.district_id === Number(districtId) : true))
    .filter((s) => (includePseudo ? true : s.is_pseudo === 0))
    .map((s) => ({
      street_id: s.street_id, district_id: s.district_id,
      street_name: s.street_name, is_pseudo: s.is_pseudo, house_count: s.house_count
    }))
}

export async function getHealth() {
  const { houses, meta } = await load()
  return {
    status: 'ok',
    db: 'static',
    version: '0.1.0-static',
    house_rows: houses.length,
    districts: meta.districts.length,
    communities: meta.kpi?.community_count ?? null,
    avg_unit_price: meta.kpi?.avg_unit_price ?? null,
    weighted_unit_price: meta.kpi?.weighted_unit_price ?? null,
    median_total_price: meta.kpi?.median_total_price ?? null,
    readonly: true,
    note: 'GitHub Pages 静态模式：全部计算在浏览器完成'
  }
}
