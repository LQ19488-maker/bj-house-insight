import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const KEY = 'bjhi_compare_ids'
const MAX = 4

/** 对比篮：跨路由存活（详情页加入 → 对比页读取），最多 4 条 */
export const useCompareStore = defineStore('compare', () => {
  const ids = ref(load())

  const count = computed(() => ids.value.length)
  const full = computed(() => ids.value.length >= MAX)

  function load() {
    try {
      const raw = sessionStorage.getItem(KEY)
      const arr = raw ? JSON.parse(raw) : []
      return Array.isArray(arr) ? arr.slice(0, MAX).map(Number) : []
    } catch {
      return []
    }
  }

  function persist() {
    try { sessionStorage.setItem(KEY, JSON.stringify(ids.value)) } catch { /* 忽略 */ }
  }

  function add(id) {
    const n = Number(id)
    if (ids.value.includes(n)) return { added: false, reason: 'already' }
    if (ids.value.length >= MAX) return { added: false, reason: 'full' }
    ids.value = [...ids.value, n]
    persist()
    return { added: true }
  }

  function remove(id) {
    ids.value = ids.value.filter((x) => x !== Number(id))
    persist()
  }

  function toggle(id) {
    return ids.value.includes(Number(id)) ? (remove(id), { added: false }) : add(id)
  }

  function clear() {
    ids.value = []
    persist()
  }

  return { ids, count, full, add, remove, toggle, clear, MAX }
})
