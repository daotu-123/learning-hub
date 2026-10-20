/* M2c 限流实测：连续 10 次错误口令，打印时间戳与状态码序列。
   用法：node ratelimit-live-check.mjs <base> <user>
   服务需绑 0.0.0.0（回环不受限），本脚本用局域网地址访问。 */
const BASE = process.argv[2] || 'http://127.0.0.1:8641'
const USER = process.argv[3] || 'unit-test-owner'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
function ts() {
  const d = new Date()
  return d.toTimeString().slice(0, 8) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

const seq = []
for (let i = 1; i <= 10; i++) {
  const t0 = Date.now()
  const r = await fetch(BASE + '/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Forwarded-For': '198.51.100.77' },
    body: JSON.stringify({ username: USER, password: 'wrong-password-live-check' }),
  })
  let ra = r.headers.get('retry-after')
  let code = r.status
  let body = null
  try { body = await r.json() } catch (e) { /* noop */ }
  seq.push({ i, ts: ts(), ms: Date.now() - t0, code, ra })
  console.log(
    String(i).padStart(2) + '. ' + ts() +
    '  → ' + code +
    (ra ? '  Retry-After=' + ra + 's' : '') +
    '  (' + (Date.now() - t0) + 'ms)' +
    (body && body.error ? '  ' + JSON.stringify(body.error) : '')
  )
  await sleep(300)
}

console.log('')
console.log('状态码序列：' + seq.map((s) => s.code).join(' → '))
const first429 = seq.find((s) => s.code === 429)
console.log('首次 429：第 ' + (first429 ? first429.i : '无') + ' 次')
if (first429) {
  console.log('第 5→6 次的错误口令仍返回 401，第 6 次才 429 —— 符合"连续 5 次失败后从第 6 次起退避"')
  // 按**最后一次**的 Retry-After 等待（指数退避会一路翻倍，不能用第 6 次的 1s）
  const lastRa = Math.max(...seq.filter((s) => s.code === 429).map((s) => Number(s.ra) || 1))
  const wait = lastRa * 1000 + 500
  console.log('')
  console.log('等待 ' + lastRa + 's（最后一次 Retry-After）+ 0.5s 后重试，验证退避会解禁…')
  await sleep(wait)
  const r = await fetch(BASE + '/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Forwarded-For': '198.51.100.77' },
    body: JSON.stringify({ username: USER, password: 'wrong-password-live-check' }),
  })
  const ok = r.status === 401
  console.log(ts() + '  → ' + r.status + (ok ? '（退避已解禁，符合预期）' : '（仍是 429，退避未解禁 —— BUG）'))
  if (!ok) process.exit(1)
}
