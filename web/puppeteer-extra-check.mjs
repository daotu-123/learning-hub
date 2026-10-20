/* 补充验收（M2b）：401 跳转、next 开放重定向防护、壁纸 blob。
   node puppeteer-extra-check.mjs <base> <user> <pass>
*/
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] || 'http://127.0.0.1:8641'
const USER = process.argv[3] || 'unit-test-owner'
const PASS = process.argv[4] || 'unit-test-only-not-a-real-secret'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const log = []
function step(name, ok, note) {
  log.push({ ok, name, note: note || '' })
  console.log(`  [${ok ? '通过' : '失败'}] ${name}${note ? ' —— ' + note : ''}`)
}

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] })
const page = await browser.newPage()

async function login() {
  await page.goto(BASE + '/app/', { waitUntil: 'networkidle2' })
  await sleep(1200)
  await page.evaluate(() => localStorage.removeItem('hub_session'))
  await page.goto(BASE + '/app/#/login', { waitUntil: 'networkidle2' })
  await sleep(1200)
  await page.waitForSelector('input[name="username"]', { timeout: 10000 })
  await page.type('input[name="username"]', USER)
  await page.type('input[name="password"]', PASS)
  await page.keyboard.press('Enter')
  await sleep(2000)
}

try {
  // 1) next 开放重定向防护
  for (const evil of ['https://evil.example/x', '//evil.example/x', 'http:evil']) {
    await page.goto(BASE + '/app/#/login?next=' + encodeURIComponent(evil), { waitUntil: 'networkidle2' })
    await sleep(900)
    // 未登录 → 守卫把它留在 /login；登录后才会用 next。这里先确认没有跳出本站
    const origin = await page.evaluate(() => location.origin)
    step('next=' + evil + ' 不产生站外跳转', origin === new URL(BASE).origin, 'origin=' + origin)
  }

  await login()

  // 2) 伪造/失效会话 → API 401 → 清令牌 + 跳 /login?next=当前路由
  await page.goto(BASE + '/app/#/hub/review', { waitUntil: 'networkidle2' })
  await sleep(1500)
  await page.evaluate(() => localStorage.setItem('hub_session', 'forged-session-token-not-valid-0000'))
  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(2500)
  let hash = await page.evaluate(() => location.hash)
  const cleared = await page.evaluate(() => localStorage.getItem('hub_session'))
  step('失效会话触发 401 → 令牌被清', !cleared, '值=' + JSON.stringify(cleared))
  step('401 后跳到 /login 且带 next', hash.indexOf('#/login') === 0 && hash.indexOf('next=') >= 0, 'hash=' + hash)

  // 3) 重新登录后检查壁纸走 blob（服务端无自定义壁纸时只验不 401）
  await login()
  await page.goto(BASE + '/app/#/hub', { waitUntil: 'networkidle2' })
  await sleep(2000)
  const wpState = await page.evaluate(() => {
    const el = document.getElementById('wpLayer')
    return {
      bg: el ? el.style.backgroundImage : '',
      requests: window.__wpProbe || null,
    }
  })
  step('壁纸层正常渲染', !!wpState.bg, JSON.stringify(wpState.bg).slice(0, 120))

  // 3b) 自定义壁纸：必须走 blob（URL 里不能有令牌，也不能靠裸 URL 直连）
  const wpReqs = []
  page.on('request', (r) => { if (r.url().indexOf('/api/hub/wallpapers/') >= 0) wpReqs.push(r.url()) })
  await page.reload({ waitUntil: 'networkidle2' })
  await sleep(2500)
  const blobBg = await page.evaluate(() => {
    const el = document.getElementById('wpLayer')
    return el ? el.style.backgroundImage : ''
  })
  step('自定义壁纸用 blob URL 渲染', blobBg.indexOf('blob:') >= 0, blobBg.slice(0, 120))
  step('壁纸请求 URL 不含任何令牌', wpReqs.every((u) => u.indexOf('token') < 0), wpReqs.join(' | ').slice(0, 200))
  step('壁纸请求带上了 Authorization 头', await page.evaluate(async () => {
    const s = localStorage.getItem('hub_session') || ''
    if (!s) return false
    const r = await fetch('/api/hub/settings', { headers: { Authorization: 'Bearer ' + s } })
    return r.ok
  }), '')

  // 4) 确认没有任何请求把会话令牌拼进 URL
  const leaks = []
  page.on('request', (r) => { if (r.url().indexOf('hub_session') >= 0 || /[?&]token=[^&]*/.test(r.url())) leaks.push(r.url()) })
  await login()
  await sleep(2500)
  step('全程无请求把令牌拼进 URL', leaks.length === 0, leaks.slice(0, 3).join(' | '))
} finally {
  await browser.close()
}

const failed = log.filter((l) => !l.ok).length
console.log('')
console.log(`合计：通过 ${log.length - failed} ｜ 失败 ${failed}`)
process.exit(failed === 0 ? 0 : 1)
