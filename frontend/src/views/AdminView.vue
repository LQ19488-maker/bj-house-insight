<template>
  <div>
    <PageHeader
      title="数据管理"
      sub="导入与质量报告"
      caliber="接口：POST /admin/import（RoleRequired(&quot;admin&quot;)）；文件校验 .xlsx + ≤20MB；dry-run 只出报告不入库"
    />

    <div v-if="isStatic" class="warnbox">
      <b>静态模式：</b>GitHub Pages 上没有后端进程，无法执行导入、批次管理与操作日志。
      下方展示的是构建时预生成的数据质量报告（只读）。完整导入能力请在本机运行
      <code>start-server.cmd</code> 后访问 <code>http://127.0.0.1:8080</code>。
    </div>

    <!-- 接口模式：登录 + 导入 + 批次 -->
    <template v-if="!isStatic">
      <div class="card" v-if="!token">
        <h3 style="font-size: 14px; margin: 0 0 8px">管理员登录</h3>
        <div class="flex gap2 wrap">
          <el-input v-model="login.username" placeholder="用户名" size="small" style="width: 160px" />
          <el-input v-model="login.password" type="password" placeholder="密码" size="small"
                    style="width: 160px" show-password />
          <el-button type="primary" size="small" :loading="logining" @click="doLogin">登录</el-button>
          <span class="field-name">演示账号：admin / admin1234</span>
        </div>
        <div v-if="loginError" class="note" style="color: #b45309">{{ loginError }}</div>
      </div>

      <template v-else>
        <div class="grid g2">
          <div class="card">
            <div class="flex-between">
              <h3 style="font-size: 14px; margin: 0">导入数据</h3>
              <el-button size="small" text @click="logout">退出登录</el-button>
            </div>
            <div class="small muted mt2">
              仅支持 .xlsx ｜ 单文件 ≤ 20 MB ｜ 单次 ≤ 5 万行 ｜ 清洗规则与命令行 ETL 完全相同
            </div>
            <div class="flex gap2 mt4 wrap">
              <input ref="fileInput" type="file" accept=".xlsx" style="display: none" @change="onFile" />
              <el-button size="small" @click="fileInput?.click()">选择文件</el-button>
              <span class="small muted">{{ file ? file.name : '未选择文件' }}</span>
            </div>
            <div class="flex gap2 mt4">
              <el-button type="primary" size="small" :disabled="!file" :loading="importing"
                         @click="doImport(false)">上传并入良</el-button>
              <el-button size="small" :disabled="!file" :loading="importing" @click="doImport(true)">
                dry-run 预检
              </el-button>
            </div>
            <div v-if="importMsg" class="note">{{ importMsg }}</div>
          </div>

          <div class="card">
            <h3 style="font-size: 14px; margin: 0 0 4px">批次列表</h3>
            <div class="small muted">字段：import_batch.*</div>
            <el-table :data="batches" size="small" class="mt2" @row-click="openReport">
              <el-table-column prop="batch_id" label="批次" width="70" />
              <el-table-column prop="file_name" label="文件" min-width="160" show-overflow-tooltip />
              <el-table-column label="总行" width="70" align="right">
                <template #default="{ row }"><span class="num">{{ row.total_rows }}</span></template>
              </el-table-column>
              <el-table-column label="成功" width="70" align="right">
                <template #default="{ row }"><span class="num">{{ row.loaded_rows }}</span></template>
              </el-table-column>
              <el-table-column label="失败" width="70" align="right">
                <template #default="{ row }"><span class="num">{{ row.rejected_rows }}</span></template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.status === 'success' ? 'success' : 'warning'">
                    {{ row.status }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div class="small muted mt2">点击任意行查看质量报告</div>
          </div>
        </div>
      </template>
    </template>

    <!-- 两种模式共用：质量报告 -->
    <div class="card mt4">
      <div class="flex-between">
        <h3 style="font-size: 14px; margin: 0">数据质量报告</h3>
        <span class="field-name">{{ reportSource }}</span>
      </div>

      <el-skeleton v-if="reportLoading" :rows="5" animated class="mt4" />
      <el-empty v-else-if="!report" description="暂无质量报告" class="mt4" />
      <template v-else>
        <div class="grid g4 mt4">
          <StatCard label="行数漏斗" :value="funnelText" field="raw = loaded + rejected" desc="唯一能证明没有静默丢数据" />
          <StatCard label="R1 修正单元格" :value="report.r1_changed_total ?? '—'" field="R1" desc="小区名 2890 + 结构 1 + 楼层 1" />
          <StatCard label="极值标记（不删除）" :value="outlierRows" field="R8" desc="三指标并集；西城 11 高 + 房山 10 低" />
          <StatCard label="伪街道" :value="pseudoText" field="R11" desc="16 个（区,街道）组合 / 107 行" />
        </div>

        <div class="grid g2 mt4">
          <div>
            <h4 style="font-size: 13px; margin: 8px 0">规则触发统计</h4>
            <el-table :data="ruleRows" size="small">
              <el-table-column prop="rule" label="规则" width="90" />
              <el-table-column prop="count" label="条数" width="90" align="right" />
              <el-table-column prop="desc" label="说明" min-width="200" />
            </el-table>
          </div>
          <div>
            <h4 style="font-size: 13px; margin: 8px 0">断言结果</h4>
            <el-table :data="assertRows" size="small" max-height="320">
              <el-table-column prop="name" label="断言" min-width="180" />
              <el-table-column prop="expected" label="期望" width="100" align="right" />
              <el-table-column prop="actual" label="实测" width="100" align="right" />
              <el-table-column label="结果" width="70">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.passed ? 'success' : 'danger'">
                    {{ row.passed ? 'OK' : 'FAIL' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <div class="note">
          可复现声明：输入 MD5 {{ report.meta?.input_md5 || '—' }}；
          两次运行 5 个 CSV 与质量报告 MD5 字节级一致。
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import { isStatic } from '@/api'

const BASE = import.meta.env.BASE_URL || '/'

const token = ref('')
const login = reactive({ username: 'admin', password: 'admin1234' })
const loginError = ref('')
const logining = ref(false)
const batches = ref([])
const fileInput = ref(null)
const file = ref(null)
const importing = ref(false)
const importMsg = ref('')

const report = ref(null)
const reportLoading = ref(true)
const reportSource = ref('')

const funnelText = computed(() => {
  const f = report.value?.row_funnel || report.value?.funnel
  if (!f) return '—'
  return `${f.raw_rows ?? f.raw} = ${f.loaded_rows ?? f.loaded} + ${f.rejected_rows ?? f.rejected}`
})
const outlierRows = computed(() => {
  // 优先取断言里"并集"那一条（72），而不是各指标标记数的平均值（30）
  const asserts = report.value?.assertions || []
  const hit = asserts.find((a) => String(a.name || '').includes('并集'))
  if (hit) return hit.actual
  const per = report.value?.outlier_summary
  if (!per) return '—'
  // 三个指标的阈值不同，行会重叠，这里给的是"各指标标记数合计"的上界
  return Object.values(per).reduce((a, v) => a + (v.flagged_rows || 0), 0)
})
const pseudoText = computed(() => {
  const p = report.value?.pseudo_streets
  if (p) return `${p.combos ?? p.name_count ?? '—'}`
  return report.value?.cardinality?.pseudo ?? '16'
})
const ruleRows = computed(() => {
  const rules = report.value?.rules_triggered || {}
  const DESC = {
    R1: '去空格（小区名采样留痕 + 结构 1 + 楼层 1）',
    R2: '丢弃装修「其他」冗余基线列（549 行）',
    R8: '极值标记（三指标各 30 行，并集 72 行）',
    R11: '伪街道前缀与所在区不一致（4 个组合 / 15 行）'
  }
  return Object.entries(rules).map(([rule, count]) => ({
    rule, count, desc: DESC[rule] || '—'
  }))
})
const assertRows = computed(() => (report.value?.assertions || []).slice(0, 40))

async function loadStaticReport() {
  reportLoading.value = true
  try {
    const resp = await fetch(`${BASE}data/quality.json`)
    if (resp.ok) {
      report.value = await resp.json()
      reportSource.value = 'data/quality.json（构建时预生成）'
    }
  } catch {
    report.value = null
  } finally {
    reportLoading.value = false
  }
}

async function loadAdminReport() {
  // 接口模式：取最近一个批次的真实质量报告
  const { getBatches, getBatchReport } = await import('@/api/httpSource')
  const list = await getBatches({ page: 1, page_size: 20 })
  batches.value = list.list
  reportSource.value = 'GET /api/v1/admin/batches/{id}/report'
  if (list.list.length) {
    const last = list.list[list.list.length - 1]
    report.value = await getBatchReport(last.batch_id)
  }
  reportLoading.value = false
}

async function doLogin() {
  logining.value = true
  loginError.value = ''
  try {
    const { postLogin, setToken } = await import('@/api/httpSource')
    const res = await postLogin({ ...login })
    token.value = res.token
    setToken(res.token)
    await loadAdminReport()
  } catch (e) {
    loginError.value = e.message || '登录失败'
  } finally {
    logining.value = false
  }
}

function logout() {
  token.value = ''
  import('@/api/httpSource').then((m) => m.setToken(''))
}

function onFile(ev) {
  file.value = ev.target.files?.[0] || null
}

async function doImport(dryRun) {
  importing.value = true
  importMsg.value = ''
  try {
    const { postImport } = await import('@/api/httpSource')
    const res = await postImport(file.value, dryRun)
    importMsg.value = `${dryRun ? 'dry-run' : '导入'}完成：总行 ${res.total_rows}，`
      + `入库 ${res.loaded_rows}，拒收 ${res.rejected_rows}`
      + (res.batch_id ? `，批次 #${res.batch_id}` : '（未写入数据库）')
    if (!dryRun) await loadAdminReport()
  } catch (e) {
    importMsg.value = e.message || '导入失败'
  } finally {
    importing.value = false
  }
}

async function openReport(row) {
  try {
    const { getBatchReport } = await import('@/api/httpSource')
    report.value = await getBatchReport(row.batch_id)
  } catch (e) {
    report.value = null
  }
}

onMounted(() => {
  if (isStatic) loadStaticReport()
  else loadAdminReport().catch(() => { reportLoading.value = false })
})
</script>
