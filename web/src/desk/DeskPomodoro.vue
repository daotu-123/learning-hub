<template>
  <div class="page page-pomodoro">
    <div class="card">
      <div class="seg">
        <button class="seg-btn" :class="{ active: s.pomo.mode === 'focus' }" @click="switchMode('focus')">专注</button>
        <button class="seg-btn" :class="{ active: s.pomo.mode === 'break' }" @click="switchMode('break')">休息</button>
      </div>
      <div class="timer-wrap">
        <svg class="timer-ring" viewBox="0 0 200 200">
          <circle class="ring-bg" cx="100" cy="100" r="88" />
          <circle class="ring-fg" cx="100" cy="100" r="88" :style="{ strokeDashoffset: ringOffset }" />
        </svg>
        <div class="timer-center">
          <div class="timer-time">{{ timeText }}</div>
          <div class="timer-task">{{ s.pomo.task ? s.pomo.task.name : '未选择任务' }}</div>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn primary" @click="pomoToggle">{{ s.pomo.running ? '暂停' : '开始' }}</button>
        <button class="btn plain" @click="pomoReset">重置</button>
        <button class="btn plain" @click="pomoSkip">跳过</button>
      </div>
      <div class="today-stats">{{ s.pomoToday }}</div>
    </div>

    <div class="card">
      <div class="card-head"><span>任务</span><span class="muted sm">{{ s.tasks.length }} 个</span></div>
      <div class="task-input-row">
        <input class="text-input task-input" v-model="s.taskInput" placeholder="添加任务，完成后自动勾选…" @keydown.enter="addTask" />
        <button class="btn primary sm" @click="addTask">添加</button>
      </div>
      <div class="task-list">
        <div v-if="!s.tasks.length" class="empty">暂无任务</div>
        <div v-for="(t, i) in s.tasks" :key="i" class="task-item" :class="{ done: t.done }">
          <button class="task-check" @click="toggleTask(i)">✓</button>
          <button class="task-name" :class="{ active: s.pomo.task && s.pomo.task.file === t.file }" @click="pickTask(t)">
            {{ t.priority === 'high' ? '🔥 ' : t.priority === 'medium' ? '· ' : '' }}{{ t.name }}
          </button>
          <button class="task-del" @click="deleteTask(i)">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import {
  deskState as s, pomoToggle, pomoReset, pomoSkip, pomoSwitchMode,
  addTask, toggleTask, deleteTask,
} from './store'

defineOptions({ name: 'DeskPomodoro' })

const CIRC = 2 * Math.PI * 88
const remain = computed(() => {
  if (s.pomo.running && s.pomo.endAt) return Math.max(0, Math.round((s.pomo.endAt - Date.now()) / 1000))
  return s.pomo.remainSec
})
const timeText = computed(() => {
  const r = remain.value
  return String(Math.floor(r / 60)).padStart(2, '0') + ':' + String(r % 60).padStart(2, '0')
})
const ringOffset = computed(() => {
  const pct = s.pomo.totalSec ? (1 - remain.value / s.pomo.totalSec) : 0
  return (CIRC * (1 - Math.max(0, Math.min(1, pct)))).toFixed(1)
})

function switchMode(mode: string) { pomoSwitchMode(mode) }
function pickTask(t: any) {
  if (t.done) return
  s.pomo.task = (s.pomo.task && s.pomo.task.file === t.file) ? null : t
}

/* 页面隐藏再切回时立即校正（store 内定时器负责推进，这里驱动 UI 重算） */
let uiTimer: any = null
onMounted(() => { uiTimer = setInterval(() => { /* 触发 computed 重算 */ }, 1000) })
onUnmounted(() => { if (uiTimer) clearInterval(uiTimer) })
</script>
