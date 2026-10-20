<template>
  <div class="hub" :data-scene="hubScene">
    <div class="wp-layer" id="wpLayer"></div>
    <div class="bg-glow"></div>
    <div class="app">

      <!-- 顶部 -->
      <header class="hero">
        <div class="hero-row">
          <div>
            <p class="eyebrow">{{ hubTodayLabel }}</p>
            <h1>学习<span style="color:var(--primary)">中枢</span></h1>
            <p class="slogan">{{ slogan }}</p>
          </div>
          <div class="scene-switch">
            <button
              v-for="sc in sceneKeys"
              :key="sc"
              :class="{ active: hubScene === sc }"
              @click="setScene(sc)"
            >{{ SCENE_LABELS[sc] }}</button>
          </div>
          <button class="gear-btn" title="自定义设置" aria-label="设置" @click="onOpenSettings">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </div>
      </header>

      <nav class="nav">
        <button
          v-for="n in NAV_ITEMS"
          :key="n.view"
          :class="{ active: hubState.view === n.view }"
          @click="onNav(n.view)"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" v-html="n.icon" />
          {{ n.label }}
        </button>
      </nav>

      <div v-if="hubState.err" class="err-box">⚠️ {{ hubState.err }}</div>
      <div id="loading" v-if="hubState.loading"><div class="spinner"></div>加载数据中…</div>

      <!-- 七个视图常驻 DOM（.view/.active 由 CSS 控制显隐），
           保证番茄钟 DOM（#pomoDial/#pomoTask）在后台运行时仍在 -->
      <section class="view" :class="{ active: hubState.view === 'today' }" id="view-today">
        <TodayView />
      </section>
      <section class="view" :class="{ active: hubState.view === 'plans' }" id="view-plans">
        <PlansView />
      </section>
      <section class="view" :class="{ active: hubState.view === 'review' }" id="view-review">
        <ReviewView />
      </section>
      <section class="view" :class="{ active: hubState.view === 'focus' }" id="view-focus">
        <FocusView />
      </section>
      <section class="view" :class="{ active: hubState.view === 'feedback' }" id="view-feedback">
        <FeedbackView />
      </section>
      <section class="view" :class="{ active: hubState.view === 'library' }" id="view-library">
        <LibraryView />
      </section>
      <section class="view" :class="{ active: hubState.view === 'classroom' }" id="view-classroom">
        <ClassroomView />
      </section>

    </div>

    <!-- 设置面板 -->
    <div class="modal-mask" :class="{ show: settingsOpen }" @click.self="settingsOpen = false">
      <div class="modal">
        <h3>自定义设置</h3>
        <p class="sub">设置保存在 PC 端，手机打开同步生效</p>

        <div class="set-group">
          <label>壁纸</label>
          <div class="wp-grid">
            <div
              v-for="wp in wpItems"
              :key="wp.key"
              class="wp-item"
              :class="{ active: wp.active }"
              @click="setSettingWallpaper(wp.key)"
            >
              <div class="thumb" :style="{ background: wp.bg }"></div>
              <div class="nm">{{ wp.label }}</div>
            </div>
            <label class="wp-upload">📷 上传自定义壁纸<input type="file" accept="image/*" @change="onWpUpload"></label>
          </div>
        </div>

        <div class="set-group">
          <label>强调色</label>
          <div class="color-row">
            <span
              v-for="c in ACCENT_PRESETS"
              :key="c"
              class="color-dot"
              :class="{ active: curAccent === c }"
              :style="{ background: c, color: c }"
              :title="c"
              @click="setSettingAccent(c)"
            ></span>
            <span class="color-custom"><input type="color" :value="curAccent" @input="onCustomColor"></span>
          </div>
        </div>

        <div class="set-group">
          <label>玻璃透明度（卡片透出壁纸的程度）</label>
          <div class="range-row">
            <input type="range" min="20" max="90" :value="curGlass" @input="onGlass">
            <span class="range-val">{{ curGlass }}%</span>
          </div>
        </div>

        <div class="set-group">
          <label>标语（留空 = 用场景默认）</label>
          <input type="text" class="text-input" v-model="sloganInput" placeholder="例如：让每一次专注，都留下生长的痕迹" maxlength="40">
        </div>

        <div class="set-group" v-if="IS_APP">
          <label>服务器地址（留空 = 用门户统一设置）</label>
          <input type="text" class="text-input" v-model="serverInput" placeholder="例如 http://192.168.1.8:8637" inputmode="url">
        </div>

        <div class="set-group" v-if="!IS_APP">
          <label>AI 助手 Key（DeepSeek，仅电脑端配置）</label>
          <input type="password" class="text-input" v-model="aiKeyInput" placeholder="sk-…（留空保存 = 清除）" autocomplete="off">
          <div class="modal-actions" style="margin-top:10px;justify-content:flex-start">
            <button class="btn btn-ghost" @click="onAiKeySave">保存 Key</button>
          </div>
          <p class="hint">{{ aiKeyHint }}</p>
        </div>

        <div class="set-group">
          <label>账号</label>
          <input type="password" class="text-input" v-model="oldPwd" placeholder="原口令" autocomplete="current-password">
          <input type="password" class="text-input" v-model="newPwd" placeholder="新口令（至少 12 位）" autocomplete="new-password" style="margin-top:8px">
          <input type="password" class="text-input" v-model="confirmPwd" placeholder="再输一遍新口令" autocomplete="new-password" style="margin-top:8px">
          <div class="modal-actions" style="margin-top:10px;justify-content:flex-start">
            <button class="btn btn-ghost" :disabled="pwdBusy" @click="onChangePassword">{{ pwdBusy ? '提交中…' : '修改口令' }}</button>
          </div>
          <p class="hint">{{ pwdMsg || '改口令会让其他设备全部下线。' }}</p>
          <div class="modal-actions" style="margin-top:12px;justify-content:flex-start">
            <button class="btn btn-ghost" @click="onLogout">退出登录</button>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn btn-ghost" @click="settingsOpen = false">取消</button>
          <button class="btn btn-primary" @click="onSave">保存</button>
        </div>
      </div>
    </div>

    <div class="saved-toast" :class="{ show: !!toastMsg }">{{ toastMsg }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TodayView from './TodayView.vue'
import PlansView from './PlansView.vue'
import ReviewView from './ReviewView.vue'
import FocusView from './FocusView.vue'
import FeedbackView from './FeedbackView.vue'
import LibraryView from './LibraryView.vue'
import ClassroomView from './ClassroomView.vue'
import {
  hubState, hubScene, slogan, hubTodayLabel, toast as toastMsg,
  setScene, showHubView, initHub, goBackApp, clearErr,
  openSettings, saveSettings, uploadWallpaper,
  setSettingWallpaper, setSettingAccent, setSettingGlass,
  saveAiKey, showErr, showToast,
  ACCENT_PRESETS, WP_GRADIENTS,
} from './hubStore'
import { IS_APP, getServer, setServer as saveServerAddr, api } from '@/api/server'
import { clearSession, saveSession } from '@/auth/session'
import './hub.css'

defineOptions({ name: 'HubPage' })

const route = useRoute()
const router = useRouter()

const SCENE_LABELS: Record<string, string> = { rain: '雨林', snow: '雪日', cloud: '暖云' }
const sceneKeys = Object.keys(SCENE_LABELS)

const NAV_ITEMS = [
  {
    view: 'today', label: '今日',
    icon: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  },
  {
    view: 'plans', label: '计划',
    icon: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
  },
  {
    view: 'review', label: '复习',
    icon: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  },
  {
    view: 'focus', label: '专注',
    icon: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/>',
  },
  {
    view: 'feedback', label: '反馈',
    icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  },
  {
    view: 'library', label: '知识库',
    icon: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  },
  {
    view: 'classroom', label: 'AI 课堂',
    icon: '<path d="M22 9L12 4 2 9l10 5 10-5z"/><path d="M6 11.5V17c0 1.7 2.7 3 6 3s6-1.3 6-3v-5.5"/>',
  },
]

function onNav(view: string) {
  clearErr()
  showHubView(view).catch((e: any) => showErr('加载失败：' + e.message))
}

/* ---------------- 设置面板 ---------------- */
const settingsOpen = ref(false)
const sloganInput = ref('')
const serverInput = ref('')
const aiKeyInput = ref('')
const aiKeyHint = ref('Key 保存在本机，手机端 AI 助手通过局域网使用。')

const curAccent = computed(() => (hubState.settings || {}).accent || '#d7ef83')
const curGlass = computed(() => (hubState.settings || {}).glass || 55)
const wpItems = computed(() => {
  const s: any = hubState.settings || {}
  const builtins = s.builtins || {}
  const items = Object.entries(builtins).map(([key, label]) => ({
    key,
    label: label as string,
    bg: WP_GRADIENTS[key] || 'linear-gradient(135deg,#333,#111)',
    active: s.wallpaper === key,
  }))
  // 当前自定义壁纸（如有）
  if (s.wallpaper && !builtins[s.wallpaper]) {
    items.push({ key: s.wallpaper, label: '自定义壁纸', bg: "url('" + s.wallpaper + "') center/cover", active: true })
  }
  return items
})

async function onOpenSettings() {
  const s = await openSettings()
  sloganInput.value = s.slogan || ''
  serverInput.value = getServer()
  if (!IS_APP) {
    try {
      const r = await fetch(getServer() + '/api/hub/aiconfig')
      const c = await r.json()
      aiKeyHint.value = c.configured ? ('当前 Key：' + (c.masked || '已配置')) : '尚未配置 Key'
    } catch (e) { /* noop */ }
  }
  settingsOpen.value = true
}
function onWpUpload(e: Event) {
  const file = (e.target as HTMLInputElement).files && (e.target as HTMLInputElement).files![0]
  if (file) uploadWallpaper(file)
}
function onCustomColor(e: Event) { setSettingAccent((e.target as HTMLInputElement).value) }
function onGlass(e: Event) { setSettingGlass(parseInt((e.target as HTMLInputElement).value, 10)) }

async function onSave() {
  if (IS_APP) {
    const ns = serverInput.value.trim().replace(/\/+$/, '')
    if (ns !== getServer()) { saveServerAddr(ns); location.reload(); return }
  }
  try {
    await saveSettings(sloganInput.value.trim())
    settingsOpen.value = false
  } catch (err: any) { showErr('保存失败：' + err.message) }
}
async function onAiKeySave() {
  try {
    const c: any = await saveAiKey(aiKeyInput.value)
    aiKeyInput.value = ''
    aiKeyHint.value = c.configured ? '已保存，AI 助手就绪' : '已清除 Key'
  } catch (err: any) { showErr('保存失败：' + err.message) }
}

/* ---------------- 账号（M2b）：登出 / 改口令 ---------------- */
const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const pwdBusy = ref(false)
const pwdMsg = ref('')

async function onLogout() {
  try {
    await api('/api/auth/logout', { method: 'POST' })
  } catch (e) {
    // 服务端不可达也要能登出：本地清干净比"留着等下次成功"更重要
  }
  clearSession()
  settingsOpen.value = false
  router.replace('/login')
}

async function onChangePassword() {
  pwdMsg.value = ''
  if (newPwd.value.length < 12) { pwdMsg.value = '新口令至少 12 位'; return }
  if (newPwd.value !== confirmPwd.value) { pwdMsg.value = '两次输入的新口令不一致'; return }
  pwdBusy.value = true
  try {
    const r = await api<{ token: string }>('/api/auth/password', {
      method: 'PUT',
      body: JSON.stringify({ old_password: oldPwd.value, new_password: newPwd.value }),
    })
    // 改口令会撤销全部旧会话，响应里带回来的新会话**必须立刻换上**，
    // 否则自己把自己踢下线。
    if (!r || !r.token) throw new Error('响应缺少新令牌')
    saveSession(r.token)
    oldPwd.value = ''; newPwd.value = ''; confirmPwd.value = ''
    pwdMsg.value = '已修改，其他设备已下线'
    showToast('口令已更新 ✓')
  } catch (err: any) {
    if (err && err.status === 401) pwdMsg.value = '原口令不正确'
    else if (err && err.status === 400) pwdMsg.value = err.message
    else pwdMsg.value = '修改失败：' + (err && err.message)
  } finally {
    pwdBusy.value = false
  }
}

/* ---------------- 生命周期 ---------------- */
onMounted(async () => {
  await initHub()
  // 深链：#/hub/review 直达对应视图
  const v = route.params.view as string
  if (v && v !== hubState.view) await showHubView(v)
  // 系统返回键：非今日视图先回今日，再交外壳处理
  ;(window as any).__goBackApp = () => goBackApp()
})
onUnmounted(() => {
  if ((window as any).__goBackApp) delete (window as any).__goBackApp
})
</script>
