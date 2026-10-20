/* ============================================================
   会话令牌存取（M2b）——**前端唯一的令牌出口**
   ------------------------------------------------------------
   为什么单独一个模块：
     令牌散落在各处就一定会漏（漏一处 = 某个请求不带凭据 = 401）。
     页面/组件一律不许直接碰 localStorage['hub_session'] 或 Native prefs。

   两处存储，一个 key：
     - APK（window.Native 存在）：Native.savePref / loadPref（SharedPreferences）
     - 浏览器：localStorage
   登出必须**同时**清两边：APK 里 WebView 的 localStorage 与 SharedPreferences
   是两个存储，只清一个会出现"登出后刷新又登回来了"。

   为什么还有旧共享令牌（hub_token）：
     双轨过渡。已发布的 APK 只认 X-Token，新页面要同时兼容两套凭据。
     注入规则见 authHeaders()：有会话用 Bearer，没有才回落到旧令牌。

   依赖方向：**本模块不 import api/server**。server.ts 单向依赖本模块，
   否则两者互相 import 会形成环（ESM 能跑，但初始化顺序不可控）。
   代价是 IS_APP 与 hub_token 的读取逻辑在这里复刻了一份，
   两处都只读同一批 key，不会写出不一致的值。
   ============================================================ */

/** 与旧令牌 hub_token 并存的第二个 key。改名会让已装 APK 全部掉登录。 */
export const SESSION_KEY = 'hub_session'
/** 旧共享令牌。key 与 api/server.ts 的 TOKEN_KEY 一致，不许改。 */
export const LEGACY_TOKEN_KEY = 'hub_token'

const IS_NATIVE: boolean = typeof window !== 'undefined' && typeof window.Native !== 'undefined'

type UnauthorizedHandler = () => void
let unauthorizedHandler: UnauthorizedHandler | null = null

/**
 * 注册 401 的统一处理（由 router/index.ts 注入，避免本模块反向依赖 router）。
 * 只注册一次即可；重复注册以最后一次为准。
 */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn
}

/**
 * 读会话令牌。
 *
 * APK 下 SharedPreferences 是权威源（它才是真正跟"账号"绑定的那一份）。
 * 若两边都在但**不一致**，说明热更新把新页面写到了 WebView 缓存而原生 prefs
 * 还是旧的——这是可自愈的状态：以 Native 为准，并把 localStorage 改写成同一个值，
 * 避免下一次读到第三种值。刻意不静默丢弃，而是 console.warn 留证据。
 */
export function loadSession(): string {
  let native = ''
  try { if (IS_NATIVE && window.Native && window.Native.loadPref) native = window.Native.loadPref(SESSION_KEY, '') || '' } catch (e) { /* noop */ }
  let local = ''
  try { local = localStorage.getItem(SESSION_KEY) || '' } catch (e) { /* noop */ }
  native = String(native).trim()
  local = String(local).trim()
  if (native && local && native !== local) {
    console.warn('[auth] 会话令牌在 Native 与 localStorage 之间不一致，以 Native 为准并已同步 localStorage')
    try { localStorage.setItem(SESSION_KEY, native) } catch (e) { /* noop */ }
    return native
  }
  return native || local
}

/** 写会话令牌。两边都写，保证 APK 与浏览器读到的是同一个值。 */
export function saveSession(token: string): string {
  const v = String(token || '').trim()
  try { if (IS_NATIVE && window.Native && window.Native.savePref) window.Native.savePref(SESSION_KEY, v) } catch (e) { /* noop */ }
  try { localStorage.setItem(SESSION_KEY, v) } catch (e) { /* noop */ }
  return v
}

/** 清会话令牌。**登出与 401 都必须走这里**，且要同时清两边。 */
export function clearSession(): void {
  try { if (IS_NATIVE && window.Native && window.Native.savePref) window.Native.savePref(SESSION_KEY, '') } catch (e) { /* noop */ }
  try { localStorage.removeItem(SESSION_KEY) } catch (e) { /* noop */ }
}

/** 是否有会话（只判存在，不校验有效性——有效性只能由服务端回答）。 */
export function hasSession(): boolean {
  return loadSession() !== ''
}

/** 旧共享令牌（只读）。有会话时用它没有意义，authHeaders 会先走 Bearer。 */
export function loadLegacyToken(): string {
  let v = ''
  try { if (IS_NATIVE && window.Native && window.Native.loadPref) v = window.Native.loadPref(LEGACY_TOKEN_KEY, '') || '' } catch (e) { /* noop */ }
  if (!v) {
    try { v = localStorage.getItem(LEGACY_TOKEN_KEY) || '' } catch (e) { /* noop */ }
  }
  return String(v).trim()
}

/**
 * 请求头注入（M2b 唯一出口）：
 *   有会话 → Authorization: Bearer <session>（**只走头，绝不拼进 URL**）
 *   无会话但有旧共享令牌 → X-Token（双轨过渡，别把老路径砍了）
 *   都没有 → 不加任何令牌头（回环访问本来就不校验）
 */
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = {}
  const s = loadSession()
  if (s) {
    h['Authorization'] = 'Bearer ' + s
  } else {
    const legacy = loadLegacyToken()
    if (legacy) h['X-Token'] = legacy
  }
  return Object.assign(h, extra || {})
}

/**
 * 401 统一处理：清会话并通知上层跳转登录页。
 *
 * 登录页自身会返回 401（用户名或口令错误），那时**不能跳**——
 * 由 router 注入的 handler 负责判断当前是否已在 /login。本模块只负责清令牌。
 */
export function handleUnauthorized(): void {
  clearSession()
  if (unauthorizedHandler) unauthorizedHandler()
}
