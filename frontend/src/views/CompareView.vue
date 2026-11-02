<template>
  <div>
    <PageHeader
      title="房源对比"
      sub="最多 4 套 · 差异高亮 · 五维归一化"
      caliber="归一化范围随图返回，否则两个雷达图的形状不可比"
    />

    <div class="card flex-between">
      <div class="flex gap2 wrap">
        <el-tag v-for="id in compare.ids" :key="id" closable size="large" @close="removeOne(id)">
          房源 #{{ id }}
        </el-tag>
        <span v-if="!compare.ids.length" class="muted small">对比篮为空，去检索页点"对比"加入</span>
      </div>
      <div class="flex gap2">
        <el-button size="small" @click="$router.push('/search')">去检索</el-button>
        <el-button size="small" :disabled="!compare.ids.length" @click="compare.clear()">清空</el-button>
        <el-button size="small" type="primary" :disabled="compare.ids.length < 2" @click="load">开始对比</el-button>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="8" animated class="mt4" />
    <el-empty v-else-if="error" :description="error" class="mt4">
      <el-button size="small" @click="load">重试</el-button>
    </el-empty>
    <el-empty v-else-if="!data" description="至少选择 2 套房源才能对比" class="mt4" />

    <div v-else class="grid g3 mt4">
      <div class="card" style="grid-column: span 2">
        <h3 style="font-size: 14px; margin: 0 0 4px">属性逐行对比</h3>
        <div class="small muted">差异项整行高亮；最佳值以 ▲ 标记</div>
        <el-table :data="data.attributes" size="small" class="mt4"
                  :row-class-name="({ row }) => (row.diff ? 'diff-row' : '')">
          <el-table-column prop="label" label="属性" width="110" fixed />
          <el-table-column v-for="(n, i) in columns" :key="i" :label="n" min-width="110" align="right">
            <template #default="{ row }">
              <span class="num">{{ format(row.values[i]) }}</span>
              <span v-if="row.best_index === i" style="color: #0f766e; margin-left: 4px">▲</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <ChartCard
        title="五维雷达"
        tip="面积 / 单价 / 房龄 / 地铁 / 装修（0–100，越优分越高）"
        :caliber="data.radar.note"
        :option="radar"
        :height="340"
      />
    </div>

    <div v-if="data" class="note">
      归一化范围：面积 {{ data.radar.normalize_range['面积']?.join(' – ') }} ㎡；
      单价 {{ data.radar.normalize_range['单价']?.map(v => fmtNum(v)).join(' – ') }} 元/㎡；
      房龄 {{ data.radar.normalize_range['房龄']?.join(' – ') }} 年。
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { radarOption } from '@/charts/options'
import { fmtNum } from '@/composables/useChart'
import { useCompareStore } from '@/stores/compare'
import { getCompare } from '@/api'

const compare = useCompareStore()
const loading = ref(false)
const error = ref('')
const data = ref(null)

const columns = computed(() => (compare.ids || []).map((id) => `房源 #${id}`))
const radar = computed(() => (data.value
  ? radarOption(data.value.radar, columns.value)
  : null))

function format(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return fmtNum(v, Number.isInteger(v) ? 0 : 2)
  return v === 1 ? '是' : v === 0 ? '否' : String(v)
}

async function load() {
  if (compare.ids.length < 2) {
    data.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    data.value = await getCompare([...compare.ids])
  } catch (e) {
    error.value = e.message || '对比失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

function removeOne(id) {
  compare.remove(id)
}

watch(() => compare.ids.join(','), load, { immediate: true })
</script>

<style scoped>
:deep(.diff-row) { background: #fffdf5; }
</style>
