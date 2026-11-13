<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "指标口径", "created": 0, "pending": 0, "abnormal": 0}, {"name": "聚合查询", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分群分析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "实验设计", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析方案", "created": 0, "pending": 0, "abnormal": 0}, {"name": "看板配置", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据服务", "created": 0, "pending": 0, "abnormal": 0}, {"name": "漏斗分析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "同期群分析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "归因模型", "created": 0, "pending": 0, "abnormal": 0}, {"name": "指标预警", "created": 0, "pending": 0, "abnormal": 0}, {"name": "报表调度", "created": 0, "pending": 0, "abnormal": 0}, {"name": "维度属性", "created": 0, "pending": 0, "abnormal": 0}, {"name": "多维下钻", "created": 0, "pending": 0, "abnormal": 0}, {"name": "预测模型", "created": 0, "pending": 0, "abnormal": 0}, {"name": "标签管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "洞察推送", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据验证", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
