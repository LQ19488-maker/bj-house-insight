<template>
  <div>
    <PageHeader
      title="房源详情"
      :sub="d ? `${d.community_name} · ${d.district_name}` : ''"
      caliber="分位口径：该房单价在同区分布中的百分位（小于该值的行数 / 同区总数）"
    />

    <el-skeleton v-if="loading" :rows="8" animated />
    <el-empty v-else-if="error" :description="error">
      <el-button size="small" @click="load">重试</el-button>
    </el-empty>

    <template v-else-if="d">
      <div class="grid g3">
        <div class="card" style="grid-column: span 2">
          <div class="flex-between">
            <div>
              <div class="field-name">house.total_price / house.unit_price</div>
              <div class="flex gap4" style="align-items: baseline">
                <span class="big num">{{ fmtNum(d.total_price) }}<span class="unit">万</span></span>
                <span class="big2 num">{{ fmtNum(d.unit_price) }}<span class="unit">元/㎡</span></span>
              </div>
            </div>
            <div class="flex gap2">
              <el-button size="small" type="primary" @click="addCompare">加入对比</el-button>
              <el-button size="small" @click="$router.push('/valuation')">相似房源估价</el-button>
              <el-button size="small" text @click="$router.back()">返回</el-button>
            </div>
          </div>

          <el-descriptions :column="2" border size="small" class="mt4">
            <el-descriptions-item label="户型">
              {{ d.room }}室{{ d.hall }}厅
              <span class="field-name">house.room / hall</span>
            </el-descriptions-item>
            <el-descriptions-item label="面积">
              <span class="num">{{ d.area }}</span> ㎡
              <span class="field-name">house.area</span>
            </el-descriptions-item>
            <el-descriptions-item label="朝向">
              {{ d.directions?.join(' ') || d.orientation_text || '—' }}
              <span class="field-name">house_orientation</span>
            </el-descriptions-item>
            <el-descriptions-item label="装修">
              {{ d.decoration }} <span class="field-name">house.decoration</span>
            </el-descriptions-item>
            <el-descriptions-item label="结构">
              {{ d.structure }} <span class="field-name">house.structure</span>
            </el-descriptions-item>
            <el-descriptions-item label="楼层">
              {{ d.floor_raw || `${d.floor_level}（共${d.floor_total}层）` }}
              <span class="field-name">floor_level / floor_total</span>
            </el-descriptions-item>
            <el-descriptions-item label="房龄">
              <span class="num">{{ d.house_age }}</span> 年
              <span class="field-name">house.house_age</span>
            </el-descriptions-item>
            <el-descriptions-item label="近地铁">
              <el-tag size="small" :type="d.near_subway ? 'success' : 'info'">
                {{ d.near_subway ? '近地铁' : '不近地铁' }}
              </el-tag>
              <span class="field-name">house.near_subway</span>
            </el-descriptions-item>
          </el-descriptions>

          <div class="grid g4 mt4">
            <StatCard label="小区在售" :value="d.community?.house_count ?? '—'" field="community.house_count" />
            <StatCard label="小区均价" :value="fmtNum(d.community?.avg_unit_price)" unit="元/㎡" field="community.avg_unit_price" />
            <StatCard label="小区中位总价" :value="fmtNum(d.community?.median_total_price)" unit="万" field="community.median_total_price" />
            <StatCard label="小区平均房龄" :value="d.community?.avg_age ?? '—'" unit="年" field="community.avg_age" />
          </div>

          <div class="flex gap2 mt4">
            <el-tag v-if="d.is_outlier" type="warning" size="small">已标记极值（不删除）</el-tag>
            <el-tag v-if="d.abnormal_layout" type="info" size="small">非常规户型（1室2厅等）</el-tag>
            <span class="field-name">source_row_no = {{ d.source_row_no }}</span>
          </div>
        </div>

        <ChartCard
          title="单价分位"
          tip="本房在同区单价分布中的位置"
          caliber="P25/P50/P75 由同区全部房源计算；标尺范围按 P25–P75 与均值自适应"
          :option="quantile"
          :height="260"
        />
      </div>

      <div class="card mt4">
        <div class="flex-between">
          <h3 style="font-size: 14px; margin: 0">相似房源</h3>
          <span class="small muted">
            降级层级：<b>{{ levelLabel }}</b>
          </span>
        </div>
        <div class="note">
          召回规则：同小区 → 同街道 → 同区 三级降级；面积 ±20%、房龄 ±5 年。
          67.4% 的小区只有 1 套在售，同小区样本经常取不到，会自动降级到同街道（中位 7 套）。
        </div>
        <el-table :data="d.similar" size="small" class="mt4" @row-click="goSimilar">
          <el-table-column prop="community_name" label="小区" min-width="140" />
          <el-table-column prop="street_name" label="街道" width="110" />
          <el-table-column label="面积" width="90" align="right">
            <template #default="{ row }"><span class="num">{{ row.area }}</span></template>
          </el-table-column>
          <el-table-column label="总价(万)" width="100" align="right">
            <template #default="{ row }"><span class="num">{{ fmtNum(row.total_price) }}</span></template>
          </el-table-column>
          <el-table-column label="单价(元/㎡)" width="110" align="right">
            <template #default="{ row }"><span class="num">{{ fmtNum(row.unit_price) }}</span></template>
          </el-table-column>
          <el-table-column label="房龄" width="70" align="right">
            <template #default="{ row }"><span class="num">{{ row.house_age }}</span></template>
          </el-table-column>
          <el-table-column label="面积差" width="90" align="right">
            <template #default="{ row }">
              <span class="num">{{ row.area_diff_pct > 0 ? '+' : '' }}{{ row.area_diff_pct }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="匹配层级" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.match_level === 'community' ? 'success' : (row.match_level === 'street' ? 'warning' : 'info')">
                {{ row.match_level }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import ChartCard from '@/components/ChartCard.vue'
import { quantileOption } from '@/charts/options'
import { fmtNum } from '@/composables/useChart'
import { useCompareStore } from '@/stores/compare'
import { getHouse } from '@/api'

const route = useRoute()
const router = useRouter()
const compare = useCompareStore()

const loading = ref(true)
const error = ref('')
const d = ref(null)

const quantile = computed(() => (d.value ? quantileOption(d.value) : null))
const levelLabel = computed(() => {
  const lv = d.value?.similar?.[0]?.match_level
  return { community: '同小区', street: '同街道', district: '同区', none: '无样本' }[lv] || '—'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    d.value = await getHouse(route.params.id)
  } catch (e) {
    error.value = e.message || '加载失败'
    d.value = null
  } finally {
    loading.value = false
  }
}

function addCompare() {
  const res = compare.add(d.value.house_id)
  if (res.added) ElMessage.success('已加入对比')
  else if (res.reason === 'already') ElMessage.info('已在对比篮中')
  else ElMessage.warning('对比篮最多 4 套')
}

function goSimilar(row) {
  router.push(`/houses/${row.house_id}`)
}

watch(() => route.params.id, load)
onMounted(load)
</script>

<style scoped>
.big { font-size: 28px; font-weight: 700; color: var(--c-primary); }
.big2 { font-size: 20px; font-weight: 600; color: var(--c-accent); }
.unit { font-size: 13px; font-weight: 500; color: var(--c-muted); margin-left: 3px; }
:deep(.el-table__row) { cursor: pointer; }
</style>
