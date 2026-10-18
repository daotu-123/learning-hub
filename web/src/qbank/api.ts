/* api.ts — 题库统一数据通道（合并单 App 后固定静态模式）
 *
 * 双模式统一决策：Web 与 APK 行为一致，都走内置静态 Store
 * （public/qbank-data.js 的 window.QBANK_DATA + localStorage），
 * 不再依赖 mech-qbank 在线服务。
 *
 * 静态路由与原 app/api.py 一一对应：
 *   GET    /questions?…            组卷/复习/搜索
 *   POST   /questions/{id}/grade   判分
 *   GET    /questions/{id}         单题
 *   GET/PUT/DELETE /questions/{id}/note   备注
 *   GET    /notes                  备注列表
 *   GET/POST /progress             导出/导入进度
 *   PUT    /progress/{id}          记录结果（mark）
 *   GET    /wrong /stats /banks /sections /chapters /cards /custom /template
 *   GET/POST /checkins             打卡日历 / 手动补签
 *   POST   /import_questions       导入自定义题
 */
import { ElMessage } from 'element-plus'
import { make, QBankStore } from './staticStore'

/* 固定静态模式：数据首次使用前按需注入 qbank-data.js（file:// 与 http 均可） */
export const STATIC = true

let _sapi: QBankStore | null = null
function sapi(): QBankStore {
  if (!_sapi) {
    _sapi = make((window as any).QBANK_DATA || { questions: [], cards: [] }, safeStorage())
  }
  return _sapi
}
function safeStorage(): Storage | null {
  try { return localStorage } catch (e) { return null }
}

let dataReady: Promise<void> | null = null
export function ensureData(): Promise<void> {
  if ((window as any).QBANK_DATA) return Promise.resolve()
  if (!dataReady) {
    dataReady = new Promise<void>((resolve, reject) => {
      const s = document.createElement('script')
      s.src = 'qbank-data.js'   // public/ 产物，相对 index.html（Web /app/ 与 APK file:// 均可用）
      s.onload = () => resolve()
      s.onerror = () => reject(new Error('题库数据加载失败（qbank-data.js）'))
      document.head.appendChild(s)
    })
  }
  return dataReady
}

/** 统一请求入口。body 为空默认 GET，有 body 默认 POST，也可显式传 method（PUT/DELETE）。 */
export async function api<T = any>(path: string, body?: any, method?: string): Promise<T | null> {
  await ensureData()
  try {
    return staticRoute(path, body, method || (body ? 'POST' : 'GET')) as T
  } catch (e: any) {
    ElMessage.error('本地处理失败：' + e.message)
    return null
  }
}

/** 直接取静态 Store（清空自定义题库等需要同步返回值的场景，先确保数据已加载） */
export async function store(): Promise<QBankStore> {
  await ensureData()
  return sapi()
}

/* RESTful 路径 → 静态 Store 调用 */
function staticRoute(path: string, body?: any, method?: string): any {
  const u = new URL('http://static' + path), p = u.pathname, q = u.searchParams, S = sapi()
  const mq = /^\/questions\/([^/]+)(?:\/(note|grade))?$/.exec(p)
  const mp = /^\/progress\/([^/]+)$/.exec(p)
  if (p === '/questions') {
    if (q.get('q')) return { items: S.search(q.get('q')!, q.get('limit') || 50) }
    return {
      items: S.pick({
        n: q.get('limit') || 10, level: q.get('level'), qtype: q.get('qtype'),
        bank: q.get('bank'), section: q.get('section'), only_new: q.get('only_new') === '1',
        review: q.get('review') === '1',
      }),
    }
  }
  if (mq && mq[2] === 'grade') return S.grade(mq[1], (body || {}).given || '')
  if (mq && mq[2] === 'note') {
    if (method === 'DELETE') return S.set_note(mq[1], '')
    if (body) return S.set_note(mq[1], body.note || '')
    for (const it of S.notes_list()) if (it.id === mq[1]) return it
    return { id: mq[1], note: '', updated_at: '' }
  }
  if (mq && !mq[2]) return { item: S.question(mq[1]) }
  if (mp) return S.mark(mp[1], (body || {}).result || 'skip')
  if (p === '/notes') return { items: S.notes_list() }
  if (p === '/progress') {
    if (body) return { ok: true, imported: S.import_progress(body.progress || {}) }
    return { exported_at: new Date().toISOString(), mode: 'static', progress: S.export_progress() }
  }
  if (p === '/wrong') return { items: S.wrong_list(q.get('limit') || 200) }
  if (p === '/stats') return S.stats()
  if (p === '/banks') return { items: S.banks() }
  if (p === '/sections') return { items: S.sections() }
  if (p === '/chapters') return { items: S.chapters() }
  if (p === '/cards') return { items: S.cards(q.get('q') || '', q.get('chapter') || '', q.get('limit') || 500) }
  if (p === '/checkins') return body ? S.manual_checkin() : S.checkin(q.get('month') || '')
  if (p === '/template') return S.export_template()
  if (p === '/import_questions') {
    const r = S.merge_questions((body || {}).questions || [], (body || {}).mode || 'skip')
    return { ok: true, added: r.added, updated: r.updated, skipped: r.skipped, rejected: r.rejected }
  }
  if (p === '/custom') return { items: S.custom_list() }
  return { error: 'not found' }
}

/* 在线模式才有的退出服务：合并后无独立服务，不再提供 */
