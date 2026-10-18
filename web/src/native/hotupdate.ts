/* hotupdate.ts — APK 网页热更新（对齐 server/hub/router.py 的 /webversion + /webfile）
 *
 * 流程：比对服务端版本号 → 逐文件拉文本 → Native.saveWebFile 写入 files/www
 *      → Native.setWebVersion → Native.reloadApp 重载（MainActivity 的 WwwHandler 缓存优先）
 * 只在 APK 内运行；服务端不可达时静默跳过（离线也能正常用内置页面）。
 */
import { IS_APP, getServer, getToken } from '@/api/server'

const TEXT_EXT = /\.(html|htm|js|mjs|css|json|svg|map)$/i
const TIMEOUT_MS = 8000

interface ManifestFile {
  name: string
  sha256: string
}

interface Manifest {
  version: number
  files: ManifestFile[]
}

function withTimeout(url: string): Promise<Response> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  // 服务端对非回环请求要求令牌，热更新走的是同一个鉴权中间件
  const tok = getToken()
  const init: RequestInit = { cache: 'no-store', signal: ctrl.signal }
  if (tok) init.headers = { 'X-Token': tok }
  return fetch(url, init).finally(() => clearTimeout(timer))
}

/** 计算 UTF-8 文本的 SHA-256（hex），与服务端清单里的 sha256 对齐。
 *  WebView 下 crypto.subtle 在 appassets 源可用；不可用时返回 null，
 *  调用方据此**拒绝**热更新（宁可不更新，也不接受未校验的代码）。 */
async function sha256Hex(text: string): Promise<string | null> {
  try {
    const subtle = (globalThis.crypto && (globalThis.crypto as any).subtle) as SubtleCrypto | undefined
    if (!subtle) return null
    const buf = await subtle.digest('SHA-256', new TextEncoder().encode(text))
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('')
  } catch (e) {
    return null
  }
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
    for (const f of man.files) {
      const name = typeof f === 'string' ? f : f.name
      const expect = typeof f === 'string' ? '' : (f.sha256 || '')
      if (!name || !TEXT_EXT.test(name)) continue   // 后端只回文本内容，二进制资源跳过
      if (!expect) continue                          // 清单没带 sha256 → 不更新该文件
      try {
        const fr = await withTimeout(server + '/api/hub/webfile/' + encodePath(name))
        if (!fr.ok) continue
        const body = (await fr.json()) as { content: string }
        if (typeof body.content !== 'string') continue
        // 校验：内容哈希必须与清单一致，否则视为被篡改并跳过。
        // 无法计算哈希时同样跳过——宁可停在旧版，也不执行未校验的代码。
        const got = await sha256Hex(body.content)
        if (!got || got.toLowerCase() !== expect.toLowerCase()) continue
        if (N.saveWebFile(name, body.content)) ok++
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
