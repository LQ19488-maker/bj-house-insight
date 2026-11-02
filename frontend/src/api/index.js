/**
 * 数据源适配器 —— 前端唯一的数据入口。
 *
 * 页面组件只 import 这里暴露的函数，不直接 fetch、不直接读 JSON。
 * 同一套页面因此能在两种形态下运行：
 *
 *   VITE_DATA_SOURCE=http   → 调后端 29+1 个接口（本地完整系统）
 *   VITE_DATA_SOURCE=static → 读 public/data/*.json 并在浏览器内存里计算
 *                             （GitHub Pages 只读站）
 *
 * 两种实现返回**完全相同的数据结构**，字段名与 docs/api-contract.md 一致。
 *
 * 注意：这里用静态 import 而非顶层 await 动态 import ——
 * 顶层 await 会要求 target 支持 ESM 顶层 await（es2022），
 * 与 Vite 默认的 es2020 target 冲突；两个数据源合计不到 20 KB，不值得为此改 target。
 */
import * as httpImpl from './httpSource.js'
import * as staticImpl from './staticSource.js'

const SOURCE = String(import.meta.env.VITE_DATA_SOURCE || 'http').toLowerCase()

export const dataSource = SOURCE
export const isStatic = SOURCE === 'static'

const impl = isStatic ? staticImpl : httpImpl

export const getMetaFilters = impl.getMetaFilters
export const getDistricts = impl.getDistricts
export const getStreets = impl.getStreets
export const getHouses = impl.getHouses
export const getHouse = impl.getHouse
export const getSimilar = impl.getSimilar
export const getCompare = impl.getCompare
export const getDistrictSummary = impl.getDistrictSummary
export const getPriceDistribution = impl.getPriceDistribution
export const getScatter = impl.getScatter
export const getAgeTrend = impl.getAgeTrend
export const getAgeByDistrict = impl.getAgeByDistrict
export const getPremium = impl.getPremium
export const getFloorOrientation = impl.getFloorOrientation
export const getLayoutDistribution = impl.getLayoutDistribution
export const getValueAnomaly = impl.getValueAnomaly
export const getCommunity = impl.getCommunity
export const getRankings = impl.getRankings
export const postValuation = impl.postValuation
export const getHealth = impl.getHealth
