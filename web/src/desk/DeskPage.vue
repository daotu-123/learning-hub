<template>
  <div class="desk">
    <!-- 顶部栏 -->
    <header class="topbar">
      <button class="back-btn" :class="{ show: s.stack.length > 0 }" @click="goBack()" aria-label="返回">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <div class="topbar-title">{{ PAGE_TITLES[s.page] || s.page }}</div>
      <div class="topbar-right">
        <span class="conn-dot" :class="{ ok: s.sync.online }"></span>
        <button class="icon-btn" @click="pushPage('settings')" aria-label="设置">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </div>
    </header>

    <!-- 内容区：6 Tab + 二级页（照片/设置） -->
    <main class="content" ref="contentEl">
      <transition name="page">
        <component :is="activeComp" :key="s.page" />
      </transition>
    </main>

    <!-- 底部导航 -->
    <nav class="tabbar">
      <button v-for="t in TABS" :key="t" class="tab" :class="{ active: s.page === t }" @click="goTab(t)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="TAB_ICONS[t]" />
        <span>{{ TAB_LABELS[t] }}</span>
      </button>
    </nav>

    <!-- toast -->
    <div v-if="toast.show" class="desk-toast">{{ toast.msg }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onMounted, onUnmounted, ref } from 'vue'
import './desk.css'
import {
  PAGE_TITLES, TABS, deskState as s, toastState as toast,
  initDesk, goTab, pushPage, goBack, showPage, onBackgroundChanged,
} from './store'
import DeskOverview from './DeskOverview.vue'
import DeskDiary from './DeskDiary.vue'
import DeskPomodoro from './DeskPomodoro.vue'
import DeskHealth from './DeskHealth.vue'
import DeskFav from './DeskFav.vue'
import DeskAi from './DeskAi.vue'
import DeskPhotos from './DeskPhotos.vue'
import DeskSettings from './DeskSettings.vue'

defineOptions({ name: 'DeskPage' })

const TAB_LABELS: Record<string, string> = {
  overview: '概览', diary: '日记', pomodoro: '专注', health: '健康', fav: '收藏', ai: 'AI',
}
const TAB_ICONS: Record<string, string> = {
  overview: '<rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>',
  diary: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  pomodoro: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/>',
  health: '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
  fav: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  ai: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
}
const PAGE_COMPS: Record<string, any> = {
  overview: DeskOverview, diary: DeskDiary, pomodoro: DeskPomodoro,
  health: DeskHealth, fav: DeskFav, ai: DeskAi, photos: DeskPhotos, settings: DeskSettings,
}
const activeComp = computed(() => markRaw(PAGE_COMPS[s.page] || DeskOverview))

/* 左右滑动切 Tab（简化版：识别横向滑动即切换，去掉跟手渲染） */
const contentEl = ref<HTMLElement>()
let touch: { x: number; y: number } | null = null
function onTouchStart(e: TouchEvent) {
  if (e.touches.length !== 1) return
  const el = document.activeElement
  if (el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT')) return
  if (TABS.indexOf(s.page) < 0) return
  touch = { x: e.touches[0].clientX, y: e.touches[0].clientY }
}
function onTouchEnd(e: TouchEvent) {
  if (!touch) return
  const dx = e.changedTouches[0].clientX - touch.x
  const dy = e.changedTouches[0].clientY - touch.y
  touch = null
  if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return
  const idx = TABS.indexOf(s.page)
  const nIdx = idx + (dx < 0 ? 1 : -1)
  if (nIdx < 0 || nIdx >= TABS.length) return
  goTab(TABS[nIdx])
}

/* 系统返回键：页面栈优先 */
function goBackApp(): string {
  if (s.stack.length > 0) { goBack(); return 'ok' }
  return 'none'
}

onMounted(() => {
  initDesk()
  contentEl.value?.addEventListener('touchstart', onTouchStart, { passive: true })
  contentEl.value?.addEventListener('touchend', onTouchEnd, { passive: true })
  ;(window as any).__onBackgroundChanged = onBackgroundChanged
  ;(window as any).__goBackApp = goBackApp
})
onUnmounted(() => {
  contentEl.value?.removeEventListener('touchstart', onTouchStart)
  contentEl.value?.removeEventListener('touchend', onTouchEnd)
})
</script>

<style scoped>
/* 页面切换动画（替代原跟手拖拽渲染，交互等价） */
.page-enter-active { animation: deskIn .26s ease; }
@keyframes deskIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
</style>
