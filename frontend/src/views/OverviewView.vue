<template>
  <div>
    <PageHeader
      title="市场概览"
      sub="2024-08 挂牌快照 · 2890 条"
      caliber="口径：均价为算术均值；中位数为线性插值中位数；极值行只标记不删除"
    />

    <div class="grid g4">
      <StatCard
        label="在售房源数"
        :value="kpi.house_count"
        field="house 表全量行数"
        desc="清洗后 100% 入库，拒收 0 行"
      />
      <StatCard
        label="全市均价"
        :value="kpi.avg_unit_price"
        unit="元/㎡"
        field="AVG(house.unit_price)"
        :desc="`面积加权为 ${kpi.weighted} 元/㎡`"
      />
      <StatCard
        label="中位总价"
        :value="kpi.median_total_price"
        unit="万元"
        field="MEDIAN(house.total_price)"
        desc="线性插值中位数"
      />
      <StatCard
        label="覆盖小区"
        :value="kpi.community_count"
        field="COUNT(DISTINCT (district, name))"
        desc="名称去重为 1864；绿地中央广场跨区"
      />
    </div>

    <div class="grid g2 mt4">
      <ChartCard
        title="区均价 Top 10"
        tip="条形=算术均价，标签含样本量 n；平谷仅 1 套、延庆 2 套"
        caliber="均价=AVG(unit_price)；中位数为插值法；n<3 的区不参与排行结论"
        :option="districtOption"
        :loading="loading"
        :error="error"
        :height="330"
        :retry="load"
      />
      <ChartCard
        title="总价分布"
        tip="分位分桶：等宽分桶会把 60% 样本挤进第一桶"
        :caliber="dist?.caliber"
        :option="histOption"
        :loading="loading"
        :error="error"
        :height="330"
        :retry="load"
      />
    </div>

    <div class="card mt4">
      <div class="flex-between">
        <h3 style="font-size: 14px; margin: 0">在售套数最多的小区</h3>
        <RouterLink to="/search"><el-button type="primary" size="small">进入房源检索 →</el-button></RouterLink>
      </div>
      <div class="note">
        67.4% 的小区仅有 1 套在售，因此小区不是可统计粒度——这里只列"在售最多"的，
        而非"最贵"的。小区画像只做"在同街道中的位置"。
      </div>
      <div class="grid g3 mt4">
        <div v-for="c in topCommunities" :key="c.community_id" class="comm">
          <div class="comm-name">{{ c.community_name }}</div>
          <div class="small muted">{{ c.district_name }} · {{ c.street_name }}</div>
          <div class="flex gap4 mt2 small">
            <span>在售 <b class="num">{{ c.house_count }}</b></span>
            <span>均价 <b class="num">{{ fmtNum(c.avg_unit_price) }}</b></span>
            <span>中位总价 <b class="num">{{ fmtNum(c.median_total_price) }}</b> 万</span>
          </div>
          <RouterLink :to="`/communities/${c.community_id}`" class="mt2" style="display:inline-block">
            <el-button size="small" text type="primary">查看画像</el-button>
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import ChartCard from '@/components/ChartCard.vue'
import { districtBarOption, histogramOption } from '@/charts/options'
import { fmtNum } from '@/composables/useChart'
import {
  getDistrictSummary, getDistricts, getHealth, getPriceDistribution, getRankings
} from '@/api'

const loading = ref(true)
const error = ref('')
const districts = ref([])
const dist = ref(null)
const topCommunities = ref([])
const health = ref({})

const kpi = computed(() => ({
  house_count: fmtNum(health.value.house_rows ?? 0),
  avg_unit_price: fmtNum(health.value.avg_unit_price ?? 0),
  weighted: fmtNum(health.value.weighted_unit_price ?? 0),
  median_total_price: fmtNum(health.value.median_total_price ?? 0),
  community_count: fmtNum(health.value.communities ?? 0)
}))

const districtOption = computed(() => (districts.value.length
  ? districtBarOption(districts.value)
  : null))
const histOption = computed(() => (dist.value?.bins?.length ? histogramOption(dist.value) : null))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [summary, d, h] = await Promise.all([
      getDistrictSummary(),
      getPriceDistribution({ metric: 'total', bins: 10, binning: 'quantile' }),
      getHealth().catch(() => ({}))
    ])
    districts.value = summary
    dist.value = d
    health.value = h

    const ranking = await getRankings({
      scope: 'community', by: 'house_count', order: 'desc', min_count: 1, limit: 6
    })
    topCommunities.value = ranking.list.map((c) => ({
      ...c,
      district_name: c.district_name || '',
      street_name: c.street_name || ''
    }))
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.comm {
  border: 1px solid var(--c-line);
  border-radius: var(--radius-sm);
  padding: 12px;
}
.comm-name { font-weight: 600; }
</style>
