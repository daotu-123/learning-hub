/* ============================================================
   公共服务器模块（TS 版，替代原 server.js / ServerMod）
   - 服务器地址存取（App 内走原生桥，浏览器端走 localStorage）
   - api() 统一请求（8s 超时）
   - discover() UDP 自动发现 PC（App 内）
   ============================================================ */
const KEY = 'hub_server'
export const IS_APP: boolean = typeof window !== 'undefined' && typeof window.Native !== 'undefined'

export function getServer(): string {
  let v = ''
  try { if (IS_APP && window.Native!.loadPref) v = window.Native!.loadPref(KEY, '') || '' } catch (e) { /* noop */ }
  if (!v) { try { v = localStorage.getItem(KEY) || '' } catch (e) { /* noop */ } }
  return String(v).trim().replace(/\/+$/, '')
}

export function setServer(v: string): string {
  v = String(v || '').trim().replace(/\/+$/, '')
  try { if (IS_APP && window.Native!.savePref) window.Native!.savePref(KEY, v) } catch (e) { /* noop */ }
  try { localStorage.setItem(KEY, v) } catch (e) { /* noop */ }
  return v
}

export interface ApiError extends Error {
  status?: number
  data?: any
}

export function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const server = getServer()
  if (!server && !IS_APP) {
    // 浏览器端未配置：走同源相对路径（FastAPI 静态托管时天然可用）
    return rawFetch<T>(path, opts)
  }
  if (!server) return Promise.reject(new Error('未设置服务器地址'))
  return rawFetch<T>(server + path, opts)
}

async function rawFetch<T>(url: string, opts: RequestInit): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 8000)
  try {
    const res = await fetch(url, Object.assign({
      headers: { 'Content-Type': 'application/json' },
      signal: ctrl.signal,
    }, opts))
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      const err: ApiError = new Error(
        (data as any).detail
          ? (typeof (data as any).detail === 'string' ? (data as any).detail : JSON.stringify((data as any).detail))
          : ('HTTP ' + res.status))
      err.status = res.status
      err.data = data
      throw err
    }
    return data as T
  } finally {
    clearTimeout(timer)
  }
}

export function health(): Promise<boolean> {
  return api('/').then(() => true).catch(() => false)
}

export interface DiscoveredServer {
  name?: string
  ip: string
  port?: number
  url: string
}

/** UDP 自动发现：返回 [{name, ip, port, url}] */
export function discover(): DiscoveredServer[] {
  if (IS_APP && window.Native!.discoverServers) {
    try {
      const list = JSON.parse(window.Native!.discoverServers() || '[]')
      return (list || []).map((s: any) => {
        s.url = 'http://' + s.ip + ':' + (s.port || 8637)
        return s
      })
    } catch (e) { return [] }
  }
  return []
}

/** 发现并自动连接：返回 url 或 null */
export async function autoConnect(): Promise<string | null> {
  const list = discover()
  for (let i = 0; i < list.length; i++) {
    setServer(list[i].url)
    if (await health()) return list[i].url
  }
  return null
}
