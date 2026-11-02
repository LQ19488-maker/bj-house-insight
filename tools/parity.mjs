/**
 * 双模式一致性检查：静态模式（GitHub Pages）与接口模式（本地后端）
 * 对同一组请求必须算出同样的数字。
 *
 * 为什么需要它：页面组件共用一套，但数据层有两份实现。
 * 两份实现一旦口径分叉，用户在 Pages 上看到的数字和本机不同，
 * 而这种差异在浏览器里极难发现 —— 必须用脚本自动比对。
 *
 * 由 tools/check_parity.py 启动后端后调用本文件。
 */
import { pathToFileURL } from 'node:url'
import path from 'node:path'

const ROOT = process.argv[2]
const API = process.argv[3] || 'http://127.0.0.1:18082'
const DATA_DIR = path.join(ROOT, 'frontend', 'public', 'data')

// 把静态源的 fetch 指到本地 JSON 文件；其余请求照常走 HTTP
const realFetch = globalThis.fetch
globalThis.fetch = async (url, opts) => {
  const u = String(url)
  if (u.includes('/data/')) {
    const name = u.split('/data/').pop().split('?')[0]
    const fs = await import('node:fs/promises')
    try {
      const text = await fs.readFile(path.join(DATA_DIR, name), 'utf8')
      return new Response(text, { status: 200, headers: { 'content-type': 'application/json' } })
    } catch (e) {
      return new Response('not found', { status: 404 })
    }
  }
  return realFetch(url, opts)
}

const staticSrc = await import(pathToFileURL(path.join(ROOT, 'frontend', 'src', 'api', 'staticSource.js')).href)

async function api(pathname, params = {}) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.append(k, String(v))
  })
  const url = `${API}${pathname}${sp.toString() ? `?${sp}` : ''}`
  const resp = await realFetch(url)
  const payload = await resp.json()
  if (payload.code !== 0) throw new Error(`${pathname} → code ${payload.code}: ${payload.message}`)
  return payload.data
}

async function apiPost(pathname, body) {
  const resp = await realFetch(`${API}${pathname}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  const payload = await resp.json()
  if (payload.code !== 0) throw new Error(`${pathname} → code ${payload.code}: ${payload.message}`)
  return payload.data
}

// 文本型/环境型字段不参与比对（口径文案允许措辞不同，数值必须一致）
const IGNORE_KEYS = new Set([
  'took_ms', 'caliber', 'why', 'note', 'message', 'db', 'version', 'status',
  'readonly', 'model_version', 'disclaimer'
])

function diff(a, b, pathStr = '', out = []) {
  if (a === b) return out
  const bothNum = typeof a === 'number' && typeof b === 'number'
  if (bothNum) {
    const tol = Math.max(0.02, Math.abs(a) * 0.002)
    if (Math.abs(a - b) > tol) out.push(`${pathStr}: api=${a} static=${b}`)
    return out
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) {
      out.push(`${pathStr}.length: api=${a.length} static=${b.length}`)
      return out
    }
    a.forEach((v, i) => diff(v, b[i], `${pathStr}[${i}]`, out))
    return out
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a).filter((k) => !IGNORE_KEYS.has(k))
    const kb = Object.keys(b).filter((k) => !IGNORE_KEYS.has(k))
    const missing = ka.filter((k) => !kb.includes(k))
    const extra = kb.filter((k) => !ka.includes(k))
    if (missing.length) out.push(`${pathStr}.missing_in_static: ${missing.join(',')}`)
    if (extra.length) out.push(`${pathStr}.extra_in_static: ${extra.join(',')}`)
    ka.filter((k) => kb.includes(k)).forEach((k) => diff(a[k], b[k], `${pathStr}.${k}`, out))
    return out
  }
  out.push(`${pathStr}: api=${JSON.stringify(a)} static=${JSON.stringify(b)}`)
  return out
}

const CASES = [
  ['列表查询（默认）',
    () => api('/api/v1/houses', { page: 1, page_size: 20 }),
    () => staticSrc.getHouses({ page: 1, page_size: 20 })],

  ['列表查询（多条件）',
    () => api('/api/v1/houses', {
      district_id: 11, near_subway: 1, price_min: 400, price_max: 600,
      sort: 'unit_price', order: 'desc', page: 2, page_size: 20
    }),
    () => staticSrc.getHouses({
      district_id: 11, near_subway: 1, price_min: 400, price_max: 600,
      sort: 'unit_price', order: 'desc', page: 2, page_size: 20
    })],

  ['列表查询（朝向多选）',
    () => api('/api/v1/houses', { direction: '南,北', page_size: 50 }),
    () => staticSrc.getHouses({ direction: ['南', '北'], page_size: 50 })],

  ['房源详情',
    () => api('/api/v1/houses/1'),
    () => staticSrc.getHouse(1)],

  ['相似房源',
    () => api('/api/v1/houses/1/similar', { limit: 5 }),
    () => staticSrc.getSimilar(1, 5)],

  ['房源对比',
    () => api('/api/v1/houses/compare', { ids: '1,2,3' }),
    () => staticSrc.getCompare([1, 2, 3])],

  ['区级汇总',
    () => api('/api/v1/analytics/district-summary').then((d) => d.list),
    () => staticSrc.getDistrictSummary()],

  ['价格分布',
    () => api('/api/v1/analytics/price-distribution', { metric: 'total', bins: 10 }),
    () => staticSrc.getPriceDistribution({ metric: 'total', bins: 10 })],

  ['面积总价散点',
    () => api('/api/v1/analytics/area-price-scatter', { limit: 500 }),
    () => staticSrc.getScatter({ limit: 500 })],

  ['房龄趋势',
    () => api('/api/v1/analytics/age-price-trend'),
    () => staticSrc.getAgeTrend()],

  ['分区房龄对照',
    () => api('/api/v1/analytics/age-price-by-district', { top_n: 6 }),
    () => staticSrc.getAgeByDistrict(6)],

  ['溢价（同区控制）',
    () => api('/api/v1/analytics/premium', { metric: 'metro', control: 'district' }),
    () => staticSrc.getPremium({ metric: 'metro', control: 'district' })],

  ['楼层与朝向',
    () => api('/api/v1/analytics/floor-orientation', { metric: 'both' }),
    () => staticSrc.getFloorOrientation('both')],

  ['户型构成',
    () => api('/api/v1/analytics/layout-distribution', { top: 8 }),
    () => staticSrc.getLayoutDistribution(8)],

  ['性价比异常',
    () => api('/api/v1/analytics/value-anomaly', { district_id: 11, area_band: '60-90' }),
    () => staticSrc.getValueAnomaly({ district_id: 11, area_band: '60-90' })],

  ['小区画像',
    () => api('/api/v1/communities/1'),
    () => staticSrc.getCommunity(1)],

  ['街道排行',
    () => api('/api/v1/rankings', { scope: 'street', min_count: 4, limit: 20 }),
    () => staticSrc.getRankings({ scope: 'street', min_count: 4, limit: 20 })],

  ['小区排行',
    () => api('/api/v1/rankings', { scope: 'community', by: 'house_count', min_count: 2, limit: 20 }),
    () => staticSrc.getRankings({ scope: 'community', by: 'house_count', min_count: 2, limit: 20 })],

  ['估价',
    () => apiPost('/api/v1/valuation', {
      district_id: 11, street_id: null, area: 80, room: 2, hall: 1,
      age: 10, decoration: '精装', floor_level: '中', near_subway: 1
    }),
    () => staticSrc.postValuation({
      district_id: 11, street_id: null, area: 80, room: 2, hall: 1,
      age: 10, decoration: '精装', floor_level: '中', near_subway: 1
    })],

  ['元数据-区',
    () => api('/api/v1/meta/districts').then((d) => d.list),
    () => staticSrc.getDistricts()],

  ['元数据-街道',
    () => api('/api/v1/meta/streets', { district_id: 1 }).then((d) => d.list),
    () => staticSrc.getStreets(1)]
]

const results = []
for (const [name, apiFn, staticFn] of CASES) {
  try {
    const [a, b] = await Promise.all([apiFn(), staticFn()])
    const d = diff(a, b, name)
    results.push({ name, ok: d.length === 0, diffs: d.slice(0, 6) })
  } catch (e) {
    results.push({ name, ok: false, diffs: [`EXCEPTION: ${e.message}`] })
  }
}

const failed = results.filter((r) => !r.ok)
console.log(JSON.stringify({ total: results.length, failed: failed.length, results }, null, 0))
process.exit(failed.length ? 1 : 0)
