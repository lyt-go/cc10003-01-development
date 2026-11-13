<template>
  <section class="page" data-module="metricgov">
    <header class="page-head">
      <div>
        <h2>口径影响面</h2>
        <p class="page-desc">
          选择指标定义即可预览口径版本、统计粒度、时间窗口与引用看板；发布新版本后只有受影响的指标卡进入待重算，未受影响的继续复用原结果。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reloadAll">刷新面板</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p v-if="message.text" class="notice" :class="message.kind">{{ message.text }}</p>

    <div class="panel-grid">
      <div class="panel">
        <h3>指标定义（选择后查看口径与引用）</h3>
        <div class="metric-list">
          <div
            v-for="item in metrics"
            :key="item.指标编号"
            class="metric-item"
            :class="{ active: item.指标编号 === selected }"
            @click="selectMetric(item.指标编号)"
          >
            <strong>{{ item.指标编号 }} · {{ item.指标名称 }}</strong>
            <span class="badge" :class="statusClass(item.指标状态)">{{ item.指标状态 }}</span>
            <span class="badge blue">口径 {{ item.当前口径版本 }}</span>
            <div class="metric-sub">
              粒度 {{ item.统计粒度 }} · 窗口 {{ item.时间窗口 }} · 引用看板 {{ item.引用看板数 }} 个
              <template v-if="item.待重算卡片">· 待重算 {{ item.待重算卡片 }}</template>
              <template v-if="item.已阻止卡片">· 已阻止 {{ item.已阻止卡片 }}</template>
            </div>
          </div>
        </div>
      </div>

      <div class="panel" v-if="profile">
        <h3>口径预览与发布 · {{ profile.指标编号 }}</h3>
        <div class="kv-list">
          <span>当前口径版本 <strong>{{ profile.当前口径版本 }}</strong></span>
          <span>统计粒度 <strong>{{ profile.统计粒度 }}</strong></span>
          <span>时间窗口 <strong>{{ profile.时间窗口 }}</strong></span>
          <span>指标状态 <strong>{{ profile.指标状态 }}</strong></span>
          <span>历史版本 <strong>{{ profile.历史版本数 }}</strong> 个</span>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>引用看板</th><th>看板状态</th><th>卡片</th><th>引用版本</th><th>卡片状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="ref in profile.引用看板" :key="ref.卡片编号">
              <td>{{ ref.看板编号 }} · {{ ref.看板名称 }}</td>
              <td>{{ ref.看板状态 }}</td>
              <td>{{ ref.卡片编号 }}</td>
              <td>{{ ref.引用口径版本 }}</td>
              <td><span class="badge" :class="cardClass(ref.卡片状态)">{{ ref.卡片状态 }}</span></td>
            </tr>
            <tr v-if="!profile.引用看板.length">
              <td colspan="5" class="empty-state">暂无看板引用该指标</td>
            </tr>
          </tbody>
        </table>

        <h3 class="panel-sub">调整口径（只改要变的字段，其余保持当前值）</h3>
        <div class="form-grid">
          <label v-for="field in caliberFields" :key="field">
            <span>{{ field }}</span>
            <input v-model="form[field]" :placeholder="`新的${field}`" />
          </label>
          <label>
            <span>基准版本（并发校验）</span>
            <input v-model="form.基准版本" placeholder="基于哪个口径版本发起" />
          </label>
          <label>
            <span>发起看板</span>
            <select v-model="form.发起看板">
              <option value="">—</option>
              <option v-for="ref in profile.引用看板" :key="ref.看板编号" :value="ref.看板编号">
                {{ ref.看板编号 }} · {{ ref.看板名称 }}
              </option>
            </select>
          </label>
          <label>
            <span>操作人</span>
            <input v-model="form.操作人" placeholder="发布操作人" />
          </label>
        </div>
        <div class="page-actions">
          <button class="btn" type="button" @click="runPreview">预览影响</button>
          <button class="btn primary" type="button" @click="runPublish">发布新版本</button>
        </div>

        <template v-if="previewResult">
          <h3 class="panel-sub">预览结果 · 影响级别
            <span class="badge" :class="impactClass(previewResult.影响级别)">{{ previewResult.影响级别 }}</span>
          </h3>
          <p class="notice" :class="previewResult.可发布 ? 'ok' : 'error'">{{ previewResult.提示 }}</p>
          <table class="data-table">
            <thead>
              <tr><th>字段</th><th>旧值</th><th>新值</th><th>变更类型</th><th>影响级别</th></tr>
            </thead>
            <tbody>
              <tr v-for="change in previewResult.变更明细" :key="change.字段">
                <td>{{ change.字段 }}</td>
                <td>{{ change.旧值 }}</td>
                <td>{{ change.新值 }}</td>
                <td><span class="badge" :class="changeClass(change.变更类型)">{{ change.变更类型 }}</span></td>
                <td>{{ change.影响级别 }}</td>
              </tr>
              <tr v-if="!previewResult.变更明细.length">
                <td colspan="5" class="empty-state">口径无变化</td>
              </tr>
            </tbody>
          </table>
          <table class="data-table">
            <thead>
              <tr><th>看板</th><th>卡片</th><th>当前引用</th><th>预计处理</th><th>原因</th></tr>
            </thead>
            <tbody>
              <tr v-for="ref in previewResult.引用看板" :key="ref.卡片编号">
                <td>{{ ref.看板编号 }} · {{ ref.看板名称 }}</td>
                <td>{{ ref.卡片编号 }}</td>
                <td>{{ ref.当前引用版本 }}</td>
                <td><span class="badge" :class="cardClass(ref.预计处理)">{{ ref.预计处理 }}</span></td>
                <td>{{ ref.原因 }}</td>
              </tr>
              <tr v-if="!previewResult.引用看板.length">
                <td colspan="5" class="empty-state">没有看板引用，发布后不影响任何指标卡</td>
              </tr>
            </tbody>
          </table>
        </template>

        <template v-if="publishResult">
          <h3 class="panel-sub">最近处理结果 · 提交号 {{ publishResult.提交号 }}</h3>
          <div class="kv-list">
            <span>新版本 <strong>{{ publishResult.新版本 }}</strong></span>
            <span>变更类型 <strong>{{ publishResult.变更类型.join('、') }}</strong></span>
            <span>发布进度 <strong>{{ publishResult.发布进度 }}</strong></span>
            <span>发布状态 <strong>{{ publishResult.发布状态 }}</strong></span>
          </div>
          <p class="notice ok">{{ publishResult.提示 }}</p>
          <table class="data-table">
            <thead>
              <tr><th>看板</th><th>卡片</th><th>旧引用</th><th>新引用</th><th>处理结果</th></tr>
            </thead>
            <tbody>
              <tr v-for="card in publishResult.影响卡片" :key="card.卡片编号">
                <td>{{ card.看板编号 }} · {{ card.看板名称 }}</td>
                <td>{{ card.卡片编号 }}</td>
                <td>{{ card.旧引用版本 }}</td>
                <td>{{ card.新引用版本 }}</td>
                <td><span class="badge" :class="cardClass(card.处理结果)">{{ card.处理结果 }}</span></td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </div>

    <div class="panel">
      <h3>指标卡（看板引用 → 当前版本 → 最近处理结果）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>卡片编号</th><th>看板</th><th>指标</th><th>引用口径版本</th>
            <th>卡片状态</th><th>最近处理结果</th><th>来源提交号</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="card in cards" :key="card.卡片编号">
            <td>{{ card.卡片编号 }}</td>
            <td>{{ card.看板编号 }} · {{ card.看板名称 }}</td>
            <td>{{ card.指标编号 }} · {{ card.指标名称 }}</td>
            <td>{{ card.引用口径版本 }}</td>
            <td><span class="badge" :class="cardClass(card.卡片状态)">{{ card.卡片状态 }}</span></td>
            <td>{{ card.最近处理结果 }}</td>
            <td>{{ card.来源提交号 }}</td>
            <td><button class="link" type="button" @click="refreshCard(card.卡片编号)">重算</button></td>
          </tr>
          <tr v-if="!cards.length">
            <td colspan="8" class="empty-state">暂无指标卡</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel-grid">
      <div class="panel">
        <h3>口径版本历史 · {{ selected || '未选择' }}</h3>
        <table class="data-table">
          <thead>
            <tr><th>版本</th><th>变更类型</th><th>状态</th><th>提交号</th><th>发布时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="version in versions" :key="version.版本编号">
              <td>{{ version.口径版本 }}</td>
              <td>{{ version.变更类型 }}</td>
              <td><span class="badge" :class="version.版本状态 === '当前' ? 'green' : 'gray'">{{ version.版本状态 }}</span></td>
              <td>{{ version.提交号 }}</td>
              <td>{{ version.发布时间 }}</td>
            </tr>
            <tr v-if="!versions.length">
              <td colspan="5" class="empty-state">该指标还没有已发布的口径版本</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h3>看板发布记录</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>提交号</th><th>指标</th><th>版本</th><th>变更类型</th>
              <th>发起看板</th><th>影响/待重算/复用</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="release in releases" :key="release.提交号">
              <td>{{ release.提交号 }}</td>
              <td>{{ release.指标编号 }}</td>
              <td>{{ release.口径版本 }}</td>
              <td>{{ release.变更类型 }}</td>
              <td>{{ release.发起看板 }}</td>
              <td>{{ release.影响卡片数 }} / {{ release.待重算数 }} / {{ release.复用结果数 }}</td>
              <td><span class="badge" :class="release.发布状态 === '已完成' ? 'green' : 'red'">{{ release.发布状态 }}</span></td>
            </tr>
            <tr v-if="!releases.length">
              <td colspan="7" class="empty-state">暂无发布记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <h3>审计记录（版本切换同步留痕）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>审计编号</th><th>提交号</th><th>操作类型</th><th>指标</th><th>看板</th>
            <th>旧版本</th><th>新版本</th><th>影响卡片数</th><th>结果</th><th>时间</th><th>操作人</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="audit in audits" :key="audit.审计编号">
            <td>{{ audit.审计编号 }}</td>
            <td>{{ audit.提交号 }}</td>
            <td>{{ audit.操作类型 }}</td>
            <td>{{ audit.指标编号 }}</td>
            <td>{{ audit.看板编号 }}</td>
            <td>{{ audit.旧版本 }}</td>
            <td>{{ audit.新版本 }}</td>
            <td>{{ audit.影响卡片数 }}</td>
            <td>{{ audit.操作结果 }}</td>
            <td>{{ audit.操作时间 }}</td>
            <td>{{ audit.操作人 }}</td>
          </tr>
          <tr v-if="!audits.length">
            <td colspan="11" class="empty-state">暂无审计记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, any>

const caliberFields = ['指标名称', '计算公式', '统计粒度', '时间窗口', '筛选条件', '精度位数']

const stats = ref<{ label: string; value: number }[]>([])
const metrics = ref<Row[]>([])
const selected = ref('')
const profile = ref<Row | null>(null)
const form = ref<Row>({ 操作人: '值班管理员' })
const previewResult = ref<Row | null>(null)
const publishResult = ref<Row | null>(null)
const cards = ref<Row[]>([])
const versions = ref<Row[]>([])
const releases = ref<Row[]>([])
const audits = ref<Row[]>([])
const message = ref<{ text: string; kind: string }>({ text: '', kind: '' })

function statusClass(status: string) {
  if (status === '已发布') return 'green'
  if (status === '已下线') return 'gray'
  return 'orange'
}

function cardClass(status: string) {
  if (status === '正常') return 'green'
  if (status === '待重算') return 'orange'
  if (status === '已阻止') return 'red'
  if (status === '复用原结果') return 'blue'
  return 'gray'
}

function impactClass(level: string) {
  if (level === '数据影响') return 'red'
  if (level === '展示影响') return 'blue'
  return 'gray'
}

function changeClass(changeType: string) {
  if (changeType === '仅名称变化') return 'blue'
  if (changeType === '首次发布') return 'green'
  return 'orange'
}

function showMessage(text: string, kind: string) {
  message.value = { text, kind }
}

async function selectMetric(code: string) {
  selected.value = code
  previewResult.value = null
  publishResult.value = null
  try {
    const data = await fetchJson<Row>(`/api/metricgov/metrics/${code}/profile`)
    profile.value = data
    const next: Row = { 操作人: form.value.操作人 || '值班管理员' }
    for (const field of caliberFields) {
      next[field] = data[field] ?? ''
    }
    next.基准版本 = data.当前口径版本 === '未发布' ? '无' : data.当前口径版本
    next.发起看板 = data.引用看板?.[0]?.看板编号 ?? ''
    form.value = next
    const versionData = await fetchJson<{ items: Row[] }>(`/api/metricgov/metrics/${code}/versions`)
    versions.value = versionData.items ?? []
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '指标口径档案读取失败', 'error')
  }
}

async function runPreview() {
  if (!selected.value) return
  publishResult.value = null
  try {
    const response = await request(`/api/metricgov/metrics/${selected.value}/preview`, {
      method: 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      showMessage(payload.message || '预览失败', 'error')
      previewResult.value = null
      return
    }
    previewResult.value = payload.entry
    showMessage(payload.message, 'ok')
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '预览请求失败', 'error')
  }
}

async function runPublish() {
  if (!selected.value) return
  try {
    const response = await request(`/api/metricgov/metrics/${selected.value}/publish`, {
      method: 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      showMessage(payload.message || '发布未生效', 'error')
      publishResult.value = null
      return
    }
    publishResult.value = payload.entry
    previewResult.value = null
    showMessage(payload.message, 'ok')
    await reloadAll()
    await selectMetric(selected.value)
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '发布请求失败', 'error')
  }
}

async function refreshCard(cardCode: string) {
  try {
    const response = await request(`/api/metricgov/cards/${cardCode}/refresh`, {
      method: 'POST',
      body: JSON.stringify({ values: { 操作人: form.value.操作人 || '值班管理员' } }),
    })
    const payload = await response.json()
    showMessage(payload.message || '刷新结束', payload.ok ? 'ok' : 'error')
    await reloadAll()
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '刷新请求失败', 'error')
  }
}

async function reloadAll() {
  try {
    const panel = await fetchJson<Row>('/api/metricgov/panel')
    stats.value = panel.stats ?? []
    metrics.value = panel.metrics ?? []
    const [cardData, releaseData, auditData] = await Promise.all([
      fetchJson<{ items: Row[] }>('/api/metricgov/cards'),
      fetchJson<{ items: Row[] }>('/api/metricgov/releases'),
      fetchJson<{ items: Row[] }>('/api/metricgov/audits'),
    ])
    cards.value = cardData.items ?? []
    releases.value = releaseData.items ?? []
    audits.value = auditData.items ?? []
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '面板数据读取失败', 'error')
  }
}

onMounted(async () => {
  await reloadAll()
  if (metrics.value.length) {
    await selectMetric(String(metrics.value[0].指标编号))
  }
})
</script>
