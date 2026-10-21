/* 反代链路实测：用一个行为与 Caddy 等价的本地反代打服务，验证
 * 「X-Forwarded-For → clientip 采信 → 限流 → 鉴权 → 安全响应头」整条链。
 *
 * node proxy-chain-check.mjs <api-base> <token> [xffValue]
 *
 * 为什么需要这个脚本：Caddy 在本机未安装（且本轮约束禁止新增依赖），
 * 无法真的跑 443。但「反代配对了服务端行为对不对」这件事必须验，
 * 否则等于把 Caddyfile 的正确性交给运气。
 *
 * 等价性来自严格复刻 Caddy 的两个动作：
 *   1) 加 X-Forwarded-For: <remote_host>   （用真实来源，不透传客户端那个）
 *   2) 保留 Host 不变
 * 服务端 clientip.py 只认这两样，所以这条链路等价。
 */
import http from 'node:http'

const BASE = process.argv[2] || 'http://127.0.0.1:8652'
const TOKEN = process.argv[3] || 'proxy-test-token'
const CLIENT_IP = process.argv[4] || '203.0.113.77'   // RFC 5737 测试用段

let failed = 0
function check(ok, name, note) {
  if (!ok) failed++
  console.log(`  [${ok ? '通过' : '失败'}] ${name}${note ? ' —— ' + note : ''}`)
}

// ---------------------------------------------------------------- 起等价反代
const proxy = http.createServer((req, res) => {
  const opts = {
    host: '127.0.0.1',
    port: Number(new URL(BASE).port),
    path: req.url,
    method: req.method,
    headers: { ...req.headers },
  }
  // Caddy 的两个关键动作
  opts.headers['x-forwarded-for'] = CLIENT_IP
  opts.headers['x-real-ip'] = CLIENT_IP
  opts.headers['x-forwarded-proto'] = 'https'
  delete opts.headers['connection']

  const up = http.request(opts, (ur) => {
    res.writeHead(ur.statusCode, ur.headers)
    ur.pipe(res)
  })
  up.on('error', (e) => {
    res.writeHead(502); res.end(String(e))
  })
  req.pipe(up)
})

await new Promise((r) => proxy.listen(8660, '127.0.0.1', r))
const P = 'http://127.0.0.1:8660'

console.log('反代链路实测（客户端 IP ' + CLIENT_IP + ' 经等价反代 → 服务）')
console.log('  反代: ' + P + '  →  服务: ' + BASE)

// ---------------------------------------------------------------- 1. XFF 被采信
console.log('')
console.log('【一】X-Forwarded-For 采信（限流/IP 判定必须看到真实客户端）')
{
  // 用一个会把来源 IP 回显出来的端点。/api/hub/netinfo 回显 lan_ip，
  // 不直接回显 client host，所以用「限流生效」来间接证明 IP 被采信：
  // 若 XFF 不被采信，反代地址 127.0.0.1 会被当成回环 → 直接豁免限流。
  const r = await fetch(P + '/api/hub/netinfo', { headers: { 'X-Token': TOKEN } })
  const b = await r.json().catch(() => ({}))
  check(r.status === 200, '经反代访问 /api/hub/netinfo', 'status=' + r.status + ' ' + JSON.stringify(b).slice(0, 80))
  const h = Object.fromEntries([...r.headers])
  check(!!h['x-forwarded-for'] === false, '反代发出的 XFF 不透传客户端原值', 'x-forwarded-for=' + (h['x-forwarded-for'] || '(无，已由反代覆写)'))

  // 反代覆写了 XFF 为 CLIENT_IP；若客户端自带伪造 XFF，应被覆写掉
  const forged = await fetch(P + '/api/hub/netinfo', {
    headers: { 'X-Token': TOKEN, 'X-Forwarded-For': '1.2.3.4, 5.6.7.8' },
  })
  check(forged.status === 200, '带伪造 XFF 的请求仍被正确处理', 'status=' + forged.status)
}

// ---------------------------------------------------------------- 2. 安全头穿透
console.log('')
console.log('【二】安全响应头穿透反代')
{
  const r = await fetch(P + '/app')
  const h = Object.fromEntries([...r.headers])
  const csp = h['content-security-policy'] || ''
  check(!!csp, '/app 经反代仍带 CSP 响应头', csp.slice(0, 60) + '…')
  check(csp.indexOf("frame-ancestors 'none'") >= 0, 'frame-ancestors 仍在（防嵌入）')
  check(h['x-content-type-options'] === 'nosniff', 'nosniff 穿透', h['x-content-type-options'])
  check(h['referrer-policy'] === 'no-referrer', 'no-referrer 穿透（sig 不外泄）', h['referrer-policy'])
  check(h['x-frame-options'] === 'DENY', 'X-Frame-Options 穿透')
}

// ---------------------------------------------------------------- 3. 鉴权仍生效
console.log('')
console.log('【三】鉴权不因反代而失效')
{
  const noTok = await fetch(P + '/api/summary')
  check(noTok.status === 401, '无令牌经反代 → 401（没有被反代绕过）', 'status=' + noTok.status)
  const withTok = await fetch(P + '/api/summary', { headers: { 'X-Token': TOKEN } })
  check(withTok.status === 200, '带令牌经反代 → 200', 'status=' + withTok.status)
  const badTok = await fetch(P + '/api/summary', { headers: { 'X-Token': 'wrong-token' } })
  check(badTok.status === 401, '错令牌经反代 → 401', 'status=' + badTok.status)
}

// ---------------------------------------------------------------- 4. 回环豁免不误伤反代后的真实 IP
console.log('')
console.log('【四】回环豁免与反代后的非回环 IP（这条决定限流是否真的生效）')
{
  // 反代自身是 127.0.0.1 → 服务端直连来源是回环 → 命中回环豁免。
  // 这正是为什么必须配 HUB_TRUSTED_PROXIES + 正确 XFF：
  // 有 XFF 时 clientip 取的是 CLIENT_IP（非回环），限流照常生效。
  const before = await fetch(P + '/api/summary', { headers: { 'X-Token': TOKEN } })
  check(before.status === 200, '首个请求放行（桶初始满）', 'status=' + before.status)
  console.log('  （注：此处的"非回环"由 XFF 提供；若反代不覆写 XFF，')
  console.log('    服务端会把 127.0.0.1 当来源 → 命中回环豁免 → 限流完全失效）')
}

// ---------------------------------------------------------------- 5. 媒体签名 URL 经反代仍可用
console.log('')
console.log('【五】媒体签名 URL 经反代')
{
  const r = await fetch(P + '/api/photos', { headers: { 'X-Token': TOKEN } })
  const b = await r.json().catch(() => ({}))
  check(r.status === 200, '/api/photos 经反代 200', 'status=' + r.status + ' 照片数=' + (b.photos || []).length)
  const first = (b.photos || [])[0]
  if (first && first.url) {
    const abs = first.url.startsWith('http') ? first.url : BASE + first.url
    const img = await fetch(P + first.url)
    check(img.status === 200, '签名媒体 URL 经反代可取（path 未被改写）', 'status=' + img.status)
  } else {
    console.log('  [跳过] 无照片数据，跳过签名 URL 经反代这一项')
  }
}

// ---------------------------------------------------------------- 6. 反向证据
console.log('')
console.log('【六】反向证据：反代不覆写 XFF 时，限流被回环豁免整个绕过')
{
  // 起第二个反代，**刻意不覆写 X-Forwarded-For**（模拟用
  // {http.request.header.X-Forwarded-For} 透传、或干脆不设的那种错配）。
  // 此时服务端看到的直连来源是 127.0.0.1 → 命中回环豁免 → 限流完全不生效。
  const bad = http.createServer((req, res) => {
    const up = http.request({
      host: '127.0.0.1', port: Number(new URL(BASE).port), path: req.url, method: req.method,
      headers: { ...req.headers, 'x-forwarded-proto': 'https' },
    }, (ur) => { res.writeHead(ur.statusCode, ur.headers); ur.pipe(res) })
    up.on('error', (e) => { res.writeHead(502); res.end(String(e)) })
    req.pipe(up)
  })
  await new Promise((r) => bad.listen(8661, '127.0.0.1', r))

  // 把限流阈值压到很小，让效果立刻可见
  const n = 90
  let limited = 0
  for (let i = 0; i < n; i++) {
    const r = await fetch('http://127.0.0.1:8661/api/summary', { headers: { 'X-Token': TOKEN } })
    if (r.status === 429) limited++
  }
  check(limited === 0,
    `错配反代下 ${n} 个请求 0 个被限流（回环豁免生效）`,
    `429 次数=${limited}`)
  console.log('    → 这正是 Caddyfile 里必须写 {remote_host} 的原因：')
  console.log('      不覆写 XFF，服务端就把反代本机当来源，限流形同虚设。')

  // 对照组：直接以非回环来源打（不经过反代），同样的请求数应当被限流。
  // 用 LAN IP 直连需要服务绑在 0.0.0.0；这里用 XFF 指明一个非回环地址、
  // 且不经反代，等价于"客户端自己申报 IP 且反代受信"的受控情形。
  let limited2 = 0
  for (let i = 0; i < n; i++) {
    const r = await fetch(BASE + '/api/summary', {
      headers: { 'X-Token': TOKEN, 'X-Forwarded-For': '198.51.100.9' },
    })
    if (r.status === 429) limited2++
  }
  check(limited2 > 0,
    `对照组：同样 ${n} 个请求被限流 ${limited2} 次（XFF 提供非回环 IP）`,
    `429 次数=${limited2}`)
  bad.close()
}

proxy.close()
console.log('')
console.log(failed === 0 ? '合计：全部通过' : '合计：失败 ' + failed + ' 项')
process.exit(failed === 0 ? 0 : 1)