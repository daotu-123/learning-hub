<template>
  <div class="qbank">
    <header>
      <div class="wrap">
        <div class="brand">
          <svg width="36" height="36" viewBox="0 0 108 108" aria-hidden="true">
            <rect width="108" height="108" rx="22" fill="#1b2530"/>
            <g fill="none" stroke="#e8a020" stroke-width="7" stroke-linecap="round">
              <path d="M54 34v-9M54 83v-9M34 54h-9M83 54h-9M40 40l-6.5-6.5M74.5 74.5L68 68M68 40l6.5-6.5M33.5 74.5L40 68"/>
              <circle cx="54" cy="54" r="17"/>
            </g>
            <path d="M47 54.5l5.5 5.5L63 49" fill="none" stroke="#ffffff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <div>
            <h1>机械题库</h1>
            <div class="sub">本地刷题 · 艾宾浩斯复习 · 知识点卡片</div>
          </div>
          <span class="mode-pill offline">离线模式</span>
        </div>
      </div>
    </header>
    <nav>
      <div class="wrap row qb-navrow">
        <a v-for="t in tabs" :key="t.key" href="javascript:;" :class="{ active: view === t.key }"
           @click.prevent="goView(t.key)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
               stroke-linecap="round" stroke-linejoin="round" v-html="t.icon" />
          {{ t.label }}
        </a>
      </div>
    </nav>
    <main class="wrap">
      <component :is="viewComp" />
      <footer>mech-qbank · 数据来自本地题库，只读源库 · 进度与自定义题库存在本机</footer>
    </main>
  </div>
</template>

<script setup lang="ts">
/* QbankPage.vue — 题库外壳：品牌头（离线徽章）+ 五页导航 + 视图切换
 *
 * 合并单 App 后不再独立使用路由切页：五页在组件内切换（bus.ts 的 view），
 * 深度链 #/qbank/stats 只在首次挂载时定位。keep-alive 由 App.vue 负责，会话状态在模块 store。
 */
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import './qbank.css'
import 'element-plus/dist/index.css'
import { view, goView } from './bus'
import type { QbView } from './bus'
import QbankQuiz from './QbankQuiz.vue'
import QbankReview from './QbankReview.vue'
import QbankWrong from './QbankWrong.vue'
import QbankCards from './QbankCards.vue'
import QbankStats from './QbankStats.vue'

defineOptions({ name: 'QbankPage' })

const route = useRoute()

const tabs: { key: QbView; label: string; icon: string }[] = [
  { key: 'quiz', label: '刷题', icon: '<path d="M4 5h16M4 12h10M4 19h7"/>' },
  { key: 'review', label: '今日复习', icon: '<path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5"/>' },
  { key: 'wrong', label: '错题', icon: '<path d="M6 6l12 12M18 6L6 18"/>' },
  { key: 'cards', label: '知识点', icon: '<path d="M4 5h7v14H4zM13 5h7v14h-7z"/>' },
  { key: 'stats', label: '进度', icon: '<path d="M5 20V10M12 20V4M19 20v-7"/>' },
]

const comps: Record<QbView, any> = {
  quiz: QbankQuiz,
  review: QbankReview,
  wrong: QbankWrong,
  cards: QbankCards,
  stats: QbankStats,
}
const viewComp = computed(() => comps[view.value] || QbankQuiz)

onMounted(() => {
  const v = route.params.view as string
  if (v && comps[v as QbView]) goView(v as QbView)
})
</script>

<style scoped>
/* 合并单 App 后：原 body 滚动改为页内滚动（底部还有三 Tab 导航） */
.qbank {
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
}
.qbank nav a.active {
  color: var(--steel-deep);
  border-bottom-color: var(--steel);
  font-weight: 600;
}
.qbank nav a.active svg { opacity: 1; }
/* 五个导航项在窄屏（390px）一行放不下：不换行、改为可横向滑动，视觉上仍是一排 Tab */
.qb-navrow {
  gap: 0;
  flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.qb-navrow::-webkit-scrollbar { display: none; }
/* 紧凑排版：390px 宽下五项正好放下；更窄的机型（360）仍可横滑 */
.qb-navrow a { flex: none; padding: 11px 7px; font-size: 13px; gap: 4px; }
</style>
