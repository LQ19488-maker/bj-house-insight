/**
 * 图表 option 构造函数（纯函数，无副作用）。
 *
 * 把 option 从页面组件里抽出来的原因：
 *  1. 页面只管取数与布局，图表配置集中维护；
 *  2. 每张图的口径说明与图注只写一次，避免各处口径不一致。
 */
import { THEME, baseOption, fmtNum } from '@/composables/useChart'

const PRIMARY = THEME.primary
const ACCENT = THEME.accent
const WARN = THEME.warn

/** ① 区均价横向条形（标注样本量，均值/中位双值） */
export function districtBarOption(list, { top = 10 } = {}) {
  const rows = [...list].sort((a, b) => b.avg_unit_price - a.avg_unit_price).slice(0, top)
  return baseOption({
    grid: { left: 8, right: 96, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { formatter: (v) => `${v / 10000}万` } },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((d) => d.district_name),
      axisLine: { lineStyle: { color: '#e3e8ef' } },
      axisTick: { show: false }
    },
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const d = rows[p.dataIndex]
        return `<b>${d.district_name}</b><br/>均价 ${fmtNum(d.avg_unit_price)} 元/㎡<br/>`
          + `中位单价 ${fmtNum(d.median_unit_price)} 元/㎡<br/>中位总价 ${fmtNum(d.median_total_price)} 万<br/>`
          + `样本 n = ${d.house_count}${d.insufficient_sample ? '（样本不足）' : ''}`
      }
    },
    series: [{
      type: 'bar',
      barWidth: 14,
      data: rows.map((d) => ({
        value: d.avg_unit_price,
        itemStyle: {
          color: d.insufficient_sample ? '#cbd5e1' : PRIMARY,
          opacity: 0.9,
          borderRadius: [0, 3, 3, 0]
        }
      })),
      label: {
        show: true,
        position: 'right',
        fontSize: 11,
        formatter: (p) => {
          const d = rows[p.dataIndex]
          return `${fmtNum(d.avg_unit_price)}  n=${d.house_count}`
        }
      }
    }]
  })
}

/** ② 总价/单价分布直方图 */
export function histogramOption(dist) {
  const bins = dist?.bins || []
  return baseOption({
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: bins.map((b) => fmtNum(b.low)),
      axisLabel: { fontSize: 10, interval: 0, rotate: bins.length > 12 ? 45 : 0 },
      axisTick: { show: false }
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } } },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const i = ps[0].dataIndex
        const b = bins[i]
        return `${fmtNum(b.low)} – ${fmtNum(b.high)}<br/>房源 ${b.count} 套`
      }
    },
    series: [{
      type: 'bar',
      barCategoryGap: '12%',
      data: bins.map((b) => b.count),
      itemStyle: { color: ACCENT, opacity: 0.85, borderRadius: [2, 2, 0, 0] }
    }],
    graphic: dist?.total
      ? [{
          type: 'text',
          right: 8,
          top: 0,
          style: {
            text: `n = ${fmtNum(dist.total)}　中位 ${fmtNum(dist.stats?.median)}`,
            fontSize: 11,
            fill: '#6b7280'
          }
        }]
      : []
  })
}

/** ③ 面积-总价散点 + 回归线 */
export function scatterOption(scatter) {
  const pts = scatter?.points || []
  const reg = scatter?.regression
  const xs = pts.map((p) => p.x)
  const xMax = xs.length ? Math.max(...xs) : 0
  const lineData = reg ? [[0, reg.intercept], [xMax, reg.slope * xMax + reg.intercept]] : []

  return baseOption({
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      name: '面积 ㎡',
      nameTextStyle: { fontSize: 11, color: '#9ca3af' },
      splitLine: { lineStyle: { color: '#eef1f6' } }
    },
    yAxis: {
      type: 'value',
      name: '总价 万元',
      nameTextStyle: { fontSize: 11, color: '#9ca3af' },
      splitLine: { lineStyle: { color: '#eef1f6' } }
    },
    tooltip: {
      trigger: 'item',
      formatter: (p) => (p.seriesType === 'scatter'
        ? `面积 ${fmtNum(p.value[0])} ㎡<br/>总价 ${fmtNum(p.value[1])} 万${p.data?.outlier ? '<br/><span style="color:#b45309">已标记极值</span>' : ''}`
        : '回归线')
    },
    series: [
      {
        type: 'scatter',
        symbolSize: 5,
        data: pts.map((p) => ({
          value: [p.x, p.y],
          outlier: p.is_outlier === 1,
          itemStyle: {
            color: p.is_outlier === 1 ? WARN : PRIMARY,
            opacity: p.is_outlier === 1 ? 0.9 : 0.35
          }
        }))
      },
      {
        type: 'line',
        showSymbol: false,
        silent: true,
        lineStyle: { color: WARN, type: 'dashed', width: 1.6 },
        data: lineData
      }
    ],
    graphic: scatter?.pearson_r != null
      ? [{
          type: 'text',
          right: 10,
          top: 0,
          style: {
            text: `r = ${scatter.pearson_r}　n = ${fmtNum(scatter.n)}`,
            fontSize: 11,
            fill: WARN,
            fontWeight: 600
          }
        }]
      : []
  })
}

/** ④ 房龄-单价（单线 / 多线共用） */
export function ageLineOption(trend, { multi = null } = {}) {
  if (multi) {
    const buckets = multi.buckets || []
    return baseOption({
      grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 8, textStyle: { fontSize: 10 } },
      xAxis: {
        type: 'category',
        data: buckets,
        axisTick: { show: false },
        axisLabel: { fontSize: 10 }
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#eef1f6' } },
        axisLabel: { formatter: (v) => `${(v / 10000).toFixed(1)}万` }
      },
      tooltip: { trigger: 'axis' },
      series: (multi.series || []).map((s) => {
        const map = new Map(s.points.map((p) => [p.bucket, p]))
        return {
          name: s.district_name,
          type: 'line',
          symbolSize: 5,
          connectNulls: false,
          data: buckets.map((b) => (map.has(b) ? map.get(b).avg_unit_price : null)),
          lineStyle: { width: 2 }
        }
      })
    })
  }

  const buckets = trend?.buckets || []
  return baseOption({
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: buckets.map((b) => b.bucket),
      axisTick: { show: false },
      axisLabel: { fontSize: 10 }
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { formatter: (v) => `${(v / 10000).toFixed(1)}万` }
    },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const b = buckets[ps[0].dataIndex]
        return `房龄 ${b.bucket} 年<br/>均价 ${fmtNum(b.avg_unit_price)} 元/㎡<br/>n = ${b.n}`
      }
    },
    series: [{
      type: 'line',
      smooth: true,
      symbolSize: 6,
      itemStyle: { color: ACCENT },
      areaStyle: { opacity: 0.12 },
      data: buckets.map((b) => b.avg_unit_price),
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { type: 'dashed', color: '#94a3b8' },
        label: { fontSize: 10, color: '#94a3b8' },
        data: [{ type: 'average', name: '均值' }]
      }
    }],
    graphic: trend?.pearson_r != null
      ? [{
          type: 'text',
          right: 10,
          top: 0,
          style: {
            text: `r = ${trend.pearson_r}`,
            fontSize: 11,
            fill: WARN,
            fontWeight: 600
          }
        }]
      : []
  })
}

/** ⑤ 溢价：全市分组 vs 同区控制 */
export function premiumBarOption(premium, { mode = 'overall' } = {}) {
  if (mode === 'district' && premium?.by_district?.length) {
    const rows = premium.by_district
      .filter((d) => d.group === (premium.groups.find((g) => g.group !== premium.base_group)?.group))
      .sort((a, b) => b.premium_pct - a.premium_pct)
    const overall = premium.groups.find((g) => g.group !== premium.base_group)?.premium_pct
    return baseOption({
      grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: rows.map((d) => d.district_name),
        axisLabel: { fontSize: 10, interval: 0, rotate: rows.length > 8 ? 40 : 0 },
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        name: '溢价 %',
        nameTextStyle: { fontSize: 11, color: '#9ca3af' },
        splitLine: { lineStyle: { color: '#eef1f6' } }
      },
      tooltip: {
        trigger: 'axis',
        formatter: (ps) => {
          const d = rows[ps[0].dataIndex]
          return `<b>${d.district_name}</b><br/>${d.group} 溢价 ${d.premium_pct}%<br/>`
            + `基准 ${fmtNum(d.base_avg)}（n=${d.n_base}）<br/>`
            + `目标 ${fmtNum(d.target_avg)}（n=${d.n_target}）`
        }
      },
      series: [{
        type: 'bar',
        barWidth: '55%',
        data: rows.map((d) => ({
          value: d.premium_pct,
          itemStyle: {
            color: d.premium_pct >= 0 ? ACCENT : WARN,
            opacity: d.insufficient_sample ? 0.35 : 0.9,
            borderRadius: [3, 3, 0, 0]
          }
        })),
        markLine: overall != null
          ? {
              silent: true,
              symbol: 'none',
              data: [{ yAxis: overall, name: '全市' }],
              lineStyle: { color: PRIMARY, type: 'dashed' },
              label: { formatter: `全市 ${overall}%`, fontSize: 10, color: PRIMARY }
            }
          : undefined
      }]
    })
  }

  const groups = premium?.groups || []
  return baseOption({
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: groups.map((g) => g.group),
      axisLabel: { fontSize: 11, interval: 0 },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      name: '均价 元/㎡',
      nameTextStyle: { fontSize: 11, color: '#9ca3af' },
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { formatter: (v) => `${(v / 10000).toFixed(0)}万` }
    },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const g = groups[ps[0].dataIndex]
        return `<b>${g.group}</b><br/>均价 ${fmtNum(g.avg_unit_price)} 元/㎡<br/>`
          + `溢价 ${g.premium_pct ?? '—'}%（基准：${premium.base_group}）<br/>`
          + `n = ${g.n}${g.insufficient_sample ? '（样本不足，不参与结论）' : ''}`
      }
    },
    series: [{
      type: 'bar',
      barWidth: '50%',
      data: groups.map((g) => ({
        value: g.avg_unit_price,
        itemStyle: {
          color: g.group === premium.base_group ? '#94a3b8' : ACCENT,
          opacity: g.insufficient_sample ? 0.35 : 0.9,
          borderRadius: [3, 3, 0, 0]
        }
      })),
      label: {
        show: true,
        position: 'top',
        fontSize: 10,
        formatter: (p) => {
          const g = groups[p.dataIndex]
          return g.group === premium.base_group ? '基准' : `${g.premium_pct > 0 ? '+' : ''}${g.premium_pct}%`
        }
      }
    }]
  })
}

/** ⑥ 构成环形图（户型 / 朝向） */
export function donutOption(items, { nameKey = 'name', valueKey = 'n', top = 8 } = {}) {
  const sorted = [...items].sort((a, b) => b[valueKey] - a[valueKey])
  const head = sorted.slice(0, top)
  const rest = sorted.slice(top)
  const data = head.map((d) => ({ name: String(d[nameKey]), value: d[valueKey] }))
  if (rest.length) {
    data.push({ name: `其他 ${rest.length} 项`, value: rest.reduce((a, b) => a + b[valueKey], 0) })
  }
  const total = data.reduce((a, b) => a + b.value, 0)
  return baseOption({
    tooltip: {
      trigger: 'item',
      formatter: (p) => `${p.name}<br/>${fmtNum(p.value)} 条（${((p.value / total) * 100).toFixed(1)}%）`
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 0,
      top: 'center',
      itemWidth: 9,
      itemHeight: 9,
      textStyle: { fontSize: 10 }
    },
    series: [{
      type: 'pie',
      radius: ['48%', '72%'],
      center: ['34%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#fff', borderWidth: 1 },
      label: { show: false },
      data
    }]
  })
}

/** ⑦ 楼层 / 朝向对比（横向条形） */
export function groupBarOption(items, { labelKey, valueKey = 'avg_unit_price', nKey = 'n' } = {}) {
  const rows = [...items].sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0))
  return baseOption({
    grid: { left: 8, right: 80, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { formatter: (v) => `${(v / 10000).toFixed(1)}万` }
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((d) => d[labelKey]),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e3e8ef' } }
    },
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const d = rows[p.dataIndex]
        return `<b>${d[labelKey]}</b><br/>均价 ${fmtNum(d[valueKey])} 元/㎡<br/>`
          + `n = ${d[nKey]}${d.insufficient_sample ? '（样本不足）' : ''}`
      }
    },
    series: [{
      type: 'bar',
      barWidth: 12,
      data: rows.map((d) => ({
        value: d[valueKey],
        itemStyle: {
          color: d.insufficient_sample ? '#cbd5e1' : THEME.purple,
          opacity: 0.88,
          borderRadius: [0, 3, 3, 0]
        }
      })),
      label: {
        show: true,
        position: 'right',
        fontSize: 10,
        formatter: (p) => `n=${rows[p.dataIndex][nKey]}`
      }
    }]
  })
}

/** ⑧ 对比雷达 */
export function radarOption(radar, names = []) {
  const dims = radar?.dimensions || []
  const series = radar?.series || []
  return baseOption({
    tooltip: { trigger: 'item' },
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 8,
      textStyle: { fontSize: 10 }
    },
    radar: {
      center: ['50%', '46%'],
      radius: '62%',
      indicator: dims.map((d) => ({ name: d, max: 100 })),
      axisName: { fontSize: 10, color: '#6b7280' },
      splitLine: { lineStyle: { color: '#e3e8ef' } },
      splitArea: { areaStyle: { color: ['#fff', '#fafbfd'] } },
      axisLine: { lineStyle: { color: '#e3e8ef' } }
    },
    series: [{
      type: 'radar',
      symbolSize: 4,
      data: series.map((s, i) => ({
        name: names[i] || `房源 ${s.house_id}`,
        value: s.scores,
        areaStyle: { opacity: 0.12 },
        lineStyle: { width: 2 }
      }))
    }]
  })
}

/** ⑨ 单价分位标尺（本房 vs 同区 P25/P50/P75） */
export function quantileOption(detail) {
  const q = detail?.district_quantiles || {}
  const unit = detail?.unit_price
  const p25 = q.p25 ?? 0
  const p50 = q.p50 ?? 0
  const p75 = q.p75 ?? 0
  const lo = Math.min(p25, unit ?? p25) * 0.92
  const hi = Math.max(p75, unit ?? p75) * 1.08

  return baseOption({
    grid: { left: 16, right: 16, top: 40, bottom: 24, containLabel: true },
    xAxis: {
      type: 'value',
      min: Math.round(lo),
      max: Math.round(hi),
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { formatter: (v) => `${(v / 10000).toFixed(1)}万` }
    },
    yAxis: { type: 'category', data: ['本区单价'], show: false },
    tooltip: {
      trigger: 'item',
      formatter: (p) => (p.seriesType === 'scatter'
        ? `本房单价 ${fmtNum(unit)} 元/㎡<br/>处于本区第 ${detail.district_percentile} 百分位`
        : `${p.name}：${fmtNum(p.value)} 元/㎡`)
    },
    series: [
      {
        name: 'P25',
        type: 'bar',
        stack: 'range',
        silent: true,
        itemStyle: { color: 'transparent' },
        data: [p25]
      },
      {
        name: 'P25–P75',
        type: 'bar',
        stack: 'range',
        barWidth: 22,
        itemStyle: { color: PRIMARY, opacity: 0.28, borderRadius: 4 },
        data: [Math.max(0, p75 - p25)],
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ xAxis: p50, name: '中位' }],
          lineStyle: { color: ACCENT, width: 2 },
          label: { formatter: `中位 ${fmtNum(p50)}`, fontSize: 10, color: ACCENT }
        }
      },
      {
        name: '本房',
        type: 'scatter',
        symbolSize: 15,
        itemStyle: { color: WARN },
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          color: WARN,
          fontWeight: 600,
          formatter: () => `本房 ${fmtNum(unit)}`
        },
        data: [[unit, 0]]
      }
    ]
  })
}
