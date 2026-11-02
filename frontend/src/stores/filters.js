import { defineStore } from 'pinia'
import { reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

/**
 * 检索条件 store。
 *
 * 进 store 的判据：跨路由存活 或 多处写入 或 需要同步到 URL。
 * 抽屉开关、分页游标这类纯页面局部状态不进 store。
 */
const DEFAULTS = () => ({
  keyword: '',
  district_id: null,
  street_id: null,
  price_min: null,
  price_max: null,
  area_min: null,
  area_max: null,
  room: null,
  hall: null,
  age_max: null,
  decoration: [],
  structure: [],
  direction: [],
  near_subway: null,
  include_outlier: true,
  sort: 'unit_price',
  order: 'asc',
  page: 1,
  page_size: 20
})

export const useFiltersStore = defineStore('filters', () => {
  const state = reactive(DEFAULTS())

  function reset() {
    Object.assign(state, DEFAULTS())
  }

  /** 把非空条件写进 URL，保证刷新不丢、链接可分享 */
  function toQuery() {
    const q = {}
    Object.entries(state).forEach(([k, v]) => {
      if (v === null || v === '' || v === undefined) return
      if (Array.isArray(v) && !v.length) return
      if (k === 'include_outlier' && v === true) return
      if (k === 'page' && v === 1) return
      q[k] = Array.isArray(v) ? v.join(',') : String(v)
    })
    return q
  }

  function fromQuery(query) {
    const next = DEFAULTS()
    Object.entries(query || {}).forEach(([k, v]) => {
      if (!(k in next)) return
      const raw = Array.isArray(v) ? v[0] : v
      if (raw === undefined || raw === '') return
      const def = next[k]
      if (Array.isArray(def)) next[k] = String(raw).split(',').filter(Boolean)
      else if (typeof def === 'number') next[k] = Number(raw)
      else if (typeof def === 'boolean') next[k] = raw !== 'false'
      else next[k] = raw
    })
    Object.assign(state, next)
  }

  return { state, reset, toQuery, fromQuery }
})

/** 在页面组件里 `useUrlSync(filters)` 即可实现双向同步 */
export function useUrlSync(store) {
  const route = useRoute()
  const router = useRouter()

  store.fromQuery(route.query)

  watch(
    () => store.state,
    () => {
      router.replace({ query: store.toQuery() })
    },
    { deep: true }
  )

  watch(
    () => route.query,
    (q) => {
      const current = JSON.stringify(store.toQuery())
      const incoming = JSON.stringify(Object.fromEntries(
        Object.entries(q).filter(([k]) => k in store.state)
      ))
      if (current !== incoming) store.fromQuery(q)
    }
  )
}
