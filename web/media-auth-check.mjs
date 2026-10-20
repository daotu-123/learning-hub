/* M2c-P3 实测：媒体鉴权 + 前端图片仍正常。
 *
 * node media-auth-check.mjs <lan-base> <user> <pass>
 *
 * 关键：**必须走 LAN IP**，不能走 127.0.0.1。
 *   127.0.0.1 会命中服务端的「回环豁免」，媒体路径根本不校验签名——
 *   那样测出来的「图片正常」是假的。走 LAN IP 才是真实的公网/LAN 场景：
 *   服务端看到 client.host = LAN IP（非回环）→ 媒体必须凭签名或会话头。
 *
 * 浏览器侧模拟 APK：注入 window.Native 桥（loadPref/savePref 落到 localStorage），
 * 于是 IS_APP 为真、api() 走 hub_server（= LAN IP），与真机行为一致。
 */
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] || 'http://10.14.158.193:8645'
const USER = process.argv[3]
const PASS = process.argv[4]
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let failed = 0
function check(ok, name, note) {
  if (!ok) failed++
  console.log(`  [${ok ? '通过' : '失败'}] ${name}${note ? ' —— ' + note : ''}`)
}

console.log('媒体鉴权实测（LAN 场景）：' + BASE)
console.log('')
console.log('【一】未认证请求必须 401（媒体路径不再裸奔）')
for (const p of ['/img/a/b.png', '/photos/2026-08/x.jpg', '/api/hub/wallpapers/x.jpg']) {
  const r = await fetch(BASE + p)
  const b = await r.json().catch(() => null)
  check(r.status === 401, 'GET ' + p + ' → 401', 'status=' + r.status + (b ? ' error=' + JSON.stringify(b.error) : ''))
}

console.log('')
console.log('【二】伪造签名必须 401')
for (const p of ['/img/a/b.png?sig=AAAA&exp=99999999999', '/photos/2026-08/x.jpg?sig=&exp=']) {
  const r = await fetch(BASE + p)
  check(r.status === 401, '伪造签名 → 401', p + ' status=' + r.status)
}

console.log('')
console.log('【三】真浏览器（模拟 APK）：登录后照片页图片正常渲染')
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] })
const page = await browser.newPage()
const mediaReqs = []
const consoleErrs = []
page.on('request', (r) => { if (/\/img\/|\/photos\/|wallpapers/.test(r.url())) mediaReqs.push(r.url()) })
page.on('console', (m) => { if (m.type() === 'error') consoleErrs.push(m.text()) })

// 模拟 APK 原生桥：存在即 IS_APP=true；prefs 落到 localStorage（APK 里是 SharedPreferences）
await page.evaluateOnNewDocument((base) => {
  try { localStorage.setItem('hub_server', base) } catch (e) { /* noop */ }
  window.Native = {
    loadPref(k, d) { try { return localStorage.getItem(k) ?? d } catch (e) { return d } },
    savePref(k, v) { try { localStorage.setItem(k, v) } catch (e) { /* noop */ } },
    discoverServers() { return '[]' },
    getAndroid() { return 'test' },
  }
}, BASE)

try {
  await page.goto(BASE + '/app/', { waitUntil: 'networkidle2' })
  await sleep(1200)
  const isApp = await page.evaluate(() => typeof window.Native !== 'undefined')
  check(isApp, '已注入 Native 桥（IS_APP 场景）')

  await page.evaluate(() => localStorage.removeItem('hub_session'))
  await page.goto(BASE + '/app/#/login', { waitUntil: 'networkidle2' })
  await sleep(1200)
  await page.waitForSelector('input[name="username"]', { timeout: 10000 })
  await page.type('input[name="username"]', USER)
  await page.type('input[name="password"]', PASS)
  await page.keyboard.press('Enter')
  await sleep(2500)
  const hash = await page.evaluate(() => location.hash)
  check(hash.indexOf('#/login') < 0, '登录成功', 'hash=' + hash)

  // 壁纸（Blob 方案）
  await page.goto(BASE + '/app/#/hub', { waitUntil: 'networkidle2' })
  await sleep(2500)
  const bg = await page.evaluate(() => {
    const el = document.getElementById('wpLayer')
    return el ? el.style.backgroundImage : ''
  })
  check(bg.length > 0, '壁纸层已渲染', bg.slice(0, 80))

  // 照片页
  await page.goto(BASE + '/app/#/hub', { waitUntil: 'networkidle2' })
  await sleep(2000)
  await page.goto(BASE + '/app/#/desk/photos', { waitUntil: 'networkidle2' })
  await sleep(4000)
  const imgs = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('.photo-item img'))
    return els.map((e) => ({ src: e.src, w: e.naturalWidth, h: e.naturalHeight }))
  })
  console.log('  照片 <img> 数量：' + imgs.length)
  check(imgs.length > 0, '照片页渲染出图片（不是「离线模式」）', 'count=' + imgs.length)
  if (imgs.length) {
    check(imgs[0].src.indexOf('sig=') >= 0, '照片 URL 带签名参数', imgs[0].src.slice(0, 110))
    check(!/token=/.test(imgs[0].src), '照片 URL 不含 token 参数')
    check(imgs[0].src.indexOf('appassets') < 0, '照片 URL 指向真实服务器', imgs[0].src.slice(0, 60))
    const ok = imgs.filter((i) => i.w > 0).length
    check(ok === imgs.length, '全部照片实际解码成功（naturalWidth>0）', ok + '/' + imgs.length)
    for (const i of imgs) console.log('    ' + i.src + '  nw=' + i.w)
  }

  // 签名请求确实发出去了且返回 200
  const bad = mediaReqs.filter((u) => /token=/.test(u))
  check(bad.length === 0, '媒体请求 URL 一律不含 token', bad.slice(0, 2).join(' | '))
  check(mediaReqs.length > 0, '媒体请求确实发出去了', 'count=' + mediaReqs.length)
  check(consoleErrs.length === 0, '控制台无错误', consoleErrs.slice(0, 3).join(' | '))
} finally {
  await browser.close()
}

console.log('')
console.log(failed === 0 ? '合计：全部通过' : '合计：失败 ' + failed + ' 项')
process.exit(failed === 0 ? 0 : 1)
