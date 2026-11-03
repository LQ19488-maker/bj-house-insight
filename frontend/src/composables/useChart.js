/**
 * ECharts 封装：按需注册 + SVG 渲染器 + 容器尺寸自适应 + 手动释放。
 *
 * 为什么用 SVG 而不是 Canvas：
 *  1. 矢量输出，导出 PNG / 打印都清晰；
 *  2. 静态站体积更小；
 *  3. 图表元素可被浏览器查找（便于无头测试断言）。
 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, RadarChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent,
  TitleComponent, TooltipComponent
} from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

echarts.use([
  BarChart, LineChart, PieChart, RadarChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  MarkLineComponent, DataZoomComponent, SVGRenderer
])

export const THEME = {
  primary: '#1a4d8f',
  accent: '#0f766e',
  warn: '#b45309',
  purple: '#7c3aed',
  pink: '#db2777',
  cyan: '#0891b2',
  series: ['#1a4d8f', '#0f766e', '#b45309', '#7c3aed', '#db2777', '#0891b2', '#65a30d', '#94a3b8']
}

/** 基础 grid / tooltip / 字体配置，各图表 option 复用它 */
export function baseOption(extra = {}) {
  return {
    color: THEME.series,
    textStyle: {
      fontFamily: '-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
      fontSize: 12
    },
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,.96)',
      borderColor: '#e3e8ef',
      textStyle: { color: '#1f2937', fontSize: 12 }
    },
    ...extra
  }
}

export function useChart(containerRef) {
  const chart = ref(null)
  let observer = null

  function resize() {
    chart.value?.resize()
  }

  /**
   * 惰性初始化。
   *
   * 关键：图表容器可能**在组件挂载之后才出现**（例如数据还没到时先显示骨架屏，
   * 用 v-if / v-else 把容器藏起来了）。此时 onMounted 里拿不到 DOM，
   * 如果只在挂载时 init 一次，图表就会永远是空白。
   * 所以 setOption 前都先 ensure() 一次，DOM 一出现就补上初始化。
   */
  function ensure() {
    const el = containerRef.value
    if (!el) return null
    if (!chart.value) {
      chart.value = echarts.init(el, null, { renderer: 'svg' })
      if (typeof ResizeObserver !== 'undefined' && !observer) {
        observer = new ResizeObserver(() => resize())
        observer.observe(el)
      }
    }
    return chart.value
  }

  onMounted(ensure)

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
    chart.value?.dispose()
    chart.value = null
  })

  function setOption(option, opts = { notMerge: true }) {
    const c = ensure()
    if (!c || !option) return false
    c.setOption(option, opts)
    // 容器刚显示出来时宽高可能还是 0，重新量一次，否则画布尺寸为 0
    c.resize()
    return true
  }

  function exportPng(name = 'chart') {
    if (!chart.value) return
    const url = chart.value.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
    const a = document.createElement('a')
    a.href = url
    a.download = `${name}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}.png`
    a.click()
  }

  return { chart, setOption, resize, exportPng }
}

/** 数值格式化：万元 / 元 / 千分位 */
export function fmtNum(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return Number(v).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  })
}

export { echarts }
