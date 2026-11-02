/**
 * HTTP 数据源：调用后端 /api/v1/*。
 *
 * 用 fetch 而不是 axios：项目只需要"注入 token + 解包统一响应体 + 错误提示"，
 * 自己写 40 行即可，少一个依赖。
 */

const BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const TOKEN_KEY = 'bjhi_token'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
}

export function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* 隐私模式下 localStorage 可能不可用 */ }
}

class ApiError extends Error {
  constructor(code, message, httpStatus) {
    super(message)
    this.code = code
    this.httpStatus = httpStatus
  }
}

function qs(params = {}) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    if (Array.isArray(v)) {
      if (v.length) sp.append(k, v.join(','))
      return
    }
    sp.append(k, String(v))
  })
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request(path, { method = 'GET', params, body } = {}) {
  const url = BASE + path + qs(params)
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 15000)
  let resp
  try {
    resp = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal
    })
  } catch (e) {
    throw new ApiError(5000, e.name === 'AbortError' ? '请求超时（15 秒）' : '网络异常，请检查后端是否已启动', 0)
  } finally {
    clearTimeout(timer)
  }

  let payload
  try {
    payload = await resp.json()
  } catch {
    throw new ApiError(5000, `响应不是合法 JSON（HTTP ${resp.status}）`, resp.status)
  }

  if (payload.code !== 0) {
    throw new ApiError(payload.code, payload.message || '请求失败', resp.status)
  }
  return payload.data
}

// ---------------- 元数据 ----------------
export const getMetaFilters = () => request('/meta/filters')
export const getDistricts = () => request('/meta/districts').then((d) => d.list)
export const getStreets = (districtId, includePseudo = false) =>
  request('/meta/streets', { params: { district_id: districtId, include_pseudo: includePseudo } })
    .then((d) => d.list)

// ---------------- 房源 ----------------
export const getHouses = (params) => request('/houses', { params })
export const getHouse = (id) => request(`/houses/${id}`)
export const getSimilar = (id, limit = 5) =>
  request(`/houses/${id}/similar`, { params: { limit } })
export const getCompare = (ids) =>
  request('/houses/compare', { params: { ids: ids.join(',') } })

// ---------------- 分析 ----------------
export const getDistrictSummary = () => request('/analytics/district-summary').then((d) => d.list)
export const getPriceDistribution = (params) =>
  request('/analytics/price-distribution', { params })
export const getScatter = (params) => request('/analytics/area-price-scatter', { params })
export const getAgeTrend = (params = {}) => request('/analytics/age-price-trend', { params })
export const getAgeByDistrict = (topN = 6) =>
  request('/analytics/age-price-by-district', { params: { top_n: topN } })
export const getPremium = (params) => request('/analytics/premium', { params })
export const getFloorOrientation = (metric = 'both') =>
  request('/analytics/floor-orientation', { params: { metric } })
export const getLayoutDistribution = (top = 8) =>
  request('/analytics/layout-distribution', { params: { top } })
export const getValueAnomaly = (params) => request('/analytics/value-anomaly', { params })

// ---------------- 小区 / 排行 ----------------
export const getCommunity = (id) => request(`/communities/${id}`)
export const getRankings = (params) => request('/rankings', { params })

// ---------------- 估价 / 健康 ----------------
export const postValuation = (body) => request('/valuation', { method: 'POST', body })
export const getHealth = () => request('/health')

// ---------------- 认证（仅接口模式）----------------
export const postLogin = (body) => request('/auth/login', { method: 'POST', body })
export const getMe = () => request('/auth/me')

// ---------------- 管理（仅接口模式）----------------
export const getBatches = (params) => request('/admin/batches', { params })
export const getBatchReport = (id) => request(`/admin/batches/${id}/report`)
export const getLogs = (params) => request('/admin/logs', { params })

/** 导入：multipart 不能用 JSON 封装，单写一个函数 */
export async function postImport(file, dryRun = false) {
  const form = new FormData()
  form.append('file', file)
  form.append('dry_run', dryRun ? 'true' : 'false')

  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(`${BASE}/admin/import`, { method: 'POST', headers, body: form })
  const payload = await resp.json()
  if (payload.code !== 0) throw new ApiError(payload.code, payload.message, resp.status)
  return payload.data
}
