<template>
  <div>
    <PageHeader
      title="小区画像"
      :sub="c ? `${c.community_name} · ${c.district_name}` : ''"
      caliber="重要约束：67.4% 的小区只有 1 套在售，不能做箱线图，只能做“在同街道中的位置”"
    />

    <el-skeleton v-if="loading" :rows="8" animated />
    <el-empty v-else-if="error" :description="error">
      <el-button size="small" @click="load">重试</el-button>
    </el-empty>

    <template v-else-if="c">
      <div class="grid g4">
        <StatCard label="在售套数" :value="c.house_count" field="community.house_count" />
        <StatCard label="小区均价" :value="fmtNum(c.avg_unit_price)" unit="元/㎡" field="community.avg_unit_price" />
        <StatCard label="中位总价" :value="fmtNum(c.median_total_price)" unit="万元" field="community.median_total_price" />
        <StatCard label="平均房龄" :value="c.avg_age" unit="年" field="community.avg_age" />
      </div>

      <div class="grid g2 mt4">
        <ChartCard
          title="同街道小区均价分布"
          tip="每个条形=一个小区，标签为在售套数；不用箱线图的原因见上方说明"
          :caliber="`该小区在同街道 ${c.street_community_count} 个小区中处于第 ${c.street_percentile ?? '—'} 百分位；街道均价 ${fmtNum(c.street_avg_unit_price)} 元/㎡（n=${c.street_house_count}）`"
          :option="peerOption"
          :height="330"
        />
        <div class="card">
          <h3 style="font-size: 14px; margin: 0 0 4px">同街道小区排行</h3>
          <div class="small muted">community.avg_unit_price 降序</div>
          <el-table :data="c.street_rank.slice(0, 12)" size="small" class="mt2"
                    highlight-current-row>
            <el-table-column type="index" width="46" label="#" />
            <el-table-column prop="community_name" label="小区" min-width="140" />
            <el-table-column label="在售" width="70" align="right">
              <template #default="{ row }"><span class="num">{{ row.house_count }}</span></template>
            </el-table-column>
            <el-table-column label="均价" width="110" align="right">
              <template #default="{ row }"><span class="num">{{ fmtNum(row.avg_unit_price) }}</span></template>
            </el-table-column>
            <el-table-column label="中位总价" width="100" align="right">
              <template #default="{ row }"><span class="num">{{ fmtNum(row.median_total_price) }}</span></template>
            </el-table-column>
          </el-table>
          <div class="note">
            街道 <b>{{ c.street_name || '—' }}</b>：
            存在 12 个「XX其他」伪街道（16 个组合 / 107 行），排行与画像默认排除。
          </div>
        </div>
      </div>

      <div class="card mt4">
        <h3 style="font-size: 14px; margin: 0 0 8px">该小区在售房源</h3>
        <el-table :data="c.houses" size="small" @row-click="(row) => $router.push(`/houses/${row.house_id}`)">
          <el-table-column prop="house_id" label="ID" width="80" />
          <el-table-column label="户型" width="90">
            <template #default="{ row }">{{ row.room }}室{{ row.hall }}厅</template>
          </el-table-column>
          <el-table-column label="面积" width="90" align="right">
            <template #default="{ row }"><span class="num">{{ row.area }}</span></template>
          </el-table-column>
          <el-table-column label="总价(万)" width="100" align="right">
            <template #default="{ row }"><span class="num">{{ fmtNum(row.total_price) }}</span></template>
          </el-table-column>
          <el-table-column label="单价(元/㎡)" width="110" align="right">
            <template #default="{ row }"><span class="num">{{ fmtNum(row.unit_price) }}</span></template>
          </el-table-column>
          <el-table-column prop="decoration" label="装修" width="80" />
          <el-table-column prop="floor_level" label="楼层" width="80" />
          <el-table-column prop="orientation_text" label="朝向" width="90" />
          <el-table-column label="房龄" width="70" align="right">
            <template #default="{ row }"><span class="num">{{ row.house_age }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import ChartCard from '@/components/ChartCard.vue'
import { groupBarOption } from '@/charts/options'
import { fmtNum } from '@/composables/useChart'
import { getCommunity } from '@/api'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const c = ref(null)

const peerOption = computed(() => {
  if (!c.value) return null
  const rows = c.value.street_rank.slice(0, 12).map((p) => ({
    label: p.community_name,
    avg_unit_price: p.avg_unit_price,
    n: p.house_count,
    insufficient_sample: p.house_count < 3
  }))
  return groupBarOption(rows, { labelKey: 'label' })
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    c.value = await getCommunity(route.params.id)
  } catch (e) {
    error.value = e.message || '加载失败'
    c.value = null
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, load)
onMounted(load)
</script>
