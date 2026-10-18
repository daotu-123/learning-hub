/* ============================================================
   工作台状态层（TS 重写，替代原 tools/app.js）
   核心不变：本地缓存=权威；连接=同步时机；番茄钟时间戳计时。
   改进：Native 桥加 localStorage 回退（浏览器端不再崩）；toast 真实可见。
   ============================================================ */
import { reactive, ref, readonly } from 'vue'
import { api, getServer, setServer as saveServerAddr, IS_APP } from '@/api/server'

/* ---------------- 原生桥（带 Web 回退） ---------------- */
const native = {
  loadPref(key: string, def = ''): string {
    try {
      if (IS_APP && window.Native!.loadPref) return window.Native!.loadPref(key, def)
    } catch (e) { /* noop */ }
    try { return localStorage.getItem(key) ?? def } catch (e) { return def }
  },
  savePref(key: string, value: string) {
    try {
      if (IS_APP && window.Native!.savePref) { window.Native!.savePref(key, value); return }
    } catch (e) { /* noop */ }
    try { localStorage.setItem(key, value) } catch (e) { /* noop */ }
  },
  pickBackground() {
    try { if (IS_APP && window.Native!.pickBackground) window.Native!.pickBackground() } catch (e) { /* noop */ }
  },
  clearBackground() {
    try { if (IS_APP && window.Native!.clearBackground) window.Native!.clearBackground() } catch (e) { /* noop */ }
  },
  getBackgroundUri(): string {
    try { if (IS_APP && window.Native!.getBackgroundUri) return window.Native!.getBackgroundUri() || '' } catch (e) { /* noop */ }
    return ''
  },
  saveBackgroundUri(uri: string) {
    try { if (IS_APP && window.Native!.saveBackgroundUri) window.Native!.saveBackgroundUri(uri) } catch (e) { /* noop */ }
  },
  downloadImage(url: string) {
    try { if (IS_APP && window.Native!.downloadImage) { window.Native!.downloadImage(url); return true } } catch (e) { /* noop */ }
    return false
  },
}

/* ---------------- 本地缓存层 ---------------- */
export const LS = {
  get<T = any>(k: string, def: T): T {
    try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def } catch (e) { return def }
  },
  set(k: string, v: any) { try { localStorage.setItem(k, JSON.stringify(v)) } catch (e) { /* noop */ } },
  del(k: string) { try { localStorage.removeItem(k) } catch (e) { /* noop */ } },
}

/* ---------------- 工具函数 ---------------- */
export function todayStr(): string {
  const d = new Date()
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
}
export function fmtMin(min: number): string {
  if (!min || min <= 0) return '0分钟'
  const h = Math.floor(min / 60), m = min % 60
  if (h > 0) return h + '小时' + (m > 0 ? m + '分' : '')
  return m + '分钟'
}
export function fmtSyncTime(ts: number): string {
  if (!ts) return '从未同步'
  const d = new Date(ts), now = new Date()
  if (d.toDateString() === now.toDateString())
    return '今天 ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
export function isoWeekKey(d: Date): string {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNum = date.getUTCDay() || 7
  date.setUTCDate(date.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
  const weekNo = Math.ceil((((date.getTime() - yearStart.getTime()) / 86400000) + 1) / 7)
  return date.getUTCFullYear() + '-W' + String(weekNo).padStart(2, '0')
}
export function esc(s: any): string {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
}

/* ---------------- 全局状态 ---------------- */
export interface DeskTask { file: string | null; name: string; done: boolean; priority: string; mtime: number; dirty: string | false }
export interface PomoRecord { date: string; task: string; minutes: number; ts: number; synced: boolean }
export interface HealthRec { date: string; kind: string; label: string; valueMin: number; startTs: string; endTs: string; synced: boolean }
export interface AiMsg { role: 'user' | 'assistant'; content: string }

export const PRESET_BGS = [
  'linear-gradient(160deg,#f0f4fb,#e8edf7)',
  'linear-gradient(160deg,#f7f3ef,#efe7e0)',
  'linear-gradient(160deg,#eef7f3,#e2f0ea)',
  'linear-gradient(160deg,#1f2430,#2a3040)',
  'linear-gradient(160deg,#2b2438,#3a2f4d)',
  'linear-gradient(160deg,#14263c,#1e3f5e)',
]

export const PAGE_TITLES: Record<string, string> = {
  overview: '概览', diary: '日记', pomodoro: '专注', health: '健康',
  fav: '收藏', ai: 'AI 助手', photos: '照片', settings: '设置',
}
export const TABS = ['overview', 'diary', 'pomodoro', 'health', 'fav', 'ai']

const state = reactive({
  server: '',
  connected: false,
  date: todayStr(),
  favPlatform: 'all',
  stack: [] as string[],
  sync: { online: false, lastSyncAt: 0 },
  bgIndex: 0,
  customBg: '',
  /* 导航 */
  page: 'overview' as string,
  animDir: 0,
  /* 概览 */
  summary: null as any,
  deptSummary: '-',
  focusPomo: '-',
  focusSleep: '-',
  focusEx: '-',
  focusTask: '暂无未完成任务',
  focusFav: '抖音 - · 小红书 -',
  diaryPreview: '未连接服务器',
  /* 收藏 */
  favDate: todayStr(),
  favItems: [] as any[],
  favLoading: false,
  /* 健康 */
  sleepStart: '23:30',
  sleepEnd: '07:00',
  sleepHint: '',
  exType: '跑步',
  exMin: '',
  healthSleepToday: '-',
  healthExToday: '-',
  healthTrend: null as any,
  /* 文档 */
  docType: 'diary' as 'diary' | 'weekly' | 'monthly',
  docKeyDiary: todayStr(),
  docKeyWeekly: isoWeekKey(new Date()),
  docKeyMonthly: todayStr().slice(0, 7),
  diaryContent: '',
  diarySaveTag: '未保存',
  diaryMeta: '-',
  diaryImgs: [] as string[],
  /* 任务 */
  tasks: [] as DeskTask[],
  taskInput: '',
  /* 番茄 */
  pomo: {
    mode: 'focus',
    running: false,
    totalSec: 25 * 60,
    remainSec: 25 * 60,
    endAt: 0,
    timerId: null as any,
    task: null as DeskTask | null,
    startTs: null as string | null,
  },
  pomoToday: '今日：-',
  /* AI */
  aiInput: '',
  aiHistory: [] as AiMsg[],
  aiMsgs: [] as AiMsg[],
  aiBusy: false,
  /* 照片 */
  photos: [] as any[],
  photoCount: '0 张',
  photoBusy: false,
  /* 设置 */
  serverInfo: '',
})

const FOCUS_MIN = 25, BREAK_MIN = 5

/* ---------------- toast ---------------- */
const toastMsg = ref('')
const toastShow = ref(false)
let toastTimer: any = null
export function toast(msg: string) {
  toastMsg.value = msg
  toastShow.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastShow.value = false }, 2600)
}
export const toastState = readonly({ msg: toastMsg, show: toastShow })

/* ---------------- 连接 / 同步 ---------------- */
export function setConn(s: 'ok' | 'off' | 'busy') {
  state.connected = s === 'ok'
  state.sync.online = s === 'ok'
}
export function updateSyncStatus(): { online: boolean; text: string } {
  if (state.sync.online) return { online: true, text: '已连接 · 同步于 ' + fmtSyncTime(state.sync.lastSyncAt) }
  return { online: false, text: '离线模式 · 上次同步 ' + fmtSyncTime(state.sync.lastSyncAt) + ' · 重连后自动同步' }
}
export async function checkConnection(): Promise<boolean> {
  if (!state.server) return false
  try {
    await api('/')
    if (!state.sync.online) {
      state.sync.online = true
      state.sync.lastSyncAt = Date.now()
      setConn('ok')
      await syncAll()
      toast('已连接 PC，正在同步')
    } else {
      state.sync.lastSyncAt = Date.now()
      setConn('ok')
    }
    return true
  } catch (e) {
    if (state.sync.online) { state.sync.online = false; setConn('off') }
    return false
  }
}
export async function syncAll() {
  await syncTasks()
  await syncDocs()
  await syncPomos()
  await pushHealth()
  await refreshSummary()
  await refreshFavorites()
  await refreshHealth()
}

/* ---------------- 概览 ---------------- */
function renderOverview(s: any) {
  state.focusFav = '抖音 ' + s.favorites.douyin + ' 条 · 小红书 ' + s.favorites.xiaohongshu + ' 条'
  const notes = s.deeptutor.notes || {}
  const noteTxt = Object.keys(notes).length
    ? ' · 新增 ' + Object.entries(notes).map(([k, v]) => k + v).join(' ')
    : ''
  state.deptSummary = s.deeptutor.ok
    ? '今日会话 ' + s.deeptutor.sessions + ' 个 · 消息 ' + s.deeptutor.messages + ' 条' + noteTxt
    : '未读取到 DeepTutor 数据'
}
export function renderFocus() {
  const pomos = LS.get('pomos', [] as PomoRecord[]).filter(r => r.date === state.date)
  state.focusPomo = pomos.length ? pomos.length + ' 个' : '0 个'
  const hd = LS.get('health_' + state.date, null as any)
  state.focusSleep = hd && hd.sleep_min ? fmtMin(hd.sleep_min).replace('分钟', '分').replace('小时', '时') : '-'
  state.focusEx = hd && hd.exercise_min ? fmtMin(hd.exercise_min).replace('分钟', '分').replace('小时', '时') : '-'
  const tasks = LS.get('tasks', [] as DeskTask[]).filter(t => !t.done)
  if (tasks.length) {
    state.focusTask = tasks.slice(0, 2).map(t => t.name).join('、') + (tasks.length > 2 ? ' 等 ' + tasks.length + ' 项' : '')
  } else {
    state.focusTask = '暂无未完成任务'
  }
}
export function loadOverview() {
  const cached = LS.get('summary', null as any)
  if (cached && cached.date === state.date) renderOverview(cached.data)
  else if (!state.sync.online) state.focusFav = '离线模式，暂无缓存数据'
  renderFocus()
  const dl = LS.get('doc_diary_' + state.date, null as any)
  if (dl) state.diaryPreview = dl.content.slice(0, 140) || '（日记为空）'
  else if (state.sync.online) state.diaryPreview = '加载中…'
  else state.diaryPreview = '离线模式，日记无缓存'
  if (state.sync.online) refreshSummary()
}
export async function refreshSummary() {
  try {
    const s = await api('/api/summary?date=' + state.date)
    LS.set('summary', { date: state.date, data: s })
    renderOverview(s)
  } catch (e) { /* noop */ }
}

/* ---------------- 收藏 ---------------- */
export async function loadFavorites() {
  const cached = LS.get<any[] | null>('fav_' + state.favDate + '_' + state.favPlatform, null)
  if (cached) state.favItems = cached
  else if (!state.sync.online) { state.favItems = []; return }
  else { state.favItems = []; state.favLoading = true }
  if (state.sync.online) await refreshFavorites()
  state.favLoading = false
}
export async function refreshFavorites() {
  const date = state.favDate || state.date
  try {
    const d = await api('/api/favorites?date=' + date)
    const items: any[] = []
    if (state.favPlatform === 'all' || state.favPlatform === 'douyin') items.push(...(d.douyin || []).map((x: any) => Object.assign({ platform: 'douyin' }, x)))
    if (state.favPlatform === 'all' || state.favPlatform === 'xiaohongshu') items.push(...(d.xiaohongshu || []).map((x: any) => Object.assign({ platform: 'xiaohongshu' }, x)))
    items.sort((a, b) => (a.collected_at < b.collected_at ? 1 : -1))
    LS.set('fav_' + date + '_' + state.favPlatform, items)
    state.favItems = items
  } catch (e) { /* noop */ }
}

/* ---------------- 日报 ---------------- */
export async function generateDailyReport() {
  if (!state.sync.online) { toast('离线：无法生成日报（需连接 PC）'); return }
  const date = state.date
  try {
    const pomos = LS.get('pomos', [] as PomoRecord[]).filter(r => r.date === date)
    let health = LS.get('health_' + date, null as any)
    if (!health) { try { health = await api('/api/health?date=' + date) } catch (e) { /* noop */ } }
    let fav = { douyin: 0, xiaohongshu: 0 }
    try { const s = await api('/api/summary?date=' + date); fav = s.favorites } catch (e) { /* noop */ }

    const L: string[] = []
    L.push('# 学习日报', '', '**日期：' + date + '**', '', '## 番茄钟', '')
    const pomoMin = pomos.reduce((s, r) => s + r.minutes, 0)
    L.push('- 今日完成 ' + pomos.length + ' 个番茄 · 专注 ' + fmtMin(pomoMin))
    const doneTasks = LS.get('tasks', [] as DeskTask[]).filter(t => t.done)
    if (doneTasks.length) L.push('- 已完成任务: ' + doneTasks.map(t => t.name).join('、'))
    L.push('', '## 健康', '')
    if (health) L.push('- 睡眠 ' + fmtMin(health.sleep_min) + ' · 运动 ' + fmtMin(health.exercise_min))
    else L.push('- 暂无记录')
    L.push('', '## 收藏', '', '- 抖音新增 ' + fav.douyin + ' 条 · 小红书新增 ' + fav.xiaohongshu + ' 条', '', '---',
      '*由工作台生成 · ' + new Date().toLocaleString('zh-CN') + '*')

    const r = await api('/api/daily-report', { method: 'POST', body: JSON.stringify({ date, content: L.join('\n') }) })
    toast('日报已生成：' + r.path)
  } catch (e: any) {
    toast('日报生成失败：' + (e && e.message))
  }
}

/* ---------------- 健康 ---------------- */
export function loadHealth() {
  renderHealthLocal()
  if (state.sync.online) refreshHealth()
}
function renderHealthLocal() {
  const d = LS.get('health_' + state.date, null as any)
  state.healthSleepToday = d ? fmtMin(d.sleep_min) : '-'
  state.healthExToday = d ? fmtMin(d.exercise_min) : '-'
  state.healthTrend = LS.get('health_trend', null)
}
export async function refreshHealth() {
  try {
    const d = await api('/api/health?date=' + state.date)
    LS.set('health_' + state.date, d)
    const t = await api('/api/health?days=7')
    LS.set('health_trend', t)
    renderHealthLocal()
  } catch (e) { /* noop */ }
}
export function recordHealth(kind: string, label: string, valueMin: number, startTs: string, endTs: string) {
  const rec: HealthRec = { date: state.date, kind, label, valueMin, startTs, endTs, synced: false }
  const list = LS.get('health_recs', [] as HealthRec[])
  list.push(rec)
  LS.set('health_recs', list)
  if (state.sync.online) pushHealth()
  else toast('离线：已存本地，重连后同步')
  refreshHealthLocalSummary()
}
export async function pushHealth() {
  const list = LS.get('health_recs', [] as HealthRec[])
  let changed = false
  for (const r of list) {
    if (r.synced) continue
    try {
      await api('/api/health', {
        method: 'POST',
        body: JSON.stringify({ date: r.date, kind: r.kind, label: r.label, value_min: r.valueMin, start_ts: r.startTs || '', end_ts: r.endTs || '' }),
      })
      r.synced = true; changed = true
    } catch (e) { break }
  }
  if (changed) LS.set('health_recs', list)
  refreshHealth()
}
function refreshHealthLocalSummary() {
  const recs = LS.get('health_recs', [] as HealthRec[]).filter(r => r.date === state.date)
  const sleepMin = recs.filter(r => r.kind === 'sleep').reduce((s, r) => s + r.valueMin, 0)
  const exMin = recs.filter(r => r.kind === 'exercise').reduce((s, r) => s + r.valueMin, 0)
  if (!state.sync.online) {
    state.healthSleepToday = fmtMin(sleepMin)
    state.healthExToday = fmtMin(exMin)
    state.focusSleep = fmtMin(sleepMin).replace('分钟', '分').replace('小时', '时')
    state.focusEx = fmtMin(exMin).replace('分钟', '分').replace('小时', '时')
  }
}
export function calcSleepMin(start: string, end: string): number {
  const [sh, sm] = (start || '23:30').split(':').map(Number)
  const [eh, em] = (end || '07:00').split(':').map(Number)
  let mins = (eh * 60 + em) - (sh * 60 + sm)
  if (mins <= 0) mins += 24 * 60
  return mins
}
export function healthChartView() {
  const trend = state.healthTrend || {}
  const days = Object.keys(trend).sort()
  if (!days.length) return null
  const W = 340, H = 140, padB = 22, padT = 14
  const vals = days.map(d => Math.max((trend[d].sleep || 0), (trend[d].exercise || 0)))
  const max = Math.max(...vals, 1)
  const bw = (W - 40) / days.length * 0.35
  const bars: string[] = []
  days.forEach((d, i) => {
    const x = 24 + i * (W - 40) / days.length + ((W - 40) / days.length - bw * 2) / 2
    const sleep = trend[d].sleep || 0, ex = trend[d].exercise || 0
    const hs = Math.max(2, (sleep / max) * (H - padB - padT))
    const he = Math.max(2, (ex / max) * (H - padB - padT))
    bars.push('<rect class="bar bar-sleep" x="' + x.toFixed(1) + '" y="' + (H - padB - hs).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + hs.toFixed(1) + '"></rect>')
    bars.push('<rect class="bar bar-ex" x="' + (x + bw + 3).toFixed(1) + '" y="' + (H - padB - he).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + he.toFixed(1) + '"></rect>')
    bars.push('<text class="lbl" x="' + (x + bw + 1.5).toFixed(1) + '" y="' + (H - 5) + '" text-anchor="middle">' + d.slice(5) + '</text>')
  })
  return {
    svg: '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
      '<line class="axis" x1="20" y1="' + (H - padB) + '" x2="' + (W - 10) + '" y2="' + (H - padB) + '"></line>' + bars.join('') + '</svg>',
  }
}

/* ---------------- 文档（日记/周记/月记） ---------------- */
function docCacheKey(type: string, key: string) { return 'doc_' + type + '_' + key }
function currentDocKey(): string {
  if (state.docType === 'diary') return state.docKeyDiary
  if (state.docType === 'weekly') return state.docKeyWeekly
  return state.docKeyMonthly
}
export function switchDocType(t: 'diary' | 'weekly' | 'monthly') {
  state.docType = t
  loadDiary()
}
export function loadDiary() {
  const key = currentDocKey()
  if (!key) return
  const local = LS.get(docCacheKey(state.docType, key), null as any)
  if (local) {
    state.diaryContent = local.content
    state.diarySaveTag = local.dirty ? '待同步' : (state.sync.online ? '已同步' : '已存档')
    state.diaryMeta = (state.sync.online ? '' : '离线 · ') + '最后修改 ' + new Date(local.mtime * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    if (state.sync.online && !local.dirty) fetchDoc()
  } else if (state.sync.online) {
    state.diarySaveTag = '加载中…'
    fetchDoc()
  } else {
    state.diaryContent = ''
    state.diarySaveTag = '离线'
    state.diaryMeta = '离线模式，无本地缓存'
  }
  renderDiaryImgs()
}
async function fetchDoc() {
  try {
    const d = await api('/api/doc?dtype=' + state.docType + '&key=' + encodeURIComponent(currentDocKey()))
    const local = LS.get(docCacheKey(state.docType, currentDocKey()), null as any)
    if (local && local.dirty) return
    LS.set(docCacheKey(state.docType, currentDocKey()), { content: d.content || '', mtime: d.mtime || 0, dirty: false })
    state.diaryContent = d.content || ''
    renderDiaryImgs()
    state.diarySaveTag = d.exists ? '已同步' : '新建'
    state.diaryMeta = d.exists
      ? '已存在 · 最后修改 ' + new Date(d.mtime * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : '该文档不存在，保存将创建'
  } catch (e) { /* noop */ }
}
export async function saveDiary() {
  const content = state.diaryContent
  if (!content.trim()) { toast('内容为空'); return }
  const mtime = Date.now() / 1000
  LS.set(docCacheKey(state.docType, currentDocKey()), { content, mtime, dirty: true })
  state.diarySaveTag = '已存本地'
  if (state.sync.online) await pushDocByCache(docCacheKey(state.docType, currentDocKey()))
  else toast('离线：已存本地，重连后自动同步')
  loadOverview()
}
async function pushDocByCache(cacheKey: string) {
  const local = LS.get(cacheKey, null as any)
  if (!local || !local.dirty) return true
  const { type, key } = docKeyFromCache(cacheKey)
  try {
    const cur = await api('/api/doc?dtype=' + type + '&key=' + encodeURIComponent(key)).catch(() => null)
    const base = (cur && cur.mtime) || 0
    const r = await api('/api/doc', {
      method: 'PUT',
      body: JSON.stringify({ dtype: type, key, content: local.content, base_updated_at: base }),
    })
    LS.set(cacheKey, { content: local.content, mtime: r.mtime, dirty: false })
    if (type === state.docType && key === currentDocKey()) state.diarySaveTag = '已同步'
    toast('文档已同步到 PC')
    return true
  } catch (e: any) {
    if (type === state.docType && key === currentDocKey()) state.diarySaveTag = '同步失败'
    toast('同步失败：' + (e && e.message))
    return false
  }
}
function docKeyFromCache(cacheKey: string) {
  const rest = cacheKey.slice(4)
  const idx = rest.indexOf('_')
  return { type: rest.slice(0, idx), key: rest.slice(idx + 1) }
}
export async function syncDocs() {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (k && k.startsWith('doc_')) keys.push(k)
  }
  for (const k of keys) {
    const local = LS.get(k, null as any)
    if (local && local.dirty) await pushDocByCache(k)
  }
}

/* ---------------- 日记图片 ---------------- */
const IMG_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp']
function imgUrl(rel: string): string {
  return state.server.replace(/\/+$/, '') + '/img/' + rel.split('/').map(encodeURIComponent).join('/')
}
function extractDiaryImages(text: string): string[] {
  const out: string[] = []
  const re = /!\[\[([^\]]+)\]\]/g
  let m
  while ((m = re.exec(text || ''))) {
    let ref = m[1].split('|')[0].trim()
    if (!ref) continue
    const ext = ref.includes('.') ? ref.split('.').pop()!.toLowerCase() : ''
    if (IMG_EXTS.indexOf(ext) < 0) continue
    out.push(ref)
  }
  return out
}
export function renderDiaryImgs() {
  state.diaryImgs = extractDiaryImages(state.diaryContent)
}
export function diaryImgUrl(rel: string) { return imgUrl(rel) }
export function insertAtCursorInDiary(text: string) {
  state.diaryContent = state.diaryContent + text
  renderDiaryImgs()
}
export async function uploadDiaryImage(file: File) {
  if (!file) return
  if (!state.sync.online) { toast('插图需连接 PC'); return }
  if (file.size > 18 * 1024 * 1024) { toast('图片超过 18MB'); return }
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      const r = await api('/api/photo/upload', {
        method: 'POST',
        body: JSON.stringify({ date: state.date, name: file.name || 'photo.jpg', data: reader.result }),
      })
      insertAtCursorInDiary('\n![[' + r.rel + ']]\n')
      toast('已插入图片')
    } catch (e: any) { toast('上传失败：' + ((e && e.message) || '')) }
  }
  reader.onerror = () => toast('读取图片失败')
  reader.readAsDataURL(file)
}

/* ---------------- 番茄钟 ---------------- */
function pomoPersist() {
  LS.set('pomo_state', {
    mode: state.pomo.mode, running: state.pomo.running,
    totalSec: state.pomo.totalSec, remainSec: state.pomo.remainSec,
    endAt: state.pomo.endAt, task: state.pomo.task, startTs: state.pomo.startTs,
  })
}
export function pomoRestore() {
  const s = LS.get('pomo_state', null as any)
  if (!s) return
  state.pomo.mode = s.mode || 'focus'
  state.pomo.totalSec = s.totalSec || FOCUS_MIN * 60
  state.pomo.remainSec = s.remainSec || state.pomo.totalSec
  state.pomo.task = s.task || null
  state.pomo.startTs = s.startTs || null
  if (s.running && s.endAt) {
    const remain = Math.round((s.endAt - Date.now()) / 1000)
    if (remain > 0) {
      state.pomo.running = true
      state.pomo.endAt = s.endAt
      state.pomo.timerId = setInterval(pomoTick, 1000)
    } else {
      state.pomo.running = false
      state.pomo.remainSec = 0
      setTimeout(() => pomoComplete(), 100)
    }
  }
}
export function loadPomodoro() {
  loadTasks()
  loadPomoToday()
}
function pomoRemain(): number {
  if (state.pomo.running && state.pomo.endAt) return Math.max(0, Math.round((state.pomo.endAt - Date.now()) / 1000))
  return state.pomo.remainSec
}
function pomoTick() {
  if (pomoRemain() <= 0) { pomoComplete(); return }
  state.pomo.remainSec = pomoRemain()
}
export function pomoToggle() {
  if (state.pomo.running) {
    state.pomo.remainSec = pomoRemain()
    state.pomo.running = false
    if (state.pomo.timerId) { clearInterval(state.pomo.timerId); state.pomo.timerId = null }
  } else {
    if (state.pomo.remainSec <= 0) state.pomo.remainSec = state.pomo.totalSec
    state.pomo.running = true
    state.pomo.endAt = Date.now() + state.pomo.remainSec * 1000
    state.pomo.startTs = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
    state.pomo.timerId = setInterval(pomoTick, 1000)
  }
  pomoPersist()
}
export function pomoReset() {
  state.pomo.running = false
  if (state.pomo.timerId) { clearInterval(state.pomo.timerId); state.pomo.timerId = null }
  state.pomo.remainSec = state.pomo.totalSec
  state.pomo.startTs = null
  pomoPersist()
}
export function pomoSwitchMode(mode: string) {
  if (state.pomo.running) pomoReset()
  state.pomo.mode = mode
  state.pomo.totalSec = (mode === 'focus' ? FOCUS_MIN : BREAK_MIN) * 60
  state.pomo.remainSec = state.pomo.totalSec
  pomoPersist()
}
/* 跳过：直接走完成流程（记录/切换模式） */
export function pomoSkip() {
  pomoComplete()
}
async function pomoComplete() {
  const wasRunning = state.pomo.running
  state.pomo.running = false
  if (state.pomo.timerId) { clearInterval(state.pomo.timerId); state.pomo.timerId = null }
  if (state.pomo.mode === 'focus') {
    const taskName = state.pomo.task ? state.pomo.task.name : ''
    recordPomoLocal(state.date, taskName, FOCUS_MIN)
    if (state.sync.online) pushPomos()
    if (state.pomo.task) {
      const t = state.tasks.find(x => x.file === state.pomo.task!.file)
      if (t) { t.done = true; t.dirty = t.dirty === 'add' ? 'add' : 'toggle'; saveTasksLocal() }
      if (state.sync.online) {
        const endTs = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
        const startTs = state.pomo.startTs || endTs
        api('/api/tasks/patch', { method: 'POST', body: JSON.stringify({ file: state.pomo.task.file, action: 'timeEntry', start_ts: startTs, end_ts: endTs }) }).catch(() => { })
        syncTasks()
      } else {
        toast('离线：任务已标记，重连后同步')
      }
    }
    state.pomo.mode = 'break'
    state.pomo.totalSec = BREAK_MIN * 60
    state.pomo.remainSec = state.pomo.totalSec
    toast('专注完成！休息一下 ☕')
  } else {
    state.pomo.mode = 'focus'
    state.pomo.totalSec = FOCUS_MIN * 60
    state.pomo.remainSec = state.pomo.totalSec
    toast('休息结束，继续专注 💪')
  }
  state.pomo.startTs = null
  pomoPersist()
  loadPomoToday()
  loadOverview()
}
function recordPomoLocal(date: string, task: string, minutes: number) {
  const list = LS.get('pomos', [] as PomoRecord[])
  list.push({ date, task, minutes, ts: Date.now(), synced: false })
  LS.set('pomos', list)
}
async function pushPomos() {
  const list = LS.get('pomos', [] as PomoRecord[])
  let changed = false
  for (const r of list) {
    if (r.synced) continue
    try {
      await api('/api/pomodoro', { method: 'POST', body: JSON.stringify({ date: r.date, task: r.task, minutes: r.minutes }) })
      r.synced = true; changed = true
    } catch (e) { break }
  }
  if (changed) LS.set('pomos', list)
}
async function syncPomos() { await pushPomos() }
export function loadPomoToday() {
  if (state.sync.online) {
    api('/api/pomodoro?date=' + state.date).then(d => {
      state.pomoToday = '今日：' + d.count + ' 个番茄 · 专注 ' + d.focus_min + ' 分钟'
    }).catch(() => { state.pomoToday = '今日：-' })
  } else {
    const list = LS.get('pomos', [] as PomoRecord[]).filter(r => r.date === state.date)
    const cnt = list.length
    const mins = list.reduce((s, r) => s + r.minutes, 0)
    state.pomoToday = '今日：' + cnt + ' 个番茄 · 专注 ' + mins + ' 分钟（离线）'
  }
}

/* ---------------- 任务 ---------------- */
export function loadTasks() {
  state.tasks = LS.get('tasks', [] as DeskTask[])
  if (state.sync.online) fetchTasks()
}
async function fetchTasks() {
  try {
    const d = await api('/api/tasks')
    const serverTasks = d.tasks || []
    const local = state.tasks
    const localFiles: Record<string, boolean> = {}
    local.forEach(t => { if (t.file) localFiles[t.file] = true })
    serverTasks.forEach((st: any) => {
      if (!localFiles[st.file]) {
        local.push({ file: st.file, name: st.name, done: st.status === 'done', priority: st.priority || 'normal', mtime: st.mtime, dirty: false })
      }
    })
    LS.set('tasks', local)
  } catch (e) { /* noop */ }
}
function saveTasksLocal() {
  LS.set('tasks', state.tasks)
}
export async function addTask() {
  const v = state.taskInput.trim()
  if (!v) return
  state.tasks.unshift({ file: null, name: v, done: false, priority: 'normal', mtime: 0, dirty: 'add' })
  saveTasksLocal()
  state.taskInput = ''
  if (state.sync.online) await syncTasks()
  else toast('离线：已存本地，重连后创建到 PC')
}
export async function toggleTask(i: number) {
  const t = state.tasks[i]
  if (!t) return
  t.done = !t.done
  t.dirty = t.dirty === 'add' ? 'add' : 'toggle'
  saveTasksLocal()
  if (state.sync.online) await syncTasks()
  else toast('离线：已存本地，重连后同步')
}
export async function deleteTask(i: number) {
  const t = state.tasks[i]
  if (!t) return
  if (t.file) {
    const deleted = LS.get('deletedTasks', [] as string[])
    if (deleted.indexOf(t.file) < 0) deleted.push(t.file)
    LS.set('deletedTasks', deleted)
  }
  state.tasks.splice(i, 1)
  saveTasksLocal()
  if (state.sync.online) await syncTasks()
  else toast('离线：已存本地，重连后同步')
}
export async function syncTasks() {
  const deleted = LS.get('deletedTasks', [] as string[])
  const tasks = LS.get('tasks', [] as DeskTask[])
  try {
    for (const f of deleted) {
      try { await api('/api/tasks/patch', { method: 'POST', body: JSON.stringify({ file: f, action: 'delete' }) }) } catch (e) { /* noop */ }
    }
    LS.set('deletedTasks', [])
    const d = await api('/api/tasks')
    const serverByName: Record<string, any> = {}
    ;(d.tasks || []).forEach((st: any) => { serverByName[st.name] = st })
    for (const t of tasks) {
      if (!t.dirty) continue
      try {
        if (t.dirty === 'add' || !t.file) {
          const r = await api('/api/tasks/add', { method: 'POST', body: JSON.stringify({ name: t.name }) })
          t.file = r.task.file
          t.dirty = false
        } else if (t.dirty === 'toggle') {
          const st = serverByName[t.name]
          if (st) {
            await api('/api/tasks/patch', { method: 'POST', body: JSON.stringify({ file: st.file, action: 'toggle', done: t.done, base_mtime: t.mtime }) })
            t.file = st.file; t.mtime = Date.now() / 1000; t.dirty = false
          }
        }
      } catch (e) { /* noop */ }
    }
    LS.set('tasks', tasks)
    await fetchTasks()
  } catch (e) { /* noop */ }
}

/* ---------------- AI 助手 ---------------- */
function mdRender(t: string): string {
  let s = esc(t)
  s = s.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
  s = s.replace(/^- (.*)$/gm, '• $1')
  s = s.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>')
  return s
}
export function aiMd(html: string) { return mdRender(html) }
export async function sendAi(text?: string) {
  const v = (text ?? state.aiInput).trim()
  if (!v) return
  if (!state.sync.online) {
    state.aiMsgs.push({ role: 'assistant', content: '📴 离线模式：AI 助手需要连接 PC 才能使用（AI 在 PC 端分析你的工作台数据）。连接后可继续提问。' })
    return
  }
  state.aiInput = ''
  state.aiMsgs.push({ role: 'user', content: v })
  state.aiBusy = true
  state.aiHistory.push({ role: 'user', content: v })
  const typingIdx = state.aiMsgs.push({ role: 'assistant', content: '' }) - 1
  try {
    const r = await api('/api/ai/chat', {
      method: 'POST',
      body: JSON.stringify({ messages: state.aiHistory.slice(-10), date: state.date }),
    })
    state.aiHistory.push({ role: 'assistant', content: r.reply })
    state.aiMsgs[typingIdx] = { role: 'assistant', content: mdRender(r.reply) }
  } catch (e: any) {
    state.aiMsgs[typingIdx] = { role: 'assistant', content: '⚠️ ' + esc((e && e.message) || 'AI 调用失败') }
  } finally {
    state.aiBusy = false
  }
}

/* ---------------- 照片 ---------------- */
export async function loadPhotos() {
  if (!state.sync.online) {
    state.photos = []
    state.photoCount = '-'
    return
  }
  try {
    const d = await api('/api/photos')
    const photos = d.photos || []
    state.photoCount = photos.length + ' 张'
    state.photos = photos
  } catch (e) {
    state.photos = []
    state.photoCount = '0 张'
  }
}
export async function uploadPhoto(file: File) {
  if (!file) return
  if (!state.sync.online) { toast('离线：无法上传照片'); return }
  if (file.size > 18 * 1024 * 1024) { toast('照片超过 18MB'); return }
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      state.photoBusy = true
      const r = await api('/api/photo/upload', {
        method: 'POST',
        body: JSON.stringify({ date: state.date, name: file.name || 'photo.jpg', data: reader.result }),
      })
      toast('已同步：' + r.rel)
      await loadPhotos()
    } catch (e: any) {
      toast('上传失败：' + ((e && e.message) || ''))
    } finally {
      state.photoBusy = false
    }
  }
  reader.onerror = () => toast('读取照片失败')
  reader.readAsDataURL(file)
}

/* ---------------- 设置 / 背景 ---------------- */
function applyBg() {
  const custom = native.loadPref('bg_custom', '')
  state.customBg = custom
  state.bgIndex = parseInt(native.loadPref('bg_index', '0'), 10) || 0
  if (custom) {
    document.body.classList.add('has-bgimg')
    document.body.style.background = "url('" + custom + "') center/cover no-repeat fixed"
    document.body.style.backgroundColor = 'transparent'
  } else {
    document.body.classList.remove('has-bgimg')
    document.body.style.background = PRESET_BGS[state.bgIndex] || PRESET_BGS[0]
  }
}
export function pickBg(i: number) {
  state.bgIndex = i
  state.customBg = ''
  native.savePref('bg_index', String(i))
  native.savePref('bg_custom', '')
  applyBg()
}
export function clearBg() {
  native.clearBackground()
  native.savePref('bg_custom', '')
  applyBg()
}
export function pickBgFromAlbum() { native.pickBackground() }
export function onBackgroundChanged() {
  native.savePref('bg_custom', native.getBackgroundUri())
  applyBg()
}

/* ---------------- 导航 ---------------- */
export function showPage(page: string, dir = 1) {
  state.page = page
  state.animDir = dir
  if (page === 'fav') loadFavorites()
  if (page === 'diary') loadDiary()
  if (page === 'overview') loadOverview()
  if (page === 'pomodoro') loadPomodoro()
  if (page === 'health') loadHealth()
  if (page === 'photos') loadPhotos()
}
export function goTab(page: string) { state.stack = []; showPage(page, 1) }
export function pushPage(page: string) {
  state.stack.push(state.page)
  showPage(page, 1)
}
export function goBack() {
  if (state.stack.length === 0) return false
  const prev = state.stack.pop()!
  showPage(prev, -1)
  return true
}
export function currentPage() { return state.page }

/* ---------------- 初始化 ---------------- */
let heartbeatTimer: any = null
export function initDesk() {
  state.server = getServer()
  state.bgIndex = parseInt(native.loadPref('bg_index', '0'), 10) || 0
  state.customBg = native.loadPref('bg_custom', '')

  const now = new Date()
  state.favDate = state.date
  state.docKeyDiary = state.date
  state.docKeyWeekly = isoWeekKey(now)
  state.docKeyMonthly = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0')
  state.serverInfo = '当前：' + (state.server || '未配置（门户可自动发现）')

  applyBg()

  // 深链：#/desk/fav 直达对应页
  const hash = (location.hash || '').replace(/^#\/desk\/?/, '')
  if (hash && Object.prototype.hasOwnProperty.call(PAGE_TITLES, hash)) showPage(hash, 0)

  updateSyncStatus()
  pomoRestore()
  loadTasks()
  loadDiary()
  loadOverview()
  loadHealth()
  if (state.server) {
    checkConnection().then(ok => {
      if (!ok) toast('离线模式：数据已存档，重连后自动同步')
    })
    heartbeatTimer = setInterval(() => checkConnection(), 20000)
  }
}

/** 系统返回键：有页面栈先回退，栈空交由外壳（切回学习中枢） */
export function goBackApp(): string {
  if (state.stack.length > 0) { goBack(); return 'ok' }
  return 'none'
}

export { state as deskState, native }
