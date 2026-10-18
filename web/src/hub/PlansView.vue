<template>
  <div class="card">
    <div class="card-head"><span>计划进度（近 7 天）</span><span class="tag">日记 + 自建</span></div>
    <div class="plan-add">
      <input class="text-input" v-model="hubState.planNewName" placeholder="自建计划，如：每天单词 30 个" maxlength="40" @keydown.enter="onAdd">
      <button class="om-btn" @click="onAdd">添加</button>
    </div>
    <div v-if="!items.length" class="empty">近 7 天没有计划进度记录<br>可在上方添加自建计划，每天打卡跟进</div>
    <template v-else>
      <div class="plan-item" v-for="(it, i) in items" :key="i">
        <div class="plan-name">
          <span>{{ it.name }}<em v-if="it.custom" class="plan-mine">自建</em></span>
          <span class="p">{{ it.doneCount }}/{{ it.total }}{{ it.custom ? ' 天打卡' : ' 天有推进' }}{{ it.last && !it.custom ? ' · 最新：' + it.last.progress : '' }}</span>
        </div>
        <div class="plan-bar"><i :style="{ width: it.pct + '%' }"></i></div>
        <div class="plan-seq">
          <span
            v-for="(d, j) in it.days"
            :key="j"
            class="day"
            :class="{ hit: !!d.progress, tappable: it.custom && d.date === hubState.date }"
            :title="d.date"
            @click="it.custom && d.date === hubState.date ? onToggleDay(it, d) : undefined"
          ><b>{{ d.progress || '—' }}</b></span>
          <button v-if="it.custom" class="plan-del" title="删除计划" @click="onDelete(it)">×</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { hubState, plansView, planAdd, planToggleDay, planDelete, showToast } from './hubStore'

defineOptions({ name: 'PlansView' })

const items = computed(() => plansView())

async function onAdd() {
  const name = hubState.planNewName.trim()
  if (!name) { showToast('先填计划名'); return }
  try {
    await planAdd(name)
    hubState.planNewName = ''
  } catch (e: any) { showToast('添加失败：' + e.message) }
}

/* 自建计划：今日打卡 / 取消（乐观更新，失败还原） */
async function onToggleDay(it: any, d: any) {
  const willDone = !d.done
  const prevProgress = d.progress
  d.done = willDone
  d.progress = willDone ? '已完成' : ''
  try {
    await planToggleDay(it.id, d.date, willDone)
  } catch (e: any) {
    d.done = !willDone
    d.progress = prevProgress
    showToast('同步失败，已还原')
  }
}

async function onDelete(it: any) {
  if (!confirm('删除计划「' + it.name + '」？打卡记录会一起删除。')) return
  try { await planDelete(it.id) }
  catch (e: any) { showToast('删除失败：' + e.message) }
}
</script>
