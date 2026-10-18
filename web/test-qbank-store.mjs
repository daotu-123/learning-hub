/* 题库静态 Store 冒烟测试：Node + esbuild bundle（不需要浏览器/后端）
 *
 * 覆盖：数据加载 → 组卷/搜索 → 判分 → 进度/错题 → 备注 → 打卡 → 卡片 → 导入自定义题 → 进度备份
 */
import { build } from 'esbuild'
import { resolve } from 'node:path'
import { readFileSync } from 'node:fs'

// ---- 浏览器全局对象 shim ----
const lsStore = new Map()
globalThis.localStorage = {
  getItem: (k) => (lsStore.has(k) ? lsStore.get(k) : null),
  setItem: (k, v) => lsStore.set(k, String(v)),
  removeItem: (k) => lsStore.delete(k),
  clear: () => lsStore.clear(),
}
const styleStub = { setProperty() {} }
globalThis.document = {
  documentElement: { style: styleStub },
  body: { dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, style: styleStub },
  head: { appendChild() {} },
  createElement: () => ({ set src(v) { this._src = v }, get src() { return this._src } }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
}
globalThis.location = { hash: '', href: 'http://127.0.0.1/app/' }
globalThis.window = globalThis
globalThis.alert = () => {}

// 题库数据：真实 public/qbank-data.js（window.QBANK_DATA 赋值即加载完成，跳过 <script> 注入）
new Function(readFileSync('public/qbank-data.js', 'utf8'))()
if (!globalThis.QBANK_DATA || !Array.isArray(globalThis.QBANK_DATA.questions)) {
  console.error('FAIL qbank-data.js 未正确挂载 window.QBANK_DATA')
  process.exit(1)
}

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
    // Element Plus 只用到消息提示，测试里替换为空实现（避免打包整个组件库）
    b.onResolve({ filter: /^element-plus(\/.*)?$/ }, () => ({ path: 'ep', namespace: 'ep-stub' }))
    b.onLoad({ filter: /.*/, namespace: 'ep-stub' }, () => ({
      loader: 'js',
      contents: [
        'export const ElMessage = { success(){}, error(){}, warning(){}, info(){} };',
        "export const ElMessageBox = { confirm: () => Promise.reject(new Error('cancel')) };",
        'export const ElSelect = {}, ElOption = {}, ElInput = {}, ElButton = {}, ElCheckbox = {};',
      ].join('\n'),
    }))
  },
}

await build({
  stdin: {
    contents: [
      "export * from './src/qbank/api.ts'",
      "export * from './src/qbank/bus.ts'",
      "export * from './src/qbank/session.ts'",
      "export * from './src/qbank/meta.ts'",
      "export * from './src/qbank/notes.ts'",
    ].join('\n'),
    resolveDir: process.cwd(),
    loader: 'ts',
  },
  bundle: true,
  format: 'esm',
  platform: 'browser',
  plugins: [aliasPlugin],
  define: {
    'process.env.NODE_ENV': '"production"',
    __VUE_OPTIONS_API__: 'true',
    __VUE_PROD_DEVTOOLS__: 'false',
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false',
  },
  outfile: 'test-qbank-bundle.mjs',
  logLevel: 'error',
})

const QB = await import('./test-qbank-bundle.mjs')

const results = []
const check = (name, ok, extra = '') => {
  results.push(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`)
}

// ---- 元信息 ----
const stats = await QB.api('/stats')
check('api(/stats) 返回', !!stats && typeof stats.total === 'number', 'total=' + (stats && stats.total))
check('题库非空', !!stats && stats.total > 0, 'total=' + (stats && stats.total))
check('难度分布 by_level', !!stats && Object.keys(stats.by_level || {}).length > 0)
check('题型分布 by_type', !!stats && Object.keys(stats.by_type || {}).length > 0)
check('间隔配置 intervals', Array.isArray(stats && stats.intervals) && stats.intervals.length > 0,
  stats && (stats.intervals || []).join('/'))

const banks = await QB.api('/banks')
check('api(/banks) 有题库', !!banks && (banks.items || []).length > 0, 'n=' + (banks && (banks.items || []).length))
const sections = await QB.api('/sections')
check('api(/sections) 有来源', !!sections && (sections.items || []).length > 0)

await QB.loadMeta()
check('loadMeta 填充 byType', Object.keys(QB.byType.value).length > 0)
check('loadMeta 填充 banks', QB.banks.value.length > 0)

// ---- 组卷 / 搜索 ----
const pick = await QB.api('/questions?limit=5')
const items = (pick && pick.items) || []
check('组卷返回 5 题', items.length === 5, 'n=' + items.length)
check('题目字段齐全', items.every((q) => q.id && q.stem && q.qtype))

const search = await QB.api('/questions?q=' + encodeURIComponent(items[0].stem.slice(0, 6)) + '&limit=5')
check('搜索命中', !!search && (search.items || []).length > 0, 'n=' + (search && (search.items || []).length))

const review = await QB.api('/questions?review=1&limit=5')
check('复习组卷可调用', Array.isArray(review && review.items))

const single = await QB.api('/questions/' + encodeURIComponent(items[0].id))
check('单题可读', !!single && single.item && single.item.id === items[0].id)

// ---- 判分 ----
const choice = items.find((q) => (q.options || []).length > 0 && /^[A-H]+$/.test(String(q.answer || '').trim()))
if (choice) {
  const wrongLetter = 'ABCDEFGH'.split('').find((l) => !String(choice.answer).includes(l))
  const gBad = await QB.api('/questions/' + encodeURIComponent(choice.id) + '/grade', { given: wrongLetter })
  check('选择题判错', !!gBad && gBad.correct === false, choice.id + ' 答 ' + wrongLetter + ' / 正确 ' + choice.answer)
  const gGood = await QB.api('/questions/' + encodeURIComponent(choice.id) + '/grade', { given: String(choice.answer).trim() })
  check('选择题判对', !!gGood && gGood.correct === true, choice.id)
} else {
  check('选择题判错（数据中无选择题，跳过）', true)
  check('选择题判对（数据中无选择题，跳过）', true)
}

// 自评题（问答/无字母答案）：correct 为 null 且 self=true
const selfQ = items.find((q) => !(q.options || []).length && !/^[A-H]+$/.test(String(q.answer || '').trim()))
if (selfQ) {
  const g = await QB.api('/questions/' + encodeURIComponent(selfQ.id) + '/grade', { given: '随便写点' })
  check('自评题返回 self', !!g && g.self === true && g.correct === null, selfQ.id)
} else {
  check('自评题返回 self（无样本，跳过）', true)
}

// ---- 进度 / 错题 ----
const target = items[1] || items[0]
const mBad = await QB.api('/progress/' + encodeURIComponent(target.id), { result: 'wrong' }, 'PUT')
check('mark wrong 返回 due', !!mBad && !!mBad.due, 'due=' + (mBad && mBad.due))
check('mark wrong streak=0', !!mBad && mBad.streak === 0)
const mOk = await QB.api('/progress/' + encodeURIComponent(target.id), { result: 'correct' }, 'PUT')
check('mark correct streak=1', !!mOk && mOk.streak === 1, 'streak=' + (mOk && mOk.streak))

const wrongList = await QB.api('/wrong')
const wrongIds = ((wrongList && wrongList.items) || []).map((x) => x.id)
check('错题本含刚答错题', wrongIds.includes(target.id), 'n=' + wrongIds.length)
check('错题条目带 wrong 次数', ((wrongList && wrongList.items) || []).every((x) => typeof x.wrong === 'number'))

// ---- 备注 ----
const noteQid = items[2] ? items[2].id : items[0].id
const put = await QB.api('/questions/' + encodeURIComponent(noteQid) + '/note', { note: '冒烟测试备注' }, 'PUT')
check('写备注成功', !!put && !put.error, JSON.stringify(put && (put.error || put.removed)))
await QB.loadNotes()
check('备注进入 notes 缓存', !!QB.notes.value[noteQid], noteQid)
check('备注进入 notesList', QB.notesList.value.some((n) => n.id === noteQid))
check('备注条目带题干摘要', (QB.notesList.value.find((n) => n.id === noteQid) || {}).stem !== '')
const got = await QB.api('/questions/' + encodeURIComponent(noteQid) + '/note')
check('单条备注可读', !!got && got.note === '冒烟测试备注')
const del = await QB.api('/questions/' + encodeURIComponent(noteQid) + '/note', null, 'DELETE')
check('删除备注成功', !!del && !del.error)
await QB.loadNotes()
check('删除后备注消失', !QB.notes.value[noteQid])

// ---- 打卡 ----
const ck = await QB.api('/checkins')
check('打卡日历字段', !!ck && typeof ck.streak === 'number' && Array.isArray(ck.days) && ck.days.length >= 28,
  'streak=' + (ck && ck.streak) + ' days=' + (ck && (ck.days || []).length))
const ckPost = await QB.api('/checkins', {}, 'POST')
check('手动补签成功', !!ckPost && ckPost.checked_today === true)
const ckPrev = await QB.api('/checkins?month=2026-01')
check('翻历史月份', !!ckPrev && ckPrev.month === '2026-01', ckPrev && ckPrev.month)

// ---- 知识点卡片 ----
const chapters = await QB.api('/chapters')
check('章节列表非空', !!chapters && (chapters.items || []).length > 0, 'n=' + (chapters && (chapters.items || []).length))
const cards = await QB.api('/cards?limit=20')
check('卡片列表非空', !!cards && (cards.items || []).length > 0, 'n=' + (cards && (cards.items || []).length))
const cardsFiltered = await QB.api('/cards?chapter=' + encodeURIComponent(((chapters.items || [])[0] || {}).chapter || ''))
check('按章节过滤', Array.isArray(cardsFiltered && cardsFiltered.items))

// ---- 导入 / 自定义题库 ----
const tpl = await QB.api('/template')
check('模板可导出', !!tpl && Array.isArray(tpl.questions) && tpl.questions.length > 0,
  'n=' + (tpl && (tpl.questions || []).length))
const imp = await QB.api('/import_questions', { questions: tpl.questions, mode: 'skip' })
check('导入模板题', !!imp && imp.added > 0, 'added=' + (imp && imp.added))
const impAgain = await QB.api('/import_questions', { questions: tpl.questions, mode: 'skip' })
check('重复导入被跳过', !!impAgain && impAgain.skipped > 0, 'skipped=' + (impAgain && impAgain.skipped))
const custom = await QB.api('/custom')
check('自定义题列表', !!custom && (custom.items || []).length > 0, 'n=' + (custom && (custom.items || []).length))
const S = await QB.store()
const cleared = S.clear_custom()
check('清空自定义题', cleared > 0, 'cleared=' + cleared)
const customAfter = await QB.api('/custom')
check('清空后为空', (customAfter.items || []).length === 0)

// ---- 进度备份 ----
const exp = await QB.api('/progress')
check('导出进度', !!exp && !!exp.progress && Object.keys(exp.progress).length > 0,
  'n=' + (exp && Object.keys(exp.progress || {}).length))
const imported = await QB.api('/progress', { progress: exp.progress })
check('导入进度合并', !!imported && imported.imported >= 0, 'imported=' + (imported && imported.imported))

// ---- bus / session ----
const v0 = QB.dataVersion.value
QB.bump()
check('bump 递增 dataVersion', QB.dataVersion.value === v0 + 1)

QB.startSession([{ id: 'X1' }, { id: 'X2' }], '测试组')
check('startSession 装载题目', QB.session.items.length === 2 && QB.session.label === '测试组')
check('startSession 重置计数', QB.session.i === 0 && QB.session.res.ok === 0 && Object.keys(QB.session.given).length === 0)
QB.session.i = 1
check('curQuestion 跟随下标', QB.curQuestion().id === 'X2')
QB.startSession([], '')
check('空会话清空', QB.session.items.length === 0 && QB.curQuestion() === null)

QB.goView('stats')
check('goView 切页', QB.view.value === 'stats')

console.log(results.join('\n'))
const fails = results.filter((r) => r.startsWith('FAIL'))
console.log(`\n===== ${results.length - fails.length}/${results.length} PASS =====`)
process.exit(fails.length ? 1 : 0)
