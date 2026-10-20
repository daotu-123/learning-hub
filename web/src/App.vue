<template>
  <div class="shell" :class="'theme-' + activeTab">
    <div class="shell-body">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" :key="route.path" />
        </keep-alive>
      </router-view>
    </div>
    <nav class="shell-nav" v-if="!isLogin">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="shell-tab"
        :class="{ active: activeTab === t.key }"
        @click="goTab(t.key)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="t.icon" />
        <span>{{ t.label }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { checkWebUpdate } from '@/native/hotupdate'

const route = useRoute()
const router = useRouter()

const tabs = [
  {
    key: 'hub',
    label: '学习中枢',
    icon: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  },
  {
    key: 'qbank',
    label: '题库',
    icon: '<rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M8.5 7.5h7M9 11.5v.2M12 11.5v.2M15 11.5v.2M9 15v.2M12 15v.2M15 15v.2"/>',
  },
  {
    key: 'desk',
    label: '工作台',
    icon: '<rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>',
  },
]

const activeTab = computed(() => (route.meta.tab as string) || 'hub')
/* 登录页没有底部导航（也没有 hub 主题） */
const isLogin = computed(() => route.path === '/login')

/* APK 内：连上服务端时比对网页版本，有新版则热更新并重载（Web 端为空操作） */
onMounted(() => { checkWebUpdate() })

function goTab(key: string) {
  if (activeTab.value === key) return
  router.push('/' + key)
}
</script>

<style scoped>
.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #0c1f19;
}
.shell.theme-qbank, .shell.theme-desk { background: #f4f6f8; }
.shell-body {
  flex: 1;
  min-height: 0;
  position: relative;
}
.shell-body > * { height: 100%; }

/* ── 底部三 Tab 导航（原三 App 的合并入口） ── */
.shell-nav {
  display: flex;
  flex-shrink: 0;
  background: rgba(12, 31, 25, 0.92);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-bottom: var(--safe-bottom);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  z-index: 50;
}
.theme-qbank .shell-nav, .theme-desk .shell-nav {
  background: rgba(255, 255, 255, 0.94);
  border-top-color: #e5e7eb;
}
.shell-tab {
  flex: 1;
  border: none;
  background: transparent;
  color: #a0bdb2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 7px 0 8px;
  font-size: 11px;
  cursor: pointer;
  transition: color 0.15s;
}
.shell-tab svg { width: 21px; height: 21px; }
.shell-tab.active { color: #d7ef83; font-weight: 600; }
.theme-qbank .shell-tab, .theme-desk .shell-tab { color: #6b7280; }
.theme-qbank .shell-tab.active, .theme-desk .shell-tab.active { color: #2b6cb0; }
</style>
