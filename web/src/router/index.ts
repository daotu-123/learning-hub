import { createRouter, createWebHashHistory } from 'vue-router'
import HubPage from '@/hub/HubPage.vue'
import DeskPage from '@/desk/DeskPage.vue'

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
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
