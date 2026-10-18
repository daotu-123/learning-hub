<template>
  <div class="grid cols-2">
    <div class="card">
      <div class="card-head"><span>番茄钟</span><span class="tag" :style="{ color: running ? 'var(--primary)' : 'var(--muted)' }">{{ statusText }}</span></div>
      <div class="pomo-dial-wrap">
        <div class="pomo-dial" id="pomoDial">
          <div class="pomo-time">{{ timeText }}</div>
          <div class="pomo-cycle">第 {{ hubState.pomo.cycle }} 轮</div>
        </div>
        <div class="pomo-modes">
          <button
            v-for="m in MODES"
            :key="m"
            :class="{ active: hubState.pomo.minutes === m }"
            @click="pomoSetMinutes(m)"
          >{{ m }} 分</button>
        </div>
        <input v-model="pomoTask" type="text" class="text-input" id="pomoTask" placeholder="这次专注做什么？（可选）" maxlength="60">
        <div class="pomo-actions">
          <button class="btn btn-primary pomo-start" :class="{ running: running }" @click="pomoToggleStart()">{{ startText }}</button>
          <button v-if="hubState.pomo.remain < hubState.pomo.total" class="btn btn-ghost" @click="pomoReset()">重置</button>
        </div>
      </div>
    </div>
    <div>
      <div class="card" style="margin-bottom:14px">
        <div class="card-head"><span>今日专注</span><span class="tag">自动记录</span></div>
        <div class="pomo-today">
          <div class="cell"><div class="v">{{ today.count }}</div><div class="k">今日番茄</div></div>
          <div class="cell"><div class="v">{{ today.focus_min }}</div><div class="k">今日分钟</div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><span>近 7 天专注趋势</span><span class="tag">{{ totalText }}</span></div>
        <div class="focus-chart">
          <div
            v-for="(b, i) in chart"
            :key="i"
            class="focus-bar-wrap"
            :title="b.tip"
          >
            <span class="v">{{ b.focus_min || '' }}</span>
            <div class="focus-bar" :style="{ height: b.h + '%', outline: b.isToday ? '1.5px solid var(--primary)' : 'none' }"></div>
            <span class="d">{{ b.wd }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  hubState, pomoToggleStart, pomoReset, pomoSetMinutes, pomoVisibilityFix,
  focusTodayView, focusTotalView, focusChartView,
} from './hubStore'

defineOptions({ name: 'FocusView' })

const MODES = [25, 45, 60]
const pomoTask = ref('')
const running = computed(() => hubState.pomo.running)
const timeText = computed(() => {
  const s = Math.max(0, hubState.pomo.remain)
  const m = Math.floor(s / 60), r = s % 60
  return String(m).padStart(2, '0') + ':' + String(r).padStart(2, '0')
})
const statusText = computed(() =>
  hubState.pomo.running ? '专注中' : (hubState.pomo.remain < hubState.pomo.total ? '已暂停' : '待开始'))
const startText = computed(() =>
  hubState.pomo.running ? '暂停' : (hubState.pomo.remain < hubState.pomo.total ? '继续' : '开始专注'))
const today = computed(() => focusTodayView())
const totalText = computed(() => focusTotalView())
const chart = computed(() => focusChartView())

/* 页面从后台切回时立即校正（补上后台节流期间的时间） */
onMounted(() => document.addEventListener('visibilitychange', pomoVisibilityFix))
onUnmounted(() => document.removeEventListener('visibilitychange', pomoVisibilityFix))
</script>
