/* 工作台 store 冒烟测试：Node + 真实后端（8637） */
import { build } from 'esbuild'
import { resolve } from 'node:path'
import { readFileSync } from 'node:fs'

// ---- 浏览器全局对象 shim ----
const lsStore = new Map()
lsStore.set('hub_server', 'http://127.0.0.1:8637')
globalThis.localStorage = {
  getItem: (k) => (lsStore.has(k) ? lsStore.get(k) : null),
  setItem: (k, v) => lsStore.set(k, String(v)),
  removeItem: (k) => lsStore.delete(k),
}
const styleStub = { setProperty() {}, }
globalThis.document = {
  documentElement: { style: styleStub },
  body: { dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, style: styleStub },
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  title: '',
  hidden: false,
  addEventListener() {},
  removeEventListener() {},
}
globalThis.location = { hash: '', href: 'http://127.0.0.1:8639/app/', reload() {} }
globalThis.window = globalThis
globalThis.alert = () => {}
globalThis.confirm = () => true

const aliasPlugin = {
  name: 'alias',
  setup(b) {
    b.onResolve({ filter: /^@\// }, (args) => {
      const base = resolve(process.cwd(), 'src', args.path.slice(2))
      for (const ext of ['', '.ts', '.js', '/index.ts']) {
        try { readFileSync(base + ext); return { path: base + ext } } catch (e) { /* try next */ }
      }
      return { path: base }
    })
  },
}
await build({
  entryPoints: ['src/desk/store.ts'],
  bundle: true,
  format: 'esm',
  platform: 'browser',
  plugins: [aliasPlugin],
  outfile: 'test-desk-bundle.mjs',
  logLevel: 'error',
})

const desk = await import('./test-desk-bundle.mjs')

const results = []
const check = (name, ok, extra = '') => {
  results.push(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`)
}

await desk.initDesk()
check('initDesk 无异常', true)
check('date 已初始化', /^\d{4}-\d{2}-\d{2}$/.test(desk.deskState.date), desk.deskState.date)

// 各数据区加载（内部已有 try/catch 容错）
check('tasks 数组', Array.isArray(desk.deskState.tasks))
check('health 字段', typeof desk.deskState.healthSleepToday === 'string' && typeof desk.deskState.healthExToday === 'string')
check('favItems 数组', Array.isArray(desk.deskState.favItems))
check('doc 三类型字段', ['diary', 'weekly', 'monthly'].includes(desk.deskState.docType) && typeof desk.deskState.diaryContent === 'string')
check('diary 图片数组', Array.isArray(desk.deskState.diaryImgs))
check('photos 数组', Array.isArray(desk.deskState.photos))
check('serverInfo 字段', typeof desk.deskState.serverInfo === 'string')
check('pomo 状态', typeof desk.deskState.pomo.remainSec === 'number')
check('AI 消息数组', Array.isArray(desk.deskState.aiMsgs))

// 番茄钟新增导出
check('pomoSkip 已导出', typeof desk.pomoSkip === 'function')
check('pomoToggle 已导出', typeof desk.pomoToggle === 'function')

// 本地工具函数
check('todayStr', /^\d{4}-\d{2}-\d{2}$/.test(desk.todayStr()))
check('fmtMin(90)', desk.fmtMin(90) === '1小时30分', desk.fmtMin(90))
check('fmtMin(45)', desk.fmtMin(45) === '45分钟')
check('fmtMin(0)', desk.fmtMin(0) === '0分钟')

// 收藏加载（走缓存/网络两条路径都不应抛错）
await desk.loadFavorites()
check('loadFavorites 无异常', true)

// 导航
desk.goTab('health')
check('goTab(health)', desk.deskState.page === 'health')
desk.goTab('ai')
check('goTab(ai)', desk.deskState.page === 'ai')
desk.pushPage('photos')
check('pushPage(photos) 切页', desk.deskState.page === 'photos')
check('pushPage(photos) 入栈', desk.deskState.stack[desk.deskState.stack.length - 1] === 'ai')
desk.goBack()
check('goBack 返回上一页', desk.deskState.page === 'ai' && desk.deskState.stack.length === 0)

// 同步（在线时应成功；不在线也不应抛错）
await desk.syncAll().catch((e) => { throw e })
check('syncAll 无异常', true)

console.log(results.join('\n'))
const fails = results.filter((r) => r.startsWith('FAIL'))
console.log(`\n===== ${results.length - fails.length}/${results.length} PASS =====`)
process.exit(fails.length ? 1 : 0)
