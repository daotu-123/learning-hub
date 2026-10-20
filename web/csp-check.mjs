/* M2c-P4 实测：最小 CSP 加固后，所有页面功能正常且控制台无 CSP violation。
 *
 * node csp-check.mjs <lan-base> <user> <pass>
 *
 * 同样**必须走 LAN IP**：127.0.0.1 命中回环豁免，媒体与 API 都不校验凭证，
 * 那样测出来的「页面正常」在公网场景下不成立。
 *
 * 检查分两块：
 *   A. 响应头 —— curl 式断言（走 puppeteer 的 request 事件，直接读线上真头）
 *   B. 真浏览器 —— /hub、题库、照片页、壁纸、日记，逐页收集 console 错误，
 *      凡是形如 "Refused to …"（CSP violation 的标准措辞）一律判失败。
 */
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] || 'http://10.14.158.193:8646'
const USER = process.argv[3]
const PASS = process.argv[4]
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let failed = 0
function check(ok, name, note) {
  if (!ok) failed++
  console.log(`  [${ok ? '通过' : '失败'}] ${name}${note ? ' —— ' + note : ''}`)
}

console.log('CSP / 安全响应头实测（LAN 场景）：' + BASE)

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] })

// 【一】响应头 —— 通过真实请求读线上真头，不另起 curl，避免"两边环境不同"
console.log('')
console.log('【一】安全响应头')
{
  const page = await browser.newPage()
  const port = new URL(BASE).port
  const seen = {}
  page.on('response', (r) => {
    const u = new URL(r.url())
    // 用 r.status() 无法区分，这里只按路径匹配；注意 /app 与 /app/ 都要算
    if (u.port !== port) return
    if (u.pathname === '/app' || u.pathname === '/app/') seen.app = r.headers()
    if (u.pathname.startsWith('/api/summary')) seen.api = r.headers()
  })
  await page.goto(BASE + '/app/', { waitUntil: 'domcontentloaded' })
  await sleep(1500)

  const h = seen.app || {}
  const csp = h['content-security-policy'] || ''
  check(!!csp, '/app 下发 CSP 响应头')
  check(csp.indexOf("frame-ancestors 'none'") >= 0, 'CSP 含 frame-ancestors（meta 写了不生效，只能靠头）')
  check(csp.indexOf('unsafe-eval') < 0, 'CSP 无 unsafe-eval', csp.slice(0, 40) + '…')
  // unsafe-inline 只允许出现在 style-src-attr（Vue 静态 style 会编译成 cssText 赋值）
  check(!/style-src\s+'[^']*unsafe-inline/.test(csp.replace(/style-src-attr[^;]*/, '')),
    "style-src（<style>/样式表）无 unsafe-inline")
  check(csp.indexOf("style-src-attr 'unsafe-inline'") >= 0,
    'style-src-attr 放开（Vue 静态 style 走 cssText）')
  check(csp.indexOf("object-src 'none'") >= 0, "object-src 'none'")
  check(csp.indexOf("script-src 'self'") >= 0, "script-src 'self'（无 unsafe-inline 兜底）")
  for (const k of ['x-content-type-options', 'referrer-policy', 'x-frame-options']) {
    check(!!h[k], '响应头含 ' + k, h[k] || '(缺失)')
  }
  check(h['x-content-type-options'] === 'nosniff', 'nosniff 正确', h['x-content-type-options'])
  check(h['referrer-policy'] === 'no-referrer', 'no-referrer 正确', h['referrer-policy'])

  // /hub 不下发 CSP —— 旧页有内联 style/script，套上会打挂。用测试锁住这个取舍。
  const hubPage = await browser.newPage()
  let hubHeaders = {}
  hubPage.on('response', (r) => {
    const u = new URL(r.url())
    if (u.port !== port) return
    if (u.pathname === '/hub') hubHeaders = r.headers()
  })
  await hubPage.goto(BASE + '/hub', { waitUntil: 'domcontentloaded' }).catch(() => {})
  await sleep(800)
  if (Object.keys(hubHeaders).length) {
    check(!hubHeaders['content-security-policy'], '/hub 不下发 CSP（旧页有内联脚本）',
      hubHeaders['content-security-policy'] || '(无)')
    check(!!hubHeaders['x-content-type-options'], '/hub 仍带 nosniff')
  } else {
    console.log('  [跳过] /hub 未部署，本机无法验证')
  }
  await hubPage.close()
  await page.close()
}

// 【二】真浏览器逐页验证：功能 + 控制台零 CSP violation
console.log('')
console.log('【二】真浏览器逐页验证（收集全部 console 错误与页面异常）')
const page = await browser.newPage()
const consoleErrs = []
const pageErrs = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrs.push(m.text()) })
page.on('pageerror', (e) => pageErrs.push(String(e && e.message || e)))
// CSP violation 有两种出现方式：console error（Chrome）或拦截事件。两边都收。
page.on('requestfailed', (r) => {
  consoleErrs.push('requestfailed ' + r.url() + ' ' + (r.failure() && r.failure().errorText || ''))
})

// 模拟 APK 原生桥（同 P3）：让 IS_APP 成立、api() 走 hub_server
await page.evaluateOnNewDocument((base) => {
  try { localStorage.setItem('hub_server', base) } catch (e) { /* noop */ }
  window.Native = {
    loadPref(k, d) { try { return localStorage.getItem(k) ?? d } catch (e) { return d } },
    savePref(k, v) { try { localStorage.setItem(k, v) } catch (e) { /* noop */ } },
    discoverServers() { return '[]' },
    getAndroid() { return 'test' },
  }
}, BASE)

const CSP_MARK = /Refused to|Content Security Policy|violates the following/i
function cspViolations() {
  return consoleErrs.filter((t) => CSP_MARK.test(t))
}

async function visit(hash, name, probe) {
  const before = consoleErrs.length
  await page.goto(BASE + '/app/' + hash, { waitUntil: 'networkidle2' })
  await sleep(3000)
  if (probe) {
    const r = await probe()
    check(r.ok, name, r.note)
  } else {
    check(true, name + '（页面已加载）')
  }
  const newErrs = consoleErrs.slice(before)
  const v = newErrs.filter((t) => CSP_MARK.test(t))
  check(v.length === 0, name + ' 无 CSP violation', v.slice(0, 2).join(' | '))
}

try {
  await page.goto(BASE + '/app/', { waitUntil: 'networkidle2' })
  await sleep(1500)
  await page.evaluate(() => localStorage.removeItem('hub_session'))
  await page.goto(BASE + '/app/#/login', { waitUntil: 'networkidle2' })
  await sleep(1200)

  // 登录页本身在 CSP 下必须能渲染（LoginView 是独立 chunk）
  await visit('#/login', '登录页渲染', async () => {
    const has = await page.$('input[name="username"]')
    return { ok: !!has, note: has ? '输入框已渲染' : '未找到用户名输入框' }
  })

  await page.waitForSelector('input[name="username"]', { timeout: 10000 })
  await page.type('input[name="username"]', USER)
  await page.type('input[name="password"]', PASS)
  await page.keyboard.press('Enter')
  await sleep(2500)
  const hash = await page.evaluate(() => location.hash)
  check(hash.indexOf('#/login') < 0, '登录成功（CSP 未挡 fetch）', 'hash=' + hash)

  // 壁纸（Blob +签名 URL → img-src 需 blob:/http:）
  await visit('#/hub', '壁纸 / hub 页', async () => {
    const r = await page.evaluate(() => {
      const el = document.getElementById('wpLayer')
      return { bg: el ? el.style.backgroundImage : '', text: (document.body.innerText || '').length }
    })
    return { ok: r.bg.length > 0 && r.text > 20, note: (r.bg || '(无背景)').slice(0, 70) + ' 文本长度=' + r.text }
  })

  // 题库：走动态 import 的独立 chunk + 动态注入 qbank-data.js（script-src 'self' 的关键用例）
  await visit('#/qbank', '题库页（动态 chunk + 注入 qbank-data.js）', async () => {
    const r = await page.evaluate(() => ({
      body: (document.body.innerText || '').slice(0, 120),
      len: (document.body.innerText || '').length,
    }))
    return { ok: r.len > 40, note: r.body.replace(/\n/g, ' / ').slice(0, 100) }
  })

  // 照片页：签名 URL（img-src 需 http(s):）
  await visit('#/desk/photos', '照片页（签名媒体 URL）', async () => {
    const imgs = await page.evaluate(() => Array.from(document.querySelectorAll('.photo-item img'))
      .map((e) => ({ src: e.src, w: e.naturalWidth })))
    const ok = imgs.length > 0 && imgs.every((i) => i.w > 0)
    return {
      ok,
      note: imgs.length
        ? `${imgs.filter((i) => i.w > 0).length}/${imgs.length} 解码成功；首个 ${imgs[0].src.slice(0, 90)}`
        : '未渲染出 <img>（可能是离线模式）',
    }
  })

  // 日记（若有图片走签名 URL）
  await visit('#/desk/diary', '日记页', async () => {
    const r = await page.evaluate(() => (document.body.innerText || '').length)
    return { ok: r > 10, note: '文本长度=' + r }
  })

  // 任务列表（最普通的一页，确认没被 CSP 误伤）
  await visit('#/desk/tasks', '任务页', async () => {
    const r = await page.evaluate(() => (document.body.innerText || '').length)
    return { ok: r > 5, note: '文本长度=' + r }
  })

  console.log('')
  console.log('【三】控制台全局汇总')
  const v = cspViolations()
  check(v.length === 0, '全程零 CSP violation', v.slice(0, 3).join(' | ') || '无')
  console.log('  console error 总数：' + consoleErrs.length)
  for (const t of consoleErrs.slice(0, 6)) console.log('    · ' + t.slice(0, 160))
  check(pageErrs.length === 0, '无未捕获 JS 异常', pageErrs.slice(0, 2).join(' | '))
} finally {
  await browser.close()
}

console.log('')
console.log(failed === 0 ? '合计：全部通过' : '合计：失败 ' + failed + ' 项')
process.exit(failed === 0 ? 0 : 1)