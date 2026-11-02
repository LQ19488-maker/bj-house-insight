<template>
  <div>
    <PageHeader
      title="市场分析看板"
      sub="价格由什么解释"
      caliber="每张单因子图都配一张「同区控制」对照图：全市口径下的属性溢价大多是区位混杂造成的"
    />

    <div class="warnbox">
      <b>核心论点：</b>全市口径下房龄与单价正相关（r≈+0.26）、塔楼比板楼贵约 16%——
      这两个反直觉结论都是<b>区位混杂</b>造成的。请看图②与图③的对比。
    </div>

    <div class="card flex gap4 wrap">
      <span class="small muted">全局筛选</span>
      <el-select v-model="districtId" placeholder="全部区" clearable size="small" style="width: 150px" @change="load">
        <el-option v-for="d in districts" :key="d.district_id" :label="d.district_name" :value="d.district_id" />
      </el-select>
      <span class="field-name">筛选变化 → 各图并发刷新（Promise.allSettled，单图失败不阻塞其余）</span>
    </div>

    <div class="grid g2 mt4">
      <ChartCard
        title="① 面积–总价散点"
        tip="house.area × house.total_price，橙色点为已标记极值"
        :caliber="scatterRes?.caliber"
        :option="scatterOpt"
        :loading="loading.scatter"
        :error="errors.scatter"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="② 房龄–单价（全市）"
        tip="单看这张图会误导：老房集中在东西城核心区"
        :caliber="ageRes?.caliber"
        :option="ageOpt"
        :loading="loading.age"
        :error="errors.age"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="③ 房龄–单价（分区对照）★"
        tip="同图多条分区折线，控制区位后的真实关系"
        :caliber="ageDistRes?.caliber"
        :option="ageDistOpt"
        :loading="loading.ageDist"
        :error="errors.ageDist"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="④ 地铁溢价（全市 vs 同区控制）"
        tip="house.near_subway；溢价率 =(组均价−基准均价)/基准均价×100"
        :caliber="premiumRes?.caliber"
        :option="metroOpt"
        :loading="loading.premium"
        :error="errors.premium"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="⑤ 地铁溢价的同区控制对照"
        tip="每个区内部单独比较近/不近地铁，虚线为全市溢价"
        caliber="按区分组后溢价率普遍低于全市口径，差额即为区位贡献"
        :option="metroDistrictOpt"
        :loading="loading.premium"
        :error="errors.premium"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="⑥ 户型构成"
        tip="house.room + hall（共 25 种，显示 Top8 + 其他）"
        caliber="厅=0 为开间，属合法户型（共 101 条）"
        :option="layoutOpt"
        :loading="loading.orientation"
        :error="errors.orientation"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="⑦ 楼层层级均价"
        tip="楼层层级 8 值；“未知”（纯数字楼层）单独成组不合并"
        :caliber="floorRes?.caliber"
        :option="floorOpt"
        :loading="loading.orientation"
        :error="errors.orientation"
        :height="300"
        :retry="load"
      />
      <ChartCard
        title="⑧ 朝向均价"
        tip="朝向经 M:N 展开后按方向聚合（4806 条关联行）"
        :caliber="orientCaliber"
        :option="orientOpt"
        :loading="loading.orientation"
        :error="errors.orientation"
        :height="300"
        :retry="load"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import {
  ageLineOption, districtBarOption, donutOption, groupBarOption,
  histogramOption, premiumBarOption, scatterOption
} from '@/charts/options'
import {
  getAgeByDistrict, getAgeTrend, getDistricts, getFloorOrientation,
  getLayoutDistribution, getPremium, getScatter
} from '@/api'

const districts = ref([])
const districtId = ref(null)

const loading = reactive({ scatter: true, age: true, ageDist: true, premium: true, orientation: true })
const errors = reactive({ scatter: '', age: '', ageDist: '', premium: '', orientation: '' })

const scatterRes = ref(null)
const ageRes = ref(null)
const ageDistRes = ref(null)
const premiumRes = ref(null)
const floorRes = ref(null)
const layoutRes = ref(null)

const scatterOpt = computed(() => (scatterRes.value ? scatterOption(scatterRes.value) : null))
const ageOpt = computed(() => (ageRes.value ? ageLineOption(ageRes.value) : null))
const ageDistOpt = computed(() => (ageDistRes.value ? ageLineOption(null, { multi: ageDistRes.value }) : null))
const metroOpt = computed(() => (premiumRes.value ? premiumBarOption(premiumRes.value) : null))
const metroDistrictOpt = computed(() => (premiumRes.value ? premiumBarOption(premiumRes.value, { mode: 'district' }) : null))
const layoutOpt = computed(() => (layoutRes.value?.list?.length
  ? donutOption(layoutRes.value.list.map((x) => ({ name: x.layout, n: x.n })), { nameKey: 'name' })
  : null))
const floorOpt = computed(() => (floorRes.value?.floor
  ? groupBarOption(floorRes.value.floor, { labelKey: 'level' })
  : null))
const orientOpt = computed(() => (floorRes.value?.orientation
  ? groupBarOption(floorRes.value.orientation, { labelKey: 'direction' })
  : null))
const orientCaliber = computed(() => {
  const sp = floorRes.value?.orientation_spread
  if (!sp) return '朝向经 M:N 展开后按方向聚合'
  return `朝南 vs 朝北溢价 ${sp.south_minus_north_pct > 0 ? '+' : ''}${sp.south_minus_north_pct}%`
    + `（南 n=${sp.south_n}，北 n=${sp.north_n}）`
})

async function load() {
  Object.keys(loading).forEach((k) => { loading[k] = true; errors[k] = '' })

  const tasks = [
    ['scatter', () => getScatter({ district_id: districtId.value, limit: 500 }), scatterRes],
    ['age', () => getAgeTrend({ district_id: districtId.value }), ageRes],
    ['ageDist', () => getAgeByDistrict(6), ageDistRes],
    ['premium', () => getPremium({ metric: 'metro', control: 'district' }), premiumRes],
    ['orientation', () => getFloorOrientation('both'), floorRes],
    ['orientation', () => getLayoutDistribution(8), layoutRes]
  ]

  const results = await Promise.allSettled(tasks.map(([, fn]) => fn()))
  results.forEach((r, i) => {
    const [key, , target] = tasks[i]
    if (r.status === 'fulfilled') target.value = r.value
    else errors[key] = r.reason?.message || '加载失败'
  })
  Object.keys(loading).forEach((k) => { loading[k] = false })
}

onMounted(async () => {
  try {
    districts.value = await getDistricts()
  } catch {
    districts.value = []
  }
  await load()
})
</script>
