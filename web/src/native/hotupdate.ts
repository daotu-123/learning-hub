/* hotupdate.ts — APK 网页热更新（对齐 server/hub/router.py 的 /webversion + /webfile）
 *
 * 流程：比对服务端版本号 → 逐文件拉文本 → Native.saveWebFile 写入 files/www
 *      → Native.setWebVersion → Native.reloadApp 重载（MainActivity 的 WwwHandler 缓存优先）
 * 只在 APK 内运行；服务端不可达时静默跳过（离线也能正常用内置页面）。
 */
import { IS_APP, getServer } from '@/api/server'

const TEXT_EXT = /\.(html|htm|js|mjs|css|json|svg|map)$/i
const TIMEOUT_MS = 8000

interface Manifest {
  version: number
  files: string[]
}

function withTimeout(url: string): Promise<Response> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  return fetch(url, { cache: 'no-store', signal: ctrl.signal }).finally(() => clearTimeout(timer))
}

/** 逐段编码，保留 / 分隔（后端是 {name:path} 路由，编码成 %2F 会匹配不上） */
function encodePath(p: string): string {
  return p.split('/').map(encodeURIComponent).join('/')
}

let running = false

export async function checkWebUpdate(): Promise<void> {
  if (!IS_APP || running) return
  const N = window.Native
  if (!N || !N.saveWebFile || !N.setWebVersion) return
  const server = getServer()
  if (!server) return

  running = true
  try {
    const res = await withTimeout(server + '/api/hub/webversion')
    if (!res.ok) return
    const man = (await res.json()) as Manifest
    const cur = Number(N.getWebVersion ? N.getWebVersion() : 0) || 0
    if (!man || !man.version || !Array.isArray(man.files)) return
    if (man.version <= cur) return

    let ok = 0
    for (const name of man.files) {
      if (!TEXT_EXT.test(name)) continue          // 后端只回文本内容，二进制资源跳过
      try {
        const fr = await withTimeout(server + '/api/hub/webfile/' + encodePath(name))
        if (!fr.ok) continue
        const body = (await fr.json()) as { content: string }
        if (typeof body.content === 'string' && N.saveWebFile(name, body.content)) ok++
      } catch (e) { /* 单个文件失败不影响其它文件 */ }
    }
    if (!ok) return

    N.setWebVersion(man.version)
    N.reloadApp?.()
  } catch (e) {
    /* 离线 / 服务未启动：保持内置页面 */
  } finally {
    running = false
  }
}
