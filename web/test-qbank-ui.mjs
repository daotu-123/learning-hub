/* 题库 UI 端到端测试（puppeteer-core + 本机 Chrome，手机尺寸）
 *
 * 前置：build-tools/verify_server.py 在 8639 提供 /app 静态 + /api 代理
 * 运行：node test-qbank-ui.mjs
 */
import puppeteer from 'puppeteer-core'
import { writeFileSync, mkdirSync } from 'node:fs'

const BASE = process.env.QB_BASE || 'http://127.0.0.1:8639/app/'
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT = 'test-shots'

const results = []
const check = (name, ok, extra = '') => {
  results.push(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`)
}

mkdirSync(OUT, { recursive: true })

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--font-render-hinting=none'],
})

const page = await browser.newPage()
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true })

const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()) })
page.on('requestfailed', (r) => errors.push('reqfail: ' + r.url()))
page.on('response', (r) => { if (r.status() >= 400) errors.push('http ' + r.status() + ': ' + r.url()) })

async function clickText(text, scope = '.qbank') {
  const ok = await page.evaluate((t, sc) => {
    const root = document.querySelector(sc)
    if (!root) return false
    const el = [...root.querySelectorAll('button, a, .el-button')].find(
      (b) => (b.textContent || '').replace(/\s+/g, '') === t.replace(/\s+/g, ''))
    if (!el) return false
    el.click()
    return true
  }, text, scope)
  return ok
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

try {
  await page.goto(BASE + '#/qbank/quiz', { waitUntil: 'networkidle2', timeout: 30000 })
  await page.waitForSelector('.qbank header .brand h1', { timeout: 20000 })

  // ---- 外壳 ----
  const shell = await page.evaluate(() => {
    const q = document.querySelector('.qbank')
    const pill = document.querySelector('.qbank .mode-pill')
    const nav = document.querySelector('.qbank nav')
    return {
      title: (document.querySelector('.qbank header h1') || {}).textContent,
      pill: pill ? pill.textContent.trim() : '',
      pillRight: pill ? Math.round(pill.getBoundingClientRect().right) : -1,
      navScrollW: nav ? nav.scrollWidth : 0,
      rowW: (() => { const r = document.querySelector('.qb-navrow'); return r ? r.scrollWidth : 0 })(),
      rowClient: (() => { const r = document.querySelector('.qb-navrow'); return r ? r.clientWidth : 0 })(),
      navClientW: nav ? nav.clientWidth : 0,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      navOn: [...document.querySelectorAll('.qbank nav a.on, .qbank nav a.active')].map((a) => a.textContent.trim()),
    }
  })
  check('标题为机械题库', shell.title === '机械题库', shell.title)
  check('离线模式徽章', shell.pill === '离线模式', shell.pill)
  check('徽章在视口内', shell.pillRight > 0 && shell.pillRight <= shell.innerW + 1, 'right=' + shell.pillRight + '/vp=' + shell.innerW)
  check('无横向溢出', shell.scrollW <= shell.innerW + 1, `scrollW=${shell.scrollW} innerW=${shell.innerW}`)
  check('导航单行不溢出', shell.rowW <= shell.rowClient + 1, `${shell.rowW}/${shell.rowClient}`)
  check('刷题页高亮', shell.navOn.some((t) => t.includes('刷题')), shell.navOn.join('|'))

  await page.screenshot({ path: OUT + '/01-quiz.png' })

  // ---- 组卷 ----
  check('点击「开始组卷」', await clickText('开始组卷'))
  await page.waitForSelector('#quiz-area .q', { timeout: 15000 })
  const q1 = await page.evaluate(() => {
    const card = document.querySelector('#quiz-area .q')
    const badge = document.querySelector('#quiz-area .qtype-badge')
    const prog = document.querySelector('#quiz-area .q-progress')
    return { stem: card.textContent.trim().slice(0, 30), qtype: badge ? badge.textContent.trim() : '', prog: prog ? prog.textContent.replace(/\s+/g, ' ') : '' }
  })
  check('题卡出现', !!q1.stem, q1.stem)
  check('题型徽章有值', !!q1.qtype, q1.qtype)
  check('进度显示 1/N', /^第 ?1/.test(q1.prog), q1.prog)
  await page.screenshot({ path: OUT + '/02-question.png' })

  // ---- 作答（填空/问答两条路径）----
  const kind = await page.evaluate(() => {
    const card = document.querySelector('#quiz-area .card')
    if (!card) return 'unknown'
    if (card.querySelector('.judge-row')) return 'judge'
    if (card.querySelector('.opt')) return 'choice'
    if (card.querySelector('.el-input')) return 'fill'
    if (card.querySelector('textarea')) return 'free'
    return 'unknown'
  })
  check('识别题型交互', kind !== 'unknown', kind)

  if (kind === 'fill') {
    const inputs = await page.$$('#quiz-area .el-input__inner')
    if (inputs.length) await inputs[0].type('测试答案')
  } else if (kind === 'free') {
    await page.type('#quiz-area textarea', '自己先答一遍，冒烟测试内容')
  } else if (kind === 'choice') {
    await page.click('#quiz-area .opt')
  } else if (kind === 'judge') {
    await page.click('#quiz-area .opt.judge')
  }

  check('点击「提交」', await clickText('提交', '#quiz-area'))
  await page.waitForSelector('#quiz-area .fb', { timeout: 10000 })
  const fb1 = await page.evaluate(() => {
    const fb = document.querySelector('#quiz-area .fb')
    return { cls: fb.className, text: fb.textContent.replace(/\s+/g, ' ').trim().slice(0, 60) }
  })
  check('反馈框出现', /fb/.test(fb1.cls), fb1.cls.replace('fb ', ''))
  check('反馈有内容', fb1.text.length > 4, fb1.text)
  await page.screenshot({ path: OUT + '/03-feedback.png' })

  // 自评题：点「我答对了」写入进度
  const hasSelf = await page.evaluate(() => !!document.querySelector('#quiz-area .fb button'))
  if (hasSelf) {
    check('点击「我答对了」', await clickText('我答对了', '#quiz-area'))
    await sleep(400)
    const flash = await page.evaluate(() => {
      const el = document.querySelector('#quiz-area .fb .meta')
      return el ? el.textContent.trim() : ''
    })
    check('自评后写入进度提示', flash.includes('掌握') || flash.includes('错题本') || flash.includes('下次复习'), flash.slice(0, 40))
  } else {
    check('自评按钮（本题自动判分，跳过）', true)
  }

  // ---- 下一题 ----
  const before = await page.evaluate(() => document.querySelector('#quiz-area .q-progress b').textContent)
  check('点击「下一题」', await clickText('下一题', '#quiz-area'))
  await sleep(500)
  const after = await page.evaluate(() => {
    const b = document.querySelector('#quiz-area .q-progress b')
    return b ? b.textContent : ''
  })
  check('题号前进', Number(after) === Number(before) + 1, `${before} → ${after}`)

  // ---- 键盘快捷键 ----
  const beforeKey = await page.evaluate(() => document.querySelector('#quiz-area .q-progress b').textContent)
  await page.keyboard.press('ArrowRight')
  await sleep(300)
  const afterKey = await page.evaluate(() => document.querySelector('#quiz-area .q-progress b').textContent)
  check('→ 键下一题', Number(afterKey) === Number(beforeKey) + 1, `${beforeKey} → ${afterKey}`)

  // ---- 知识点 ----
  check('切到「知识点」', await clickText('知识点'))
  await sleep(700)
  const cards = await page.evaluate(() => document.querySelectorAll('.qbank .card-item').length)
  check('知识点卡片渲染', cards > 0, 'n=' + cards)
  await page.screenshot({ path: OUT + '/04-cards.png' })

  // ---- 进度 ----
  check('切到「进度」', await clickText('进度'))
  await page.waitForSelector('.qbank .ck-cal', { timeout: 15000 })
  const stats = await page.evaluate(() => ({
    kpis: [...document.querySelectorAll('.qbank .kpi')].map((k) => k.textContent.replace(/\s+/g, ' ').trim()),
    cells: document.querySelectorAll('.qbank .ck-cal .cell').length,
    bars: document.querySelectorAll('.qbank .bar i').length,
  }))
  check('KPI 数量 7', stats.kpis.length === 7, stats.kpis.length + ' ' + stats.kpis.slice(0, 3).join(' / '))
  check('打卡日历有格子', stats.cells >= 28, 'n=' + stats.cells)
  check('分布条渲染', stats.bars >= 5, 'n=' + stats.bars)
  await page.screenshot({ path: OUT + '/05-stats.png', fullPage: false })

  // ---- 错题 ----
  check('切到「错题」', await clickText('错题'))
  await sleep(600)
  const wrong = await page.evaluate(() => {
    const items = document.querySelectorAll('.qbank .card-item').length
    const empty = !!document.querySelector('.qbank .empty')
    return { items, empty }
  })
  check('错题页可用', wrong.items > 0 || wrong.empty, 'items=' + wrong.items + ' empty=' + wrong.empty)

  // ---- 今日复习 ----
  check('切到「今日复习」', await clickText('今日复习'))
  await sleep(600)
  const review = await page.evaluate(() => document.querySelector('.qbank section .card').textContent.replace(/\s+/g, ' ').trim())
  check('复习页加载', review.includes('到期'), review.slice(0, 30))

  // ---- 三 Tab 往返后状态保留（keep-alive + 模块 store）----
  await page.click('.shell-nav .shell-tab:nth-child(1)')
  await sleep(600)
  const hubVisible = await page.evaluate(() => !!document.querySelector('.hub'))
  check('切回学习中枢', hubVisible)
  await page.click('.shell-nav .shell-tab:nth-child(2)')
  await sleep(800)
  const back = await page.evaluate(() => ({
    qbank: !!document.querySelector('.qbank'),
    live: !!document.querySelector('.qbank section'),
    active: [...document.querySelectorAll('.qbank nav a.active')].map((a) => a.textContent.trim()),
  }))
  check('切回题库保留视图', back.qbank && back.live, back.active.join('|'))

  check('无 JS 运行错误', errors.length === 0, errors.slice(0, 3).join(' ; '))
} finally {
  await browser.close()
}

console.log(results.join('\n'))
const fails = results.filter((r) => r.startsWith('FAIL'))
writeFileSync(OUT + '/result.txt', results.join('\n'))
console.log(`\n===== ${results.length - fails.length}/${results.length} PASS =====`)
process.exit(fails.length ? 1 : 0)
