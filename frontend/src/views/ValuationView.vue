<template>
  <div>
    <PageHeader
      title="估价参考"
      sub="相似房源加权均价"
      caliber="仅供参考，非评估报告。算法：同小区 → 同街道 → 同区三级降级；样本 <5 强制低置信度"
    />

    <div class="warnbox">
      <b>方法说明：</b>权重 = 1/(1+面积差比) × 1/(1+房龄差/10)；召回范围为面积 ±20%、房龄 ±5 年；
      样本不足 5 条降级到街道、不足 3 条降级到区。本系统<b>不承诺精度</b>，只提供可解释的参照区间。
    </div>

    <div class="grid g2">
      <div class="card">
        <h3 style="font-size: 14px; margin: 0 0 4px">输入条件</h3>
        <div class="small muted">每个输入标注对应字段与校验规则</div>

        <el-form label-width="110px" label-position="left" class="mt4" size="small">
          <el-form-item label="区">
            <el-select v-model="form.district_id" placeholder="请选择" style="width: 100%">
              <el-option v-for="d in districts" :key="d.district_id"
                         :label="d.district_name" :value="d.district_id" />
            </el-select>
            <div class="field-name">district_id — 必填</div>
          </el-form-item>

          <el-form-item label="街道（可选）">
            <el-select v-model="form.street_id" placeholder="不限" clearable style="width: 100%"
                       :disabled="!form.district_id">
              <el-option v-for="s in streets" :key="s.street_id"
                         :label="s.street_name" :value="s.street_id" />
            </el-select>
            <div class="field-name">street_id — 必须属于所选区</div>
          </el-form-item>

          <el-form-item label="面积（㎡）">
            <el-input-number v-model="form.area" :min="10" :max="1000" :step="5"
                             controls-position="right" style="width: 100%" />
            <div class="field-name">area — 校验 10–1000，越界返回 1001</div>
          </el-form-item>

          <el-form-item label="室 / 厅">
            <div class="flex gap2" style="width: 100%">
              <el-input-number v-model="form.room" :min="1" :max="20" size="small"
                               controls-position="right" style="width: 50%" />
              <el-input-number v-model="form.hall" :min="0" :max="10" size="small"
                               controls-position="right" style="width: 50%" />
            </div>
            <div class="field-name">room 1–20 / hall 0–10（厅=0 合法）</div>
          </el-form-item>

          <el-form-item label="房龄（年）">
            <el-input-number v-model="form.age" :min="0" :max="50"
                             controls-position="right" style="width: 100%" />
            <div class="field-name">age — 校验 0–50</div>
          </el-form-item>

          <el-form-item label="装修 / 楼层">
            <div class="flex gap2" style="width: 100%">
              <el-select v-model="form.decoration" placeholder="不限" clearable style="width: 50%">
                <el-option v-for="d in filterMeta.decoration" :key="d" :label="d" :value="d" />
              </el-select>
              <el-select v-model="form.floor_level" placeholder="不限" clearable style="width: 50%">
                <el-option v-for="f in filterMeta.floor_level" :key="f" :label="f" :value="f" />
              </el-select>
            </div>
            <div class="field-name">decoration / floor_level 枚举校验</div>
          </el-form-item>

          <el-form-item label="近地铁">
            <el-switch v-model="nearSubway" active-text="近地铁" inactive-text="不近" />
            <div class="field-name">near_subway 0/1</div>
          </el-form-item>

          <el-form-item label=" ">
            <el-button type="primary" style="width: 100%" :loading="loading" @click="submit">
              开始估价
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="card">
        <h3 style="font-size: 14px; margin: 0 0 4px">估价结果</h3>
        <div class="small muted">结果卡 + 置信度 + 样本数 + 免责文案</div>

        <el-skeleton v-if="loading" :rows="5" animated class="mt4" />
        <el-empty v-else-if="error" :description="error" class="mt4">
          <el-button size="small" @click="submit">重试</el-button>
        </el-empty>
        <el-empty v-else-if="!result" description="填写左侧条件后点击「开始估价」" class="mt4" />

        <template v-else-if="result">
          <template v-if="result.insufficient_sample && !result.est_total_price">
            <el-empty :description="result.message || '样本不足，无法给出参考价'" class="mt4" />
          </template>
          <template v-else>
            <div style="text-align: center; padding: 16px 0">
              <div class="field-name">est_total_price</div>
              <div class="big num">
                {{ fmtNum(result.price_range?.low) }} – {{ fmtNum(result.price_range?.high) }}
                <span class="unit">万</span>
              </div>
              <div class="field-name mt2">est_unit_price</div>
              <div class="big2 num">{{ fmtNum(result.est_unit_price) }}<span class="unit">元/㎡</span></div>
            </div>

            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="参考区间">
                ±{{ result.price_range?.pct }}%
              </el-descriptions-item>
              <el-descriptions-item label="相似样本数">
                <b class="num">{{ result.sample_count }}</b>
                <span class="field-name">sample_count</span>
              </el-descriptions-item>
              <el-descriptions-item label="降级层级">
                <el-tag size="small" :type="result.fallback_level === 'street' ? 'warning' : 'info'">
                  {{ result.fallback_level }}
                </el-tag>
                <span class="field-name">fallback_level</span>
              </el-descriptions-item>
              <el-descriptions-item label="置信度">
                <el-tag size="small"
                        :type="result.confidence === 'high' ? 'success' : (result.confidence === 'medium' ? 'warning' : 'info')">
                  {{ result.confidence }}
                </el-tag>
                <span class="field-name">confidence</span>
              </el-descriptions-item>
              <el-descriptions-item label="算法版本">
                {{ result.model_version }} <span class="field-name">model_version</span>
              </el-descriptions-item>
            </el-descriptions>

            <div class="note">{{ result.disclaimer }}</div>
            <div v-if="result.caliber" class="field-name mt2">{{ result.caliber }}</div>
          </template>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import { fmtNum } from '@/composables/useChart'
import { getDistricts, getMetaFilters, getStreets, postValuation } from '@/api'

const districts = ref([])
const streets = ref([])
const filterMeta = ref({ decoration: [], floor_level: [] })

const form = reactive({
  district_id: null,
  street_id: null,
  area: 80,
  room: 2,
  hall: 1,
  age: 10,
  decoration: null,
  floor_level: null
})
const nearSubway = ref(true)

const loading = ref(false)
const error = ref('')
const result = ref(null)

async function loadStreets() {
  if (!form.district_id) { streets.value = []; form.street_id = null; return }
  try {
    streets.value = await getStreets(form.district_id)
    if (form.street_id && !streets.value.some((s) => s.street_id === form.street_id)) {
      form.street_id = null
    }
  } catch {
    streets.value = []
  }
}

async function submit() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await postValuation({
      ...form,
      near_subway: nearSubway.value ? 1 : 0
    })
  } catch (e) {
    error.value = e.message || '估价失败'
  } finally {
    loading.value = false
  }
}

watch(() => form.district_id, loadStreets)

onMounted(async () => {
  try {
    const [d, m] = await Promise.all([getDistricts(), getMetaFilters()])
    districts.value = d
    filterMeta.value = m
    form.district_id = d[0]?.district_id ?? null
  } catch (e) {
    error.value = e.message
  }
})
</script>

<style scoped>
.big { font-size: 30px; font-weight: 700; color: var(--c-primary); }
.big2 { font-size: 20px; font-weight: 600; color: var(--c-accent); }
.unit { font-size: 13px; font-weight: 500; color: var(--c-muted); margin-left: 3px; }
:deep(.el-form-item) { margin-bottom: 16px; }
</style>
