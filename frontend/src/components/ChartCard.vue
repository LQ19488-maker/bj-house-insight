<template>
  <div class="chart-card">
    <div class="head">
      <div>
        <h3>{{ title }}</h3>
        <div v-if="tip" class="tip">{{ tip }}</div>
      </div>
      <div class="actions">
        <el-tooltip v-if="caliber" :content="caliber" placement="left" effect="light">
          <span class="caliber-btn">口径</span>
        </el-tooltip>
        <button v-if="option && !loading && !error" class="export-btn" @click="exportPng">
          导出 PNG
        </button>
      </div>
    </div>

    <div class="body" :style="{ height: height + 'px' }">
      <el-skeleton v-if="loading" :rows="4" animated />
      <el-empty v-else-if="error" :description="error">
        <el-button v-if="retry" size="small" @click="retry">重试</el-button>
      </el-empty>
      <el-empty v-else-if="empty" :description="emptyText" />
      <div v-else ref="el" class="canvas" />
    </div>

    <div v-if="caliber && !loading && !error && !empty" class="foot">{{ caliber }}</div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useChart } from '@/composables/useChart'

const props = defineProps({
  title: { type: String, required: true },
  tip: { type: String, default: '' },
  caliber: { type: String, default: '' },
  option: { type: Object, default: null },
  height: { type: Number, default: 300 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  empty: { type: Boolean, default: false },
  emptyText: { type: String, default: '该条件下暂无数据' },
  retry: { type: Function, default: null }
})

const el = ref(null)
const { setOption, exportPng: exportRaw } = useChart(el)

/**
 * 数据到位后再画图。
 * 必须 await nextTick()：容器 div 是 v-else 分支，只有 loading 变 false 之后
 * 才会被渲染出来，等一个 tick 才能拿到真实 DOM 并初始化 ECharts。
 */
async function apply() {
  if (!props.option || props.loading || props.error || props.empty) return
  await nextTick()
  setOption(props.option)
}

onMounted(apply)
watch(() => props.option, apply, { deep: false })
watch(() => [props.loading, props.error, props.empty], apply)

function exportPng() {
  exportRaw(props.title)
}
</script>

<style scoped>
.chart-card {
  background: #fff;
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  padding: 16px;
  display: flex;
  flex-direction: column;
}
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
h3 { font-size: 14px; margin: 0 0 2px; }
.tip { font-size: 11px; color: var(--c-muted); margin-bottom: 8px; }
.actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.caliber-btn {
  font-size: 11px;
  color: var(--c-primary);
  border: 1px solid var(--c-line);
  border-radius: 10px;
  padding: 1px 8px;
  cursor: help;
}
.export-btn {
  font-size: 11px;
  color: var(--c-muted);
  background: #fff;
  border: 1px solid var(--c-line);
  border-radius: 10px;
  padding: 2px 10px;
  cursor: pointer;
}
.export-btn:hover { color: var(--c-primary); border-color: var(--c-primary); }
/**
 * 注意：这里**不能**写 flex: 1。
 * 外层 .chart-card 高度是自适应的，flex:1 会让 .body 的可用空间算成 0，
 * 结果 ECharts 初始化时量到的容器高度是 0，画出来的 SVG 高度也是 0（图表空白）。
 * 高度一律由模板上的 :style="{ height: height + 'px' }" 决定。
 */
.body { display: flex; align-items: center; justify-content: center; overflow: hidden; }
.body :deep(.el-skeleton) { width: 100%; align-self: flex-start; }
.canvas { width: 100%; height: 100%; }
.foot {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 8px;
  border-top: 1px dashed var(--c-line);
  padding-top: 6px;
}
</style>
