/* ============================================================
   学习中枢状态层（TS 重写，替代原 hub.html 内联脚本）
   ============================================================ */
import { reactive, readonly, ref } from 'vue'
import { api, IS_APP, setServer as saveServerAddr, getServer, getToken } from '@/api/server'

/* ---------------- 基础 ---------------- */
export function localDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}
export function esc(s: any): string {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
}
export function fmtDate(d: string): string {
  return d.replace(/(\d{4})-(\d{2})-(\d{2})/, '$1.$2.$3')
}
function relPath(p: string): string {
  const i = p.indexOf('DeepTutor\\')
  return i >= 0 ? p.slice(i).replace(/\\/g, '/') : String(p).replace(/\\/g, '/')
}

const state = reactive({
  date: localDate(new Date()),
  view: 'today' as string,
  settings: null as any,
  err: '',
  loading: true,
  /* 今日 */
  today: null as any,
  tasks: [] as { index: number; done: boolean; title: string; score: number | null }[],
  heat: [] as any[],
  /* 复习 */
  review: null as any,
  /* 计划 */
  plans: null as any,
  planNewName: '',
  /* 专注 */
  focus: null as any,
  /* 反馈 */
  feedback: [] as any[],
  /* 知识库 */
  library: null as any,
  /* AI 课堂 */
  om: { docs: [] as any[], roots: [] as any[], sel: {} as Record<string, number>, root: '', q: '', mode: 'merge', limit: 100, jobs: [] as any[], status: null as any, starting: false },
  /* 番茄钟 */
  pomo: { total: 0, remain: 0, running: false, timer: null as any, minutes: 25, cycle: 1, endAt: 0 },
})

const SLOGANS: Record<string, string> = {
  rain: '在雨声中沉浸，让每一段专注都有节奏。',
  snow: '在雪落中入定，让每一段专注都安静而坚定。',
  cloud: '在暖云里呼吸，让每一段专注都松弛而专注。',
}
const WP_GRADIENTS: Record<string, string> = {
  none: 'linear-gradient(160deg,#0c1f19 0%,#16291f 100%)',
  rain: 'linear-gradient(160deg,#0c1f19 0%,#12331f 45%,#0a1f16 100%)',
  snow: 'linear-gradient(160deg,#1b2430 0%,#2a3a4e 50%,#141c26 100%)',
  cloud: 'linear-gradient(160deg,#141414 0%,#2b2621 50%,#111 100%)',
  forest: 'linear-gradient(135deg,#0d1f14 0%,#1d4d2b 40%,#0a2a14 70%,#081f10 100%)',
  aurora: 'linear-gradient(135deg,#0c1f2e 0%,#1e3a5f 35%,#3b2f63 60%,#0f1f2e 100%)',
  dusk: 'linear-gradient(135deg,#1a1424 0%,#4a2a1e 45%,#7a3b1e 75%,#140d0a 100%)',
}
export const ACCENT_PRESETS = ['#d7ef83', '#60a5fa', '#c084fc', '#f472b6', '#fbbf24', '#34d399']

// 服务器地址改为「每次调用时取」，不再是模块加载时的快照：
// 原写法 const SERVER = getServer() 会让用户改了服务器地址后仍打旧地址，直到重载页面。
function apiBase(): string {
  return getServer() + '/api/hub'
}

/** 带令牌的请求头。服务端对非回环请求要求 X-Token。 */
function hubHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const tok = getToken()
  if (tok) h['X-Token'] = tok
  return Object.assign(h, extra || {})
}

async function apiHub<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(apiBase() + path, Object.assign({}, opts, {
    headers: hubHeaders((opts as any).headers),
  }))
  if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + (await r.text()).slice(0, 200))
  return r.json()
}

/* ---------------- toast / err ---------------- */
const toastMsg = ref('')
let toastTimer: any = null
export function showToast(msg: string) {
  toastMsg.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastMsg.value = '' }, 2000)
}
export const toast = readonly(toastMsg)
export function showErr(msg: string) { state.err = msg }
export function clearErr() { state.err = '' }

/* ---------------- 场景 / 壁纸 / 自定义 ---------------- */
const sceneRef = ref('rain')
export function scene(): string { return sceneRef.value }

export function setScene(scene: string, persist = true) {
  sceneRef.value = scene
  const savedSlogan = state.settings && state.settings.slogan
  sloganText.value = savedSlogan || SLOGANS[scene] || ''
  if (persist) { try { localStorage.setItem('hub-scene', scene) } catch (e) { /* noop */ } }
}
const sloganText = ref(SLOGANS.rain)
export const slogan = readonly(sloganText)

function applyWallpaper() {
  const s = state.settings || {}
  const wp = s.wallpaper || 'rain'
  const layer = document.getElementById('wpLayer')
  if (!layer) return
  if (wp === 'none') {
    layer.style.backgroundImage = WP_GRADIENTS.none
    layer.style.opacity = '0'
  } else if (WP_GRADIENTS[wp]) {
    layer.style.backgroundImage = WP_GRADIENTS[wp]
    layer.style.opacity = '0.85'
  } else {
    layer.style.backgroundImage = 'url(' + JSON.stringify(wp) + ')'
    layer.style.opacity = '1'
  }
}
function applyAccent() {
  const c = (state.settings || {}).accent || '#d7ef83'
  document.documentElement.style.setProperty('--primary', c)
  document.documentElement.style.setProperty('--primary-fg', c === '#d7ef83' ? '#051612' : '#ffffff')
}
function applyGlass() {
  const g = (state.settings || {}).glass || 55
  document.documentElement.style.setProperty('--card', 'rgba(255,255,255,' + (g / 100 * 0.22).toFixed(3) + ')')
  document.documentElement.style.setProperty('--glass', 'rgba(12,31,25,' + (g / 100 * 0.85).toFixed(3) + ')')
}
export function applyAllCustom() {
  applyWallpaper(); applyAccent(); applyGlass()
}

/* ---------------- 设置面板 ---------------- */
export async function openSettings() {
  try {
    state.settings = await apiHub('/settings')
  } catch (err: any) {
    if (!IS_APP) { showErr('读取设置失败：' + err.message); return }
    state.settings = state.settings || {}
  }
  applyAllCustom()
  return state.settings
}
export async function saveSettings(sloganInput: string) {
  const body = {
    wallpaper: state.settings.wallpaper,
    accent: state.settings.accent,
    glass: state.settings.glass,
    slogan: sloganInput,
  }
  const r = await fetch(apiBase() + '/settings', {
    method: 'PUT', headers: hubHeaders(), body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  state.settings = await r.json()
  applyAllCustom()
  sloganText.value = state.settings.slogan || SLOGANS[sceneRef.value]
  showToast('已保存 ✓')
}
export async function uploadWallpaper(file: File) {
  if (file.size > 12 * 1024 * 1024) { showErr('图片超过 12MB，请压缩后再上传'); return }
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      const r = await fetch(apiBase() + '/wallpaper', {
        method: 'POST',
        headers: hubHeaders(),
        body: JSON.stringify({ data: reader.result }),
      })
      if (!r.ok) throw new Error(await r.text())
      const j = await r.json()
      state.settings = j.settings
      applyWallpaper()
      showToast('壁纸已上传 ✓')
    } catch (err: any) { showErr('上传失败：' + err.message) }
  }
  reader.readAsDataURL(file)
}
export function setSettingWallpaper(wp: string) { state.settings.wallpaper = wp; applyWallpaper() }
export function setSettingAccent(accent: string) { state.settings.accent = accent; applyAccent() }
export function setSettingGlass(g: number) { state.settings.glass = g; applyGlass() }
export async function saveAiKey(key: string) {
  const r = await fetch(apiBase() + '/aiconfig', {
    method: 'PUT', headers: hubHeaders(),
    body: JSON.stringify({ key: key.trim() }),
  })
  if (!r.ok) throw new Error((await r.json()).detail || ('HTTP ' + r.status))
  const c = await r.json()
  showToast(c.configured ? 'Key 已保存 ✓' : 'Key 已清除 ✓')
  return c
}

/* ---------------- 今日 ---------------- */
function parseTasks(content: string) {
  const out: { index: number; done: boolean; title: string; score: number | null }[] = []
  const re = /^\s*[-*]\s*\[([ xX])\]\s*(.+)$/gm
  let m, idx = 0
  while ((m = re.exec(content))) {
    const done = m[1].toLowerCase() === 'x'
    let title = m[2].trim()
    let score: number | null = null
    const sm = title.match(/[（(]\s*(\d+)\s*[）)]/)
    if (sm) score = parseInt(sm[1])
    out.push({ index: idx, done, title, score })
    idx++
  }
  return out
}

export function todayStatsView() {
  const t = state.today
  if (!t) return []
  const d = t.diary
  return [
    { v: d ? d.tasks_done : 0, u: d ? '/' + d.tasks_total : '', k: '今日任务', cls: 'pri' },
    { v: d ? d.score : 0, u: '分', k: '完成任务分', cls: 'green' },
    { v: t.review.due_today, u: '条', k: '复习到期', cls: 'red' },
    { v: t.score.total, u: '分', k: '累计积分', cls: 'amber' },
  ]
}

export async function loadToday() {
  const t = await apiHub('/today?date=' + state.date)
  state.today = t
  if (!t.diary) {
    state.tasks = []
  } else {
    let txt: any = { content: '' }
    try { txt = await (await fetch(getServer() + '/api/diary?date=' + state.date, { headers: hubHeaders() })).json() } catch (e) { /* noop */ }
    state.tasks = parseTasks(txt.content || '')
  }
  return t
}

/* 今日任务打勾同步：乐观更新，失败回滚 */
export async function toggleTask(index: number, done: boolean) {
  const t = state.tasks.find(x => x.index === index)
  if (t) t.done = done
  try {
    const j: any = await apiHub('/task', {
      method: 'POST',
      body: JSON.stringify({ date: state.date, index: index, done: done }),
    })
    if (j.diary) {
      state.today.diary = j.diary
    }
    showToast(done ? '已完成 ✓ 已同步' : '已取消勾选')
  } catch (err: any) {
    if (t) t.done = !done
    showToast('同步失败，已还原')
  }
}

/* 复习完成：写日记标记 + 推进艾宾浩斯间隔 */
export async function reviewDone(concept: string) {
  try {
    const j: any = await apiHub('/review-done', {
      method: 'POST',
      body: JSON.stringify({ concept: concept }),
    })
    if (j.already) {
      showToast('这条今天已推进过')
    } else {
      const nx = j.item && j.item.next_review ? (' · 下次 ' + j.item.next_review) : ''
      showToast('复习完成 ✓' + nx)
    }
    if (state.view === 'today') await loadToday()
    else if (state.view === 'review') await loadReview()
  } catch (err: any) {
    showToast('同步失败：' + err.message)
  }
}

export function todayNotesView() {
  const t = state.today
  if (!t) return []
  const notes = t.notes || {}
  const out: { kind: string; items: { name: string; path: string }[] }[] = []
  for (const [kind, items] of Object.entries(notes)) {
    if (!(items as any[]).length) continue
    out.push({
      kind,
      items: (items as any[]).map((i: any) => ({ name: i.name, path: i.path })),
    })
  }
  return out
}
export function obsidianFileUrl(path: string): string {
  return 'obsidian://open?vault=self-improve&file=' + encodeURIComponent(relPath(path))
}

/* ---------------- 热力图 ---------------- */
export async function loadHeat() {
  const ov = await apiHub('/overview?days=30')
  const data = ov.data
  const max = Math.max(...data.map((d: any) => d.tasks_done), 1)
  const lv = (d: any) => d.tasks_done === 0 ? '' : d.tasks_done > max * 0.75 ? ' l4' : d.tasks_done > max * 0.5 ? ' l3' : d.tasks_done > max * 0.25 ? ' l2' : ' l1'
  state.heat = data.map((d: any) => ({
    date: d.date,
    cls: d.exists ? lv(d) : '',
    tip: d.date + ' · 完成 ' + d.tasks_done + '/' + d.tasks_total + (d.score ? ' · +' + d.score + '分' : ''),
  }))
}

/* ---------------- 计划 ---------------- */
export async function loadPlans() {
  const p = await apiHub('/plans?days=7')
  state.plans = p
  return p
}
export function plansView() {
  const p = state.plans
  if (!p) return []
  const series = p.series
  if (!Object.keys(series).length) return []
  return Object.entries(series).map(([name, days]: [string, any]) => {
    const custom = days.some((d: any) => d.custom)
    const last = [...days].reverse().find((d: any) => d.progress) || null
    const doneCount = days.filter((d: any) => d.done).length
    const total = days.length
    const pct = Math.round(doneCount / total * 100)
    return {
      name, days, last, pct, doneCount, total, custom,
      id: (days.find((d: any) => d.id) || {}).id || '',
    }
  })
}
export async function planToggleDay(id: string, date: string, willDone: boolean) {
  await apiHub('/plan-toggle', {
    method: 'POST',
    body: JSON.stringify({ id: id, date: date, done: willDone }),
  })
  showToast(willDone ? '今日打卡 ✓' : '已取消打卡')
}
export async function planDelete(id: string) {
  await apiHub('/plan-delete', { method: 'POST', body: JSON.stringify({ id: id }) })
  showToast('已删除')
  await loadPlans()
}
export async function planAdd(name: string) {
  if (!name) { showToast('先填计划名'); return }
  await apiHub('/plan', { method: 'POST', body: JSON.stringify({ name: name }) })
  showToast('已添加计划 ✓ 点今天的格子即可打卡')
  await loadPlans()
}

/* ---------------- 复习 ---------------- */
export async function loadReview() {
  const r = await apiHub('/review')
  state.review = r
  return r
}
export function reviewStatsView() {
  const r = state.review
  if (!r) return []
  return [
    { v: r.total, u: '条', k: '总数', cls: '' },
    { v: r.active, u: '条', k: '进行中', cls: 'pri' },
    { v: r.due_today, u: '条', k: '今日到期', cls: 'red' },
    { v: r.done, u: '条', k: '已掌握', cls: 'green' },
  ]
}
export function revItemView(item: any) {
  const due = item.next_review && item.next_review <= state.date
  return {
    due,
    concept: item.concept,
    meta: '第 ' + (item.reviews || 0) + ' 次复习 · 间隔 ' + (item.interval_days || 1) + ' 天 · 下次 <b>' + esc(item.next_review || '—') + '</b>',
  }
}

/* ---------------- 专注 ---------------- */
function pomoFormat(s: number) {
  const m = Math.floor(s / 60), r = s % 60
  return String(m).padStart(2, '0') + ':' + String(r).padStart(2, '0')
}
export function pomoRender() {
  const P = state.pomo
  const pct = P.total > 0 ? ((P.total - P.remain) / P.total * 100).toFixed(1) : '0'
  const dial = document.getElementById('pomoDial')
  if (dial) dial.style.setProperty('--pomo-pct', pct + '%')
  document.title = (P.running ? '⏱ ' + pomoFormat(P.remain) + ' · ' : '') + '学习中枢 · Learning Hub'
}
function pomoPersist() {
  try {
    const P = state.pomo
    if (P.running) {
      localStorage.setItem('hub-pomo', JSON.stringify({
        endAt: P.endAt, total: P.total, minutes: P.minutes,
        cycle: P.cycle, task: (document.getElementById('pomoTask') as HTMLInputElement | null)?.value.trim() || '', running: true,
      }))
    } else {
      localStorage.removeItem('hub-pomo')
    }
  } catch (e) { /* noop */ }
}
function pomoTick() {
  const P = state.pomo
  if (!P.running) return
  P.remain = Math.max(0, Math.round((P.endAt - Date.now()) / 1000))
  pomoRender()
  if (P.remain <= 0) pomoComplete()
}
function pomoResumeFromStorage() {
  let saved: any = null
  try { saved = JSON.parse(localStorage.getItem('hub-pomo') || 'null') } catch (e) { /* noop */ }
  if (!saved || !saved.running || !saved.endAt) return
  const remain = Math.round((saved.endAt - Date.now()) / 1000)
  if (remain <= 0) {
    localStorage.removeItem('hub-pomo')
    fetch(apiBase() + '/focus', {
      method: 'POST',
      headers: hubHeaders(),
      body: JSON.stringify({ task: saved.task || '', minutes: saved.minutes || 25 }),
    }).then(() => showToast('上次的番茄已自动补记 ✓')).catch(() => { })
    return
  }
  state.pomo.minutes = saved.minutes || 25
  state.pomo.total = saved.total || saved.minutes * 60
  state.pomo.remain = remain
  state.pomo.cycle = saved.cycle || 1
  state.pomo.endAt = saved.endAt
  state.pomo.running = true
  const ta = document.getElementById('pomoTask') as HTMLInputElement | null
  if (ta && saved.task) ta.value = saved.task
  state.pomo.timer = setInterval(pomoTick, 1000)
  pomoRender()
}
async function pomoComplete() {
  const P = state.pomo
  P.running = false
  if (P.timer) { clearInterval(P.timer); P.timer = null }
  localStorage.removeItem('hub-pomo')
  const mins = P.minutes
  const ta = document.getElementById('pomoTask') as HTMLInputElement | null
  const task = ta ? ta.value.trim() : ''
  try {
    await fetch(apiBase() + '/focus', {
      method: 'POST',
      headers: hubHeaders(),
      body: JSON.stringify({ task: task, minutes: mins }),
    })
    showToast('专注完成 +' + mins + ' 分钟 ✓')
    await loadFocus()
  } catch (err: any) { showErr('记录失败：' + err.message) }
  P.cycle++
  P.total = P.minutes * 60
  P.remain = P.total
  pomoRender()
}
export function pomoToggleStart() {
  const P = state.pomo
  if (P.running) {
    P.running = false
    if (P.timer) { clearInterval(P.timer); P.timer = null }
    localStorage.removeItem('hub-pomo')
  } else {
    if (P.remain <= 0) { P.total = P.minutes * 60; P.remain = P.total }
    P.running = true
    P.endAt = Date.now() + P.remain * 1000
    P.timer = setInterval(pomoTick, 1000)
    pomoPersist()
  }
  pomoRender()
}
export function pomoReset() {
  const P = state.pomo
  P.running = false
  if (P.timer) { clearInterval(P.timer); P.timer = null }
  localStorage.removeItem('hub-pomo')
  P.total = P.minutes * 60
  P.remain = P.total
  pomoRender()
}
export function pomoSetMinutes(min: number) {
  const P = state.pomo
  if (P.running || P.remain < P.total) return
  P.minutes = min
  P.total = P.minutes * 60
  P.remain = P.total
  pomoRender()
}
export function pomoVisibilityFix() {
  const P = state.pomo
  if (!document.hidden && P.running) {
    P.remain = Math.max(0, Math.round((P.endAt - Date.now()) / 1000))
    pomoRender()
    if (P.remain <= 0) pomoComplete()
  }
}
export async function loadFocus() {
  const f = await apiHub('/focus?days=7')
  state.focus = f
  return f
}
export function focusTodayView() {
  const f = state.focus
  if (!f) return { count: 0, focus_min: 0 }
  return f.data[f.data.length - 1] || { count: 0, focus_min: 0 }
}
export function focusTotalView() {
  const f = state.focus
  return f ? ('7 天 ' + f.total_count + ' 个 · ' + f.total_min + ' 分钟') : ''
}
export function focusChartView() {
  const f = state.focus
  if (!f) return []
  const max = Math.max(...f.data.map((d: any) => d.focus_min), 1)
  const labels = ['一', '二', '三', '四', '五', '六', '日']
  return f.data.map((d: any, i: number) => {
    const h = Math.round(d.focus_min / max * 100)
    const wd = labels[(new Date(d.date).getDay() + 6) % 7]
    const isToday = i === f.data.length - 1
    return {
      date: d.date,
      count: d.count,
      focus_min: d.focus_min,
      h: d.focus_min ? h : 3,
      wd,
      isToday,
      tip: d.date + '：' + d.count + ' 个番茄 / ' + d.focus_min + ' 分钟',
    }
  })
}

/* ---------------- 反馈 ---------------- */
export async function loadFeedback() {
  const f = await apiHub('/feedback?n=5')
  state.feedback = f.items || []
}

/* ---------------- 知识库 ---------------- */
const LIB_ICONS: Record<string, string> = {
  '抖音收藏': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 9V5a8 8 0 0 1 8 8v3h-4v-3a4 4 0 0 0-4-4z"/><rect x="2" y="9" width="12" height="11" rx="2"/></svg>',
  '小红书收藏': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2l2.4 2.4L17 3l1 2.6 2.6 1-1 2.4L22 12l-2.4 2.4 1 2.4-2.6 1-1 2.6-2.6-1L12 22l-2.4-2.4-2.6 1-1-2.6-2.4-1 1-2.4L2 12l2.4-2.4-1-2.4 2.6-1L7 3l2.6 1z"/></svg>',
  '知乎收藏': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><path d="M9 8h6M9 12h6M9 16h4"/></svg>',
  'B站收藏': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 8h16v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8z"/><path d="M8 8V5a2 2 0 0 1 4 0v3"/><path d="M12 8V5a2 2 0 0 1 4 0v3"/></svg>',
  'LLM-Wiki': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2a7 7 0 0 0-7 7c0 3 2 4 2 6h10c0-2 2-3 2-6a7 7 0 0 0-7-7z"/><path d="M9 19a3 3 0 0 0 6 0"/></svg>',
}
export async function loadLibrary() {
  const lib = await apiHub('/library')
  state.library = {
    roots: (lib.roots || []).map((r: any) => ({
      name: r.name,
      count: r.count,
      recent: r.recent || [],
      icon: LIB_ICONS[r.name] || '',
    })),
  }
}

/* ---------------- AI 课堂（OpenMAIC） ---------------- */
async function apiSend(path: string, method: string, body?: any) {
  const r = await fetch(apiBase() + path, {
    method,
    headers: hubHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) {
    let detail = ''
    try { const j = await r.json(); detail = j.detail || JSON.stringify(j) } catch (e) { detail = (await r.text()).slice(0, 200) }
    throw new Error(detail || ('HTTP ' + r.status))
  }
  return r.json()
}
function omSize(b: number) { return b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' : (b / 1048576).toFixed(1) + ' MB' }
function omDate(ms: number) {
  const d = new Date(ms)
  return d.getFullYear() + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + String(d.getDate()).padStart(2, '0')
}
function omShort(p: string) {
  const parts = String(p).replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean)
  return parts.slice(-2).join('\\')
}
export async function omLoadStatus() {
  try {
    const s = await apiHub('/openmaic/status')
    state.om.status = s
    return s
  } catch (err: any) {
    state.om.status = { error: err.message }
    return state.om.status
  }
}
export function omStatusView() {
  const s = state.om.status
  if (!s) return { line: '读取中…', running: false, url: '', version: '', port: '' }
  if (s.error) return { line: '服务状态读取失败：' + s.error, running: false, url: '', version: '', port: '' }
  const app = s.app || {}
  const line = app.running
    ? '<span style="color:var(--green)">●</span> 运行中 · v' + esc(app.version || '?') + ' · 端口 ' + s.port
    : '<span style="color:var(--amber)">●</span> 未启动 · 点右边按钮按需拉起（约 10 秒）'
  return { line, running: !!app.running, url: s.url || '', version: app.version || '', port: s.port || '' }
}
export async function omStartSvc() {
  state.om.starting = true
  try {
    await apiSend('/openmaic/start', 'POST')
    showToast('OpenMAIC 已启动 ✓')
  } catch (err: any) { showErr('启动失败：' + err.message) }
  state.om.starting = false
  await omLoadStatus()
}
export async function omStopSvc() {
  try { await apiSend('/openmaic/stop', 'POST'); showToast('已停止') }
  catch (err: any) { showErr('停止失败：' + err.message) }
  await omLoadStatus()
}
export async function omLoadDocs(refresh = false) {
  try {
    const d = await apiHub('/openmaic/docs' + (refresh ? '?refresh=1' : ''))
    state.om.docs = d.docs || []
    state.om.roots = d.roots || []
  } catch (err: any) {
    state.om.docs = []
    state.om.roots = []
    showErr('文档读取失败：' + err.message)
  }
}
export function omRootChipsView() {
  const chips = [{ label: '全部 ' + state.om.docs.length, root: '', active: !state.om.root, title: '' }]
  ;(state.om.roots || []).forEach((r: any) => {
    chips.push({
      label: esc(omShort(r.path)) + ' · ' + (r.exists ? r.count : '不可用'),
      root: r.path,
      active: state.om.root === r.path,
      title: r.path,
    })
  })
  return chips
}
export function omFiltered() {
  const q = state.om.q.trim().toLowerCase()
  return state.om.docs.filter((d: any) => {
    if (state.om.root && d.root !== state.om.root) return false
    if (!q) return true
    return d.title.toLowerCase().includes(q)
      || d.relPath.toLowerCase().includes(q)
      || (d.excerpt || '').toLowerCase().includes(q)
  })
}
export function omDocsView() {
  const list = omFiltered()
  const shown = list.slice(0, state.om.limit)
  return {
    total: state.om.docs.length,
    count: list.length,
    more: list.length > state.om.limit ? list.length - state.om.limit : 0,
    docs: shown.map((d: any) => ({
      absPath: d.absPath,
      title: d.title,
      relPath: d.relPath,
      excerpt: d.excerpt || '（无预览）',
      meta: omDate(d.mtime) + ' · ' + omSize(d.size) + ' · ≈' + d.approxWords + ' 字',
      on: !!state.om.sel[d.absPath],
    })),
  }
}
export function omSelInfo() {
  const picked = state.om.docs.filter((d: any) => state.om.sel[d.absPath])
  const chars = picked.reduce((s: number, d: any) => s + Math.round(d.approxWords * 1.6), 0)
  return {
    count: picked.length,
    chars,
    text: picked.length ? '已选 ' + picked.length + ' 篇 · 合计 ≈' + chars + ' 字符' : '未选文档',
  }
}
export function omToggleDoc(path: string) {
  if (state.om.sel[path]) delete state.om.sel[path]
  else state.om.sel[path] = 1
}
export function omSelAll(max = 10) {
  const list = omFiltered().slice(0, max)
  list.forEach((d: any) => { state.om.sel[d.absPath] = 1 })
  if (omFiltered().length > list.length) showToast('已选前 ' + max + ' 篇（一次别选太多）')
}
export function omSelNone() { state.om.sel = {} }
export async function omGenerate(name: string) {
  const picked = state.om.docs.filter((d: any) => state.om.sel[d.absPath]).map((d: any) => d.absPath)
  await apiSend('/openmaic/generate', 'POST', { paths: picked, mode: state.om.mode, name })
  showToast('已提交，生成中 ✓')
  await omLoadJobs()
}
export async function omTopicGenerate(topic: string) {
  if (!topic) { showErr('先写一个主题'); return }
  await apiSend('/openmaic/generate', 'POST', { paths: [], mode: 'merge', name: topic, topic: topic })
  showToast('已提交，生成中 ✓')
  await omLoadJobs()
}
export async function omLoadJobs() {
  try {
    const j = await apiHub('/openmaic/jobs?limit=30')
    state.om.jobs = j.jobs || []
  } catch (err: any) {
    state.om.jobs = []
  }
}
export function omJobsView() {
  const js = state.om.jobs
  const running = js.filter((j: any) => !j.done).length
  return {
    running,
    tag: js.length ? (running + ' 进行中 / ' + js.length) : '—',
    jobs: js.map((j: any) => {
      const state_ = j.status === 'interrupted' ? '<span style="color:var(--red)">中断</span>'
        : j.error ? '<span style="color:var(--red)">失败</span>'
          : j.done ? '<span style="color:var(--green)">完成</span>'
            : '<span style="color:var(--primary)">' + esc(j.status || '…') + '</span>'
      const meta = [j.message, (j.sources && j.sources.length) ? (j.sources.length + ' 篇材料') : '', j.created_at ? j.created_at.slice(11, 16) : '']
        .filter(Boolean).join(' · ')
      return { label: j.label, state: state_, meta, url: j.url || '', progress: Math.max(2, Math.min(100, j.progress || 0)), error: j.error || '' }
    }),
  }
}
let omTimer: any = null
export function omStartPoll() {
  if (omTimer) clearInterval(omTimer)
  omTimer = setInterval(() => {
    if (state.view !== 'classroom') return
    if (state.om.jobs.some((j: any) => !j.done && j.status !== 'interrupted')) omLoadJobs()
  }, 6000)
}
export function omStopPoll() { if (omTimer) { clearInterval(omTimer); omTimer = null } }

/* ---------------- 视图切换 / 启动 ---------------- */
const LOADERS: Record<string, () => Promise<any>> = {
  today: loadToday,
  plans: loadPlans,
  review: loadReview,
  focus: loadFocus,
  feedback: loadFeedback,
  library: loadLibrary,
}
export async function showHubView(view: string) {
  state.view = view
  if (view === 'classroom') {
    await Promise.all([omLoadStatus(), omLoadDocs(), omLoadJobs()])
    omStartPoll()
  } else {
    omStopPoll()
    const loader = LOADERS[view]
    if (loader) {
      try { await loader() } catch (err: any) { showErr('加载失败：' + err.message) }
    }
  }
  if (view === 'today') { try { await loadHeat() } catch (e) { /* noop */ } }
}
export const hubViews = ['today', 'plans', 'review', 'focus', 'feedback', 'library', 'classroom']

export async function initHub() {
  const today = new Date()
  const wd = ['日', '一', '二', '三', '四', '五', '六'][today.getDay()]
  todayLabel.value = today.getFullYear() + '年' + (today.getMonth() + 1) + '月' + today.getDate() + '日 · 星期' + wd
  try {
    const saved = localStorage.getItem('hub-scene')
    if (saved) { setScene(saved, false) }
  } catch (e) { /* noop */ }
  // 深链：#/hub/review 直达对应视图
  const hashView = (location.hash || '').replace(/^#\/hub\/?/, '')
  if (hashView && hubViews.indexOf(hashView) >= 0) state.view = hashView
  // 加载服务端自定义设置
  try {
    state.settings = await apiHub('/settings')
    applyAllCustom()
    const s = state.settings
    if (s.scene && SLOGANS[s.scene]) setScene(s.scene, false)
    sloganText.value = s.slogan || SLOGANS[sceneRef.value]
  } catch (e) { /* noop */ }
  try {
    await showHubView(state.view)
    state.pomo.total = state.pomo.minutes * 60
    state.pomo.remain = state.pomo.total
    pomoRender()
    pomoResumeFromStorage()
    state.loading = false
  } catch (err: any) {
    state.loading = false
    showErr('连接失败：' + err.message + '。请确认 PC 端工作台服务已启动（端口 8637）。')
  }
}

const todayLabel = ref('')
export const hubTodayLabel = readonly(todayLabel)

/* 系统返回键：非今日视图先回今日 */
export function goBackApp(): string {
  if (state.view !== 'today') { showHubView('today'); return 'ok' }
  return 'none'
}

export { state as hubState, sceneRef as hubScene, SLOGANS, WP_GRADIENTS }
