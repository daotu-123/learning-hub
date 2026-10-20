/* M2c-P2 XFF 矩阵实测。
   用法：
     node xff-matrix-check.mjs <base> <user> untrusted
     node xff-matrix-check.mjs <base> <user> trusted
   trusted 模式要求服务端以 HUB_TRUSTED_PROXIES=10.14.158.0/24 启动。
   直连来源与 XFF 用的是同一个本机地址，所以"受信"就是同一台机器扮演反代。 */
const BASE = process.argv[2] || 'http://127.0.0.1:8641'
const USER = process.argv[3] || 'm2c-check'
const MODE = process.argv[4] || 'untrusted'
const SELF = process.argv[5] || '10.14.158.193'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let failed = 0
function check(ok, name, note) {
  if (!ok) failed++
  console.log(`  [${ok ? '通过' : '失败'}] ${name}${note ? ' —— ' + note : ''}`)
}

async function login(xff) {
  const headers = { 'Content-Type': 'application/json' }
  if (xff) headers['X-Forwarded-For'] = xff
  const r = await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers,
    body: JSON.stringify({ username: USER, password: 'wrong-' + Math.random() }),
  })
  let b = null
  try { b = await r.json() } catch (e) { /* noop */ }
  return { status: r.status, code: b && b.error ? b.error.code : null }
}

console.log('XFF 矩阵实测 —— 模式：' + MODE + '，直连来源即本机 ' + SELF)
console.log('')

if (MODE === 'untrusted') {
  console.log('【场景 A】HUB_TRUSTED_PROXIES 为空 → 不采信 XFF')
  console.log('  连发 6 次错误口令，每次伪造一个不同的 XFF：')
  const codes = []
  for (let i = 1; i <= 6; i++) {
    const r = await login('203.0.113.' + i)
    codes.push(r.status)
    console.log('    第 ' + i + ' 次  XFF=203.0.113.' + i + '  → ' + r.status + '  (' + r.code + ')')
    await sleep(200)
  }
  check(codes.slice(0, 5).every((c) => c === 401), '前 5 次仍是 401', codes.join(' → '))
  check(codes[5] === 429, '第 6 次 429 —— 伪造 XFF 没能绕开限流', codes.join(' → '))
  console.log('')
  console.log('  结论：XFF 完全被忽略，全部计数落在真实来源 ' + SELF + ' 上。')
} else {
  console.log('【场景 B】本机被列入受信代理 → 采信 XFF 的最右侧非受信项')
  const target = '198.51.100.50'
  console.log('  用同一个伪造客户端 ' + target + ' 连发 6 次：')
  const codes = []
  for (let i = 1; i <= 6; i++) {
    const r = await login(target)
    codes.push(r.status)
    console.log('    第 ' + i + ' 次  XFF=' + target + '  → ' + r.status + '  (' + r.code + ')')
    await sleep(200)
  }
  check(codes.slice(0, 5).every((c) => c === 401), '前 5 次 401', codes.join(' → '))
  check(codes[5] === 429, '第 6 次 429 —— 按 XFF 里的真实客户端计数生效', codes.join(' → '))

  console.log('')
  console.log('  换一个 XFF（= 另一个真实客户端），应重新从 401 开始：')
  await sleep(200)
  const other = await login('198.51.100.51')
  console.log('    XFF=198.51.100.51  → ' + other.status + '  (' + other.code + ')')
  check(other.status === 401, '不同真实客户端独立计数', 'status=' + other.status)
  console.log('')
  console.log('  结论：受信后 XFF 生效，且按最右侧非受信项区分不同客户端。')
}

console.log('')
console.log(failed === 0 ? '合计：全部通过' : '合计：失败 ' + failed + ' 项')
process.exit(failed === 0 ? 0 : 1)
