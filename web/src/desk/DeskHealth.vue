<template>
  <div class="page page-health">
    <div class="card">
      <div class="card-head"><span>😴 睡眠</span></div>
      <div class="health-row">
        <div class="health-field">
          <label class="field-label">入睡</label>
          <input type="time" class="date-input" v-model="s.sleepStart" />
        </div>
        <div class="health-field">
          <label class="field-label">醒来</label>
          <input type="time" class="date-input" v-model="s.sleepEnd" />
        </div>
        <button class="btn primary sm health-btn" @click="addSleep">记录</button>
      </div>
      <div class="health-hint" v-if="s.sleepHint">{{ s.sleepHint }}</div>
    </div>

    <div class="card">
      <div class="card-head"><span>🏃 运动</span></div>
      <div class="health-row">
        <select class="date-input" v-model="s.exType">
          <option>跑步</option><option>健身</option><option>篮球</option>
          <option>羽毛球</option><option>骑行</option><option>其他</option>
        </select>
        <input type="number" class="date-input health-min" v-model="s.exMin" placeholder="分钟" min="1" />
        <button class="btn primary sm health-btn" @click="addEx">记录</button>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><span>今日健康</span></div>
      <div class="today-row">
        <div><div class="today-label">睡眠</div><div class="today-num sm-num">{{ s.healthSleepToday }}</div></div>
        <div><div class="today-label">运动</div><div class="today-num sm-num">{{ s.healthExToday }}</div></div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><span>近 7 天趋势</span></div>
      <div class="chart" v-if="chart" v-html="chart.svg"></div>
      <div v-else class="empty">暂无趋势数据</div>
      <div class="chart-legend"><span class="legend-dot" style="background:#2563eb"></span>睡眠 <span class="legend-dot" style="background:#10b981"></span>运动</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { deskState as s, loadHealth, calcSleepMin, recordHealth, fmtMin, healthChartView, toast } from './store'

defineOptions({ name: 'DeskHealth' })

const chart = computed(() => healthChartView())

function addSleep() {
  const mins = calcSleepMin(s.sleepStart, s.sleepEnd)
  recordHealth('sleep', '夜间睡眠', mins, s.sleepStart, s.sleepEnd)
  s.sleepHint = '睡眠 ' + fmtMin(mins)
}
function addEx() {
  const min = parseInt(s.exMin, 10)
  if (!min || min <= 0) { toast('请输入运动分钟数'); return }
  recordHealth('exercise', s.exType, min, '', '')
  s.exMin = ''
}

onMounted(() => { loadHealth() })
</script>
