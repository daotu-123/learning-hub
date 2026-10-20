<template>
  <div class="login">
    <form class="card" @submit.prevent="onSubmit">
      <h1>学习中枢</h1>
      <p class="sub">登录后同步你的复习计划、笔记与工作台</p>

      <label class="field">
        <span>用户名</span>
        <input
          v-model="username"
          class="text-input"
          type="text"
          name="username"
          autocomplete="username"
          autocapitalize="off"
          autocorrect="off"
          spellcheck="false"
          placeholder="请输入用户名"
        >
      </label>

      <label class="field">
        <span>口令</span>
        <input
          v-model="password"
          class="text-input"
          type="password"
          name="password"
          autocomplete="current-password"
          placeholder="请输入口令"
        >
      </label>

      <p v-if="error" class="err">{{ error }}</p>

      <button class="btn-primary" type="submit" :disabled="busy || !canSubmit">
        {{ busy ? '登录中…' : '登录' }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { hasSession, saveSession } from '@/auth/session'
import { api } from '@/api/server'
import './login.css'

defineOptions({ name: 'LoginPage' })

const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

const canSubmit = computed(() => username.value.trim() !== '' && password.value !== '')

/**
 * next 必须是站内相对路径（防开放重定向）。
 * 拒绝：绝对 URL、协议相对 //host、带反斜杠的路径、以及任何非 / 开头的值。
 * 已经是站内路径时交给 router 处理，不手工拼字符串。
 */
function safeNext(): string {
  const raw = route.query.next
  const v = Array.isArray(raw) ? String(raw[0] || '') : String(raw || '')
  if (!v) return '/hub'
  if (v.charAt(0) !== '/') return '/hub'
  if (v.charAt(1) === '/') return '/hub'      // //evil.com
  if (v.indexOf('\\') >= 0) return '/hub'
  if (/^\/login/.test(v)) return '/hub'        // 别把自己送回登录页
  return v
}

async function onSubmit() {
  if (busy.value || !canSubmit.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await api<{ token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: username.value.trim(), password: password.value }),
    })
    if (!r || !r.token) throw new Error('登录响应缺少令牌')
    saveSession(r.token)
    password.value = ''
    await router.replace(safeNext())
  } catch (e: any) {
    // 后端已把"用户不存在"与"口令错"合成同一条消息与同一个 401，
    // 前端**不得**再自行区分，否则等于把区分能力又还给了攻击者。
    // 503（服务端还没建账号）是另一回事，那条是有指引价值的。
    if (e && e.status === 503) error.value = e.message || '服务端尚未创建账号'
    else error.value = '用户名或口令错误'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  // 已有会话就别停在登录页（双保险：路由守卫之外，页面自己再看一次）
  if (hasSession()) router.replace(safeNext())
})
</script>
