/* 手工验证清单的自动化执行（M2b）：真浏览器 + 真页面。
   只在本轮验收时用，不进 npm scripts（它依赖本机 Chrome 路径）。
   node puppeteer-manual-check.mjs http://127.0.0.1:8641 user pass
*/
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] || 'http://127.0.0.1:8641'
const USER = process.argv[3] || 'unit-test-owner'
const PASS = process.argv[4] || 'unit-test-only-not-a-real-secret'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'

const log = []
function step(name, ok, note) {
  log.push({ name, ok, note: note || '' })
  console.log(`  [${ok ? '通过' : '失败'}] ${name}${note ? ' —— ' + note : ''}`)
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function waitHash(page, want, timeout = 8000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    const h = await page.evaluate(() => location.hash)
    if (h === want) return true
    await sleep(200)
  }
  return false
}

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1280, height: 900 })

try {
  // 1) 未登录访问 /app → 被送到 /login
  await page.goto(BASE + '/app/', { waitUntil: 'networkidle2' })
  await sleep(1200)
  let hash = await page.evaluate(() => location.hash)
  step('浏览器打开 /app → 未登录被送到 /login', hash.indexOf('#/login') === 0, 'hash=' + hash)
  const hasNext = hash.indexOf('next=') >= 0
  step('登录页带上 next 参数', hasNext, hash)
  const hasBottomNav = await page.evaluate(() => !!document.querySelector('.shell-nav'))
  step('登录页无底部导航', !hasBottomNav, '')

  // 2) 错误口令 → 统一提示
  await page.type('input[name="username"]', USER)
  await page.type('input[name="password"]', 'definitely-wrong-pass')
  await page.keyboard.press('Enter')
  await sleep(1200)
  const errText = await page.evaluate(() => {
    const el = document.querySelector('.login .err')
    return el ? el.textContent.trim() : ''
  })
  step('错误口令提示统一为「用户名或口令错误」', errText === '用户名或口令错误', '文案=' + JSON.stringify(errText))
  hash = await page.evaluate(() => location.hash)
  step('口令错误不发生跳转（无 401 循环）', hash.indexOf('#/login') === 0, 'hash=' + hash)

  // 3) 正确口令 → 回到原页面
  await page.evaluate(() => { document.querySelector('input[name="password"]').value = '' })
  await page.click('input[name="password"]', { clickCount: 3 })
  await page.type('input[name="password"]', PASS)
  await page.keyboard.press('Enter')
  await sleep(2000)
  hash = await page.evaluate(() => location.hash)
  step('登录成功后回到原页面', hash.indexOf('#/login') < 0, 'hash=' + hash)
  const stored = await page.evaluate(() => localStorage.getItem('hub_session') || '')
  step('令牌写入 localStorage.hub_session', stored.length > 20, 'len=' + stored.length)

  // 4) 刷新后仍登录
  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(1500)
  hash = await page.evaluate(() => location.hash)
  step('刷新后仍登录', hash.indexOf('#/login') < 0, 'hash=' + hash)

  // 5) 手动删 localStorage 再刷新 → 回登录页
  await page.evaluate(() => localStorage.removeItem('hub_session'))
  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(1500)
  hash = await page.evaluate(() => location.hash)
  step('删掉 hub_session 再刷新 → 自动回登录页', hash.indexOf('#/login') === 0, 'hash=' + hash)

  // 6) 375px 宽度下无横向滚动
  await page.setViewport({ width: 375, height: 720 })
  await sleep(500)
  const overflow = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  step('375px 宽度下登录页无横向滚动', overflow.scroll <= overflow.client + 1, JSON.stringify(overflow))

  // 7) 触控目标 ≥44px
  const targets = await page.evaluate(() => {
    const out = []
    for (const el of document.querySelectorAll('.login input, .login button')) {
      const r = el.getBoundingClientRect()
      out.push({ tag: el.tagName, h: Math.round(r.height), w: Math.round(r.width) })
    }
    return out
  })
  const tooSmall = targets.filter((t) => t.h < 44 || t.w < 44)
  step('触控目标 ≥44px', tooSmall.length === 0, tooSmall.length ? JSON.stringify(tooSmall) : JSON.stringify(targets))

  // 8) 登录后登出 → 回 /login，刷新不复活
  await page.setViewport({ width: 1280, height: 900 })
  await page.evaluate(() => localStorage.setItem('hub_session', ''))
  await page.type('input[name="username"]', USER)
  await page.click('input[name="password"]', { clickCount: 3 })
  await page.type('input[name="password"]', PASS)
  await page.keyboard.press('Enter')
  await sleep(2000)
  const loggedIn = (await page.evaluate(() => location.hash)).indexOf('#/login') < 0
  if (loggedIn) {
    // 走设置面板里的「退出登录」
    const opened = await page.evaluate(() => {
      const b = document.querySelector('.gear-btn')
      if (!b) return false
      b.click()
      return true
    })
    await sleep(900)
    const clicked = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('.hub .modal button'))
      const t = btns.find((x) => x.textContent.trim() === '退出登录')
      if (!t) return false
      t.click()
      return true
    })
    step('设置面板可打开并找到「退出登录」', opened && clicked, '')
    await sleep(1500)
    hash = await page.evaluate(() => location.hash)
    step('登出后回到 /login', hash.indexOf('#/login') === 0, 'hash=' + hash)
    const after = await page.evaluate(() => localStorage.getItem('hub_session'))
    step('登出后 localStorage 令牌已清', !after, '值=' + JSON.stringify(after))
    await page.reload({ waitUntil: 'networkidle2' })
    await sleep(1500)
    hash = await page.evaluate(() => location.hash)
    step('登出后刷新不复活', hash.indexOf('#/login') === 0, 'hash=' + hash)
  } else {
    step('二次登录成功（用于验证登出）', false, 'hash=' + await page.evaluate(() => location.hash))
  }
} finally {
  await browser.close()
}

const failed = log.filter((l) => !l.ok).length
console.log('')
console.log(`合计：通过 ${log.length - failed} ｜ 失败 ${failed}`)
process.exit(failed === 0 ? 0 : 1)
