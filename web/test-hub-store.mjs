/* 学习中枢 store 冒烟测试：Node + 真实后端（8637）
   运行：node test-hub-store.mjs */
import { build } from 'esbuild'
import { resolve } from 'node:path'
import { readFileSync } from 'node:fs'

// ---- 浏览器全局对象 shim ----
const lsStore = new Map()
lsStore.set('hub_server', 'http://127.0.0.1:8637') // 指向后端
globalThis.localStorage = {
  getItem: (k) => (lsStore.has(k) ? lsStore.get(k) : null),
  setItem: (k, v) => lsStore.set(k, String(v)),
  removeItem: (k) => lsStore.delete(k),
}
const styleStub = { setProperty() {}, }
globalThis.document = {
  documentElement: { style: styleStub },
  body: { dataset: {} },
  getElementById: () => null,
  title: '',
  hidden: false,
  addEventListener() {},
  removeEventListener() {},
}
globalThis.location = { hash: '', href: 'http://127.0.0.1:8639/app/' }
globalThis.window = globalThis

// ---- 打包 src/hub/hubStore.ts（@ 别名 → src/） ----
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
  entryPoints: ['src/hub/hubStore.ts'],
  bundle: true,
  format: 'esm',
  platform: 'browser',
  plugins: [aliasPlugin],
  outfile: 'test-hub-bundle.mjs',
  logLevel: 'error',
})

const hub = await import('./test-hub-bundle.mjs')

const results = []
const check = (name, ok, extra = '') => {
  results.push(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`)
}

// initHub：读设置 + today + heat + pomo
await hub.initHub()
check('initHub 无异常', true)
check('settings 已加载', !!hub.hubState.settings, 'wallpaper=' + (hub.hubState.settings || {}).wallpaper)
check('today 已加载', !!hub.hubState.today, 'due_today=' + (hub.hubState.today || {}).review?.due_today)
check('heat 30 格', hub.hubState.heat.length === 30, 'len=' + hub.hubState.heat.length)

// 视图切换
for (const v of ['plans', 'review', 'focus', 'feedback', 'library']) {
  await hub.showHubView(v)
  check('showHubView(' + v + ')', true)
}
check('plans 返回数组', Array.isArray(hub.plansView()))
check('review stats 4 项', hub.reviewStatsView().length === 4)
check('focus 图表 7 天', hub.focusChartView().length === 7, 'today=' + JSON.stringify(hub.focusTodayView()))

// classroom（OpenMAIC 状态/文档/任务）
await hub.showHubView('classroom')
check('om status view', typeof hub.omStatusView().line === 'string')
check('om docs view', typeof hub.omDocsView().count === 'number', 'total=' + hub.omDocsView().total)
check('om jobs view', typeof hub.omJobsView().tag === 'string')

// 计划添加 + 打卡 + 删除（真实写后端）
const planName = '__smoke_' + Date.now()
await hub.planAdd(planName)
const mine = hub.plansView().find((x) => x.name === planName)
check('planAdd 生效', !!mine)
if (mine) {
  const todayDay = mine.days.find((d) => d.date === hub.hubState.date && d.custom)
  check('自建计划含今日格', !!todayDay)
  if (todayDay) {
    const willDone = !todayDay.done
    await hub.planToggleDay(mine.id, todayDay.date, willDone)
    await hub.loadPlans() // 重新拉取，验证服务端已生效
    const day2 = hub.plansView().find((x) => x.name === planName)
      .days.find((d) => d.date === hub.hubState.date && d.custom)
    check('planToggleDay 打卡（服务端生效）', day2.done === willDone)
  }
  await hub.planDelete(mine.id)
  check('planDelete 删除', !hub.plansView().find((x) => x.name === planName))
}

// 番茄钟逻辑
hub.pomoSetMinutes(45)
check('pomoSetMinutes(45)', hub.hubState.pomo.minutes === 45 && hub.hubState.pomo.total === 2700)

// 视图渲染函数
const revItem = { concept: '测试概念', reviews: 2, interval_days: 3, next_review: '2099-01-01' }
check('revItemView 结构', hub.revItemView(revItem).meta.includes('间隔 3 天'))
check('esc 转义', hub.esc('<b>&"') === '&lt;b&gt;&amp;&quot;')
check('fmtDate', hub.fmtDate('2026-10-18') === '2026.10.18')
check('todayStatsView 4 项', hub.todayStatsView().length === 4)

console.log(results.join('\n'))
const fails = results.filter((r) => r.startsWith('FAIL'))
console.log(`\n===== ${results.length - fails.length}/${results.length} PASS =====`)
process.exit(fails.length ? 1 : 0)
