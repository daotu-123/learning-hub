import { createRouter, createWebHashHistory } from 'vue-router'
import HubPage from '@/hub/HubPage.vue'
import DeskPage from '@/desk/DeskPage.vue'
import { hasSession, setUnauthorizedHandler } from '@/auth/session'

const routes = [
  { path: '/', redirect: '/hub' },
  { path: '/hub', name: 'hub', component: HubPage, meta: { tab: 'hub' } },
  { path: '/hub/:view', name: 'hub-view', component: HubPage, meta: { tab: 'hub' } },
  /* 题库含 Element Plus（约 1MB JS + 400KB CSS），按需加载：首屏只拉学习中枢 */
  {
    path: '/qbank', name: 'qbank', meta: { tab: 'qbank' },
    component: () => import('@/qbank/QbankPage.vue'),
  },
  {
    path: '/qbank/:view', name: 'qbank-view', meta: { tab: 'qbank' },
    component: () => import('@/qbank/QbankPage.vue'),
  },
  { path: '/desk', name: 'desk', component: DeskPage, meta: { tab: 'desk' } },
  { path: '/desk/:view', name: 'desk-view', component: DeskPage, meta: { tab: 'desk' } },
  /* 登录页懒加载：已登录的人永远不需要下载它 */
  {
    path: '/login', name: 'login', meta: { public: true },
    component: () => import('@/auth/LoginView.vue'),
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

/* ---------------- M2b 会话守卫 ----------------
   规则刻意保持"薄"：只看本地有没有会话，不在这里联网校验。
   有效性由服务端回答——首个 401 会清会话并把你送回登录页，
   那样就不需要任何"静默刷新令牌"的机制（服务端也没有刷新端点）。 */
router.beforeEach((to) => {
  if (to.path === '/login') {
    // 已有会话时访问 /login → 直接去目标页，不让人再登一次
    if (hasSession()) {
      const raw = to.query.next
      const v = Array.isArray(raw) ? String(raw[0] || '') : String(raw || '')
      const target = v && v.charAt(0) === '/' && v.charAt(1) !== '/' && v.indexOf('\\') < 0 && !/^\/login/.test(v) ? v : '/hub'
      return target
    }
    return true
  }
  if (!hasSession()) {
    return { path: '/login', query: to.fullPath && to.fullPath !== '/' ? { next: to.fullPath } : {} }
  }
  return true
})

/**
 * 401 → 跳登录页（session.handleUnauthorized 已经清掉令牌，这里只管跳）。
 * 登录页自身的 401（口令错）**不跳**，否则会形成
 * /login → 401 → /login?next=/login 的死循环。
 */
setUnauthorizedHandler(() => {
  if (router.currentRoute.value.path === '/login') return
  const next = router.currentRoute.value.fullPath
  router.push({ path: '/login', query: next && next !== '/' ? { next } : {} }).catch(() => { /* 已在登录页 */ })
})

export default router
