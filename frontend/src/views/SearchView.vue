<template>
  <div>
    <PageHeader
      title="房源检索"
      sub="11 类筛选条件 · 条件同步到 URL"
      caliber="组合逻辑：不同条件之间 AND，同一多选项内部 IN；排序字段走白名单（防注入）"
    />

    <div class="layout">
      <!-- 左侧筛选面板 -->
      <aside class="card filter">
        <div class="fg">
          <label>关键词（小区名）</label>
          <el-input v-model="f.keyword" placeholder="如 银河" clearable size="small" />
          <div class="field-name">community.name — 前缀匹配</div>
        </div>

        <div class="fg">
          <label>区</label>
          <el-select v-model="f.district_id" placeholder="全部" clearable size="small" style="width: 100%">
            <el-option v-for="d in districtList" :key="d.district_id"
                       :label="d.district_name" :value="d.district_id" />
          </el-select>
          <div class="field-name">house.district_id</div>
        </div>

        <div class="fg">
          <label>街道（联动）</label>
          <el-select v-model="f.street_id" placeholder="全部" clearable size="small"
                     style="width: 100%" :disabled="!f.district_id">
            <el-option v-for="s in streetList" :key="s.street_id"
                       :label="s.street_name" :value="s.street_id" />
          </el-select>
          <div class="field-name">house.street_id — 随区联动</div>
        </div>

        <div class="fg">
          <label>总价区间（万元）</label>
          <el-slider v-model="priceRange" range :min="36" :max="8000" :step="10"
                     :show-tooltip="true" size="small" />
          <div class="field-name">house.total_price BETWEEN ? AND ?</div>
        </div>

        <div class="fg">
          <label>面积区间（㎡）</label>
          <el-slider v-model="areaRange" range :min="16" :max="750" :step="5" size="small" />
          <div class="field-name">house.area BETWEEN ? AND ?</div>
        </div>

        <div class="fg">
          <label>户型（室 / 厅）</label>
          <div class="flex gap2">
            <el-select v-model="f.room" placeholder="室" clearable size="small" style="width: 50%">
              <el-option v-for="r in roomOptions" :key="r" :label="`${r} 室`" :value="r" />
            </el-select>
            <el-select v-model="f.hall" placeholder="厅" clearable size="small" style="width: 50%">
              <el-option v-for="h in hallOptions" :key="h" :label="`${h} 厅`" :value="h" />
            </el-select>
          </div>
          <div class="field-name">house.room / house.hall（厅=0 合法）</div>
        </div>

        <div class="fg">
          <label>房龄上限（年）</label>
          <el-input-number v-model="f.age_max" :min="3" :max="50" size="small"
                           controls-position="right" style="width: 100%" />
          <div class="field-name">house.house_age &lt;= ?</div>
        </div>

        <div class="fg">
          <label>装修</label>
          <el-checkbox-group v-model="f.decoration" size="small">
            <el-checkbox v-for="d in filterMeta.decoration" :key="d" :value="d" :label="d" />
          </el-checkbox-group>
          <div class="field-name">house.decoration IN (...)</div>
        </div>

        <div class="fg">
          <label>结构</label>
          <el-checkbox-group v-model="f.structure" size="small">
            <el-checkbox v-for="s in filterMeta.structure" :key="s" :value="s" :label="s" />
          </el-checkbox-group>
          <div class="field-name">house.structure IN (...)</div>
        </div>

        <div class="fg">
          <label>朝向（多选）</label>
          <el-checkbox-group v-model="f.direction" size="small">
            <el-checkbox v-for="d in filterMeta.direction" :key="d" :value="d" :label="d" />
          </el-checkbox-group>
          <div class="field-name">house_orientation.direction IN (...)</div>
        </div>

        <div class="fg">
          <label>近地铁</label>
          <el-select v-model="f.near_subway" placeholder="不限" clearable size="small" style="width: 100%">
            <el-option label="仅近地铁" :value="1" />
            <el-option label="仅不近地铁" :value="0" />
          </el-select>
          <div class="field-name">house.near_subway</div>
        </div>

        <div class="fg flex gap2">
          <el-button type="primary" size="small" style="flex: 1" @click="resetFilters">重置</el-button>
          <el-button size="small" style="flex: 1" @click="load">查询</el-button>
        </div>
        <div class="field-name">共 {{ fmtNum(total) }} 条 · 用时 {{ tookMs }} ms</div>
      </aside>

      <!-- 右侧结果区 -->
      <section>
        <div class="card flex-between">
          <div class="flex gap4 wrap">
            <span class="small muted">排序</span>
            <el-select v-model="f.sort" size="small" style="width: 130px">
              <el-option label="单价" value="unit_price" />
              <el-option label="总价" value="total_price" />
              <el-option label="面积" value="area" />
              <el-option label="房龄" value="house_age" />
            </el-select>
            <el-select v-model="f.order" size="small" style="width: 90px">
              <el-option label="升序" value="asc" />
              <el-option label="降序" value="desc" />
            </el-select>
            <span class="field-name">sort 白名单：unit_price / total_price / area / house_age</span>
          </div>
          <div class="small">
            命中 <b class="num">{{ fmtNum(total) }}</b> 套
          </div>
        </div>

        <div class="card mt4">
          <el-skeleton v-if="loading" :rows="6" animated />
          <el-empty v-else-if="error" :description="error">
            <el-button size="small" @click="load">重试</el-button>
          </el-empty>
          <el-empty v-else-if="!rows.length" description="该条件下无房源，试试放宽价格区间">
            <el-button size="small" @click="resetFilters">清空筛选</el-button>
          </el-empty>
          <template v-else>
            <el-table :data="rows" size="small" stripe @row-click="goDetail">
              <el-table-column prop="community_name" label="小区" min-width="140" />
              <el-table-column prop="district_name" label="区" width="80" />
              <el-table-column prop="street_name" label="街道" width="100" />
              <el-table-column label="户型" width="80">
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
              <el-table-column label="装修" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.decoration === '精装' ? 'success' : 'info'">
                    {{ row.decoration }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="floor_level" label="楼层" width="70" />
              <el-table-column label="房龄" width="70" align="right">
                <template #default="{ row }"><span class="num">{{ row.house_age }}</span></template>
              </el-table-column>
              <el-table-column label="朝向" width="90">
                <template #default="{ row }">{{ row.orientation_text }}</template>
              </el-table-column>
              <el-table-column label="标记" width="90">
                <template #default="{ row }">
                  <el-tag v-if="row.is_outlier" size="small" type="warning">极值</el-tag>
                  <el-tag v-if="row.abnormal_layout" size="small" type="info">非常规</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" text type="primary" @click.stop="goDetail(row)">详情</el-button>
                  <el-button size="small" text @click.stop="addCompare(row)">对比</el-button>
                </template>
              </el-table-column>
            </el-table>

            <div class="flex-between mt4">
              <span class="small muted">共 {{ fmtNum(total) }} 条</span>
              <el-pagination
                v-model:current-page="f.page"
                v-model:page-size="f.page_size"
                :page-sizes="[20, 50, 100]"
                :total="total"
                layout="sizes, prev, pager, next, jumper"
                size="small"
                background
              />
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import { fmtNum } from '@/composables/useChart'
import { useFiltersStore, useUrlSync } from '@/stores/filters'
import { useCompareStore } from '@/stores/compare'
import { getDistricts, getHouses, getMetaFilters, getStreets } from '@/api'

const router = useRouter()
const store = useFiltersStore()
const compare = useCompareStore()
useUrlSync(store)

const f = store.state
const loading = ref(true)
const error = ref('')
const rows = ref([])
const total = ref(0)
const tookMs = ref(0)
const districtList = ref([])
const streetList = ref([])
const filterMeta = ref({ decoration: [], structure: [], direction: [] })

const priceRange = ref([36, 8000])
const areaRange = ref([16, 750])
const roomOptions = [1, 2, 3, 4, 5, 6]
const hallOptions = [0, 1, 2, 3, 4]

const effectiveParams = computed(() => ({
  ...f,
  price_min: priceRange.value[0] > 36 ? priceRange.value[0] : null,
  price_max: priceRange.value[1] < 8000 ? priceRange.value[1] : null,
  area_min: areaRange.value[0] > 16 ? areaRange.value[0] : null,
  area_max: areaRange.value[1] < 750 ? areaRange.value[1] : null
}))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getHouses(effectiveParams.value)
    rows.value = res.list
    total.value = res.total
    tookMs.value = res.took_ms ?? 0
  } catch (e) {
    error.value = e.message || '查询失败'
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function loadStreets() {
  if (!f.district_id) {
    streetList.value = []
    f.street_id = null
    return
  }
  try {
    streetList.value = await getStreets(f.district_id)
    if (f.street_id && !streetList.value.some((s) => s.street_id === f.street_id)) {
      f.street_id = null
    }
  } catch {
    streetList.value = []
  }
}

function resetFilters() {
  store.reset()
  priceRange.value = [36, 8000]
  areaRange.value = [16, 750]
  load()
}

function goDetail(row) {
  router.push(`/houses/${row.house_id}`)
}

function addCompare(row) {
  const res = compare.add(row.house_id)
  if (res.added) ElMessage.success('已加入对比')
  else if (res.reason === 'already') ElMessage.info('该房源已在对比篮中')
  else ElMessage.warning('对比篮最多 4 套')
}

watch(() => f.district_id, loadStreets)
watch(() => [f.page, f.page_size, f.sort, f.order], load)

onMounted(async () => {
  try {
    const [d, m] = await Promise.all([getDistricts(), getMetaFilters()])
    districtList.value = d
    filterMeta.value = m
  } catch {
    /* 字典加载失败不阻塞主流程 */
  }
  await loadStreets()
  await load()
})
</script>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 1280px) {
  .layout { grid-template-columns: 1fr; }
}
.filter { position: sticky; top: 72px; }
.fg { margin-bottom: 14px; }
.fg label {
  display: block;
  font-size: 12px;
  color: #374151;
  margin-bottom: 4px;
}
:deep(.el-checkbox) { margin-right: 8px; }
:deep(.el-table__row) { cursor: pointer; }
</style>
