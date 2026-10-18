<template>
  <div class="page page-overview">
    <div class="greet-row">
      <div>
        <div class="greet">{{ greet }}</div>
        <div class="date-line">{{ dateLine }}</div>
        <div class="sync-status" :class="{ offline: !s.sync.online }">{{ syncText }}</div>
      </div>
      <button class="sync-btn" :class="{ spinning: syncing }" @click="onSync">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg>
        同步
      </button>
    </div>

    <!-- AI 快捷输入条 -->
    <div class="ai-quickbar">
      <input class="text-input ai-quick-input" v-model="aiQuick" placeholder="问问 AI：总结今天 / 明日计划 / 薄弱点…" @keydown.enter="quickAsk" />
      <button class="btn primary ai-send" @click="quickAsk" aria-label="发送">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>

    <!-- 今日焦点 -->
    <div class="card">
      <div class="card-head"><span>今日焦点</span></div>
      <div class="focus-grid">
        <div class="focus-item" @click="goTab('pomodoro')">
          <div class="focus-label">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/></svg>
            番茄
          </div>
          <div class="focus-val">{{ s.focusPomo }}</div>
        </div>
        <div class="focus-item" @click="goTab('health')">
          <div class="focus-label">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            睡眠
          </div>
          <div class="focus-val">{{ s.focusSleep }}</div>
        </div>
        <div class="focus-item" @click="goTab('health')">
          <div class="focus-label">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6h12v12H6z"/><path d="M9 9h6v6H9z"/></svg>
            运动
          </div>
          <div class="focus-val">{{ s.focusEx }}</div>
        </div>
      </div>
      <div class="focus-row">
        <div class="focus-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          今日目标
        </div>
        <div class="focus-text">{{ s.focusTask }}</div>
      </div>
      <div class="focus-row">
        <div class="focus-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          今日收藏
        </div>
        <div class="focus-text">{{ s.focusFav }}</div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="quick-grid">
      <button class="quick-item" @click="goTab('diary')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
        <span>日记</span>
      </button>
      <button class="quick-item" @click="goTab('pomodoro')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/></svg>
        <span>专注</span>
      </button>
      <button class="quick-item" @click="goTab('health')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
        <span>健康</span>
      </button>
      <button class="quick-item" @click="goTab('fav')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        <span>收藏</span>
      </button>
      <button class="quick-item" @click="goTab('ai')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
        <span>AI</span>
      </button>
      <button class="quick-item" @click="pushPage('photos')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
        <span>照片</span>
      </button>
    </div>

    <div class="card" @click="goTab('diary')">
      <div class="card-head">
        <span>今日日记</span>
        <span class="card-arrow">›</span>
      </div>
      <div class="diary-preview">{{ s.diaryPreview }}</div>
    </div>

    <button class="btn plain block" @click="generateDailyReport">生成今日日报 → 同步 Obsidian</button>

    <div class="card">
      <div class="card-head"><span>DeepTutor</span></div>
      <div class="fav-summary">{{ s.deptSummary }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { deskState as s, goTab, pushPage, generateDailyReport, updateSyncStatus, checkConnection, syncAll, loadOverview, toast } from './store'

defineOptions({ name: 'DeskOverview' })

const syncing = ref(false)
const aiQuick = ref('')
const syncText = computed(() => updateSyncStatus().text)

const now = new Date()
const greet = now.getHours() < 6 ? '夜深了' : now.getHours() < 12 ? '早上好' : now.getHours() < 18 ? '下午好' : '晚上好'
const dateLine = (now.getMonth() + 1) + '月' + now.getDate() + '日 · 周' + ['日', '一', '二', '三', '四', '五', '六'][now.getDay()]

async function onSync() {
  syncing.value = true
  try {
    if (s.sync.online) await syncAll()
    else await checkConnection()
    loadOverview()
  } finally {
    syncing.value = false
  }
}
function quickAsk() {
  const v = aiQuick.value.trim()
  if (!v) { goTab('ai'); return }
  aiQuick.value = ''
  goTab('ai')
  setTimeout(() => {
    ;(window as any).__deskAiAsk?.(v)
  }, 120)
}

onMounted(() => { loadOverview() })
</script>
