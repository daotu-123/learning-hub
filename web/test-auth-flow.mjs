/* 身份链路验收脚本（M2b）：login → me(200) → logout(200) → me(401)
 *
 * 不依赖浏览器：直接对真实服务发 HTTP 请求，验证前端将要依赖的那条链路。
 * 用法：
 *   node test-auth-flow.mjs                     # 默认 http://127.0.0.1:8637
 *   HUB_BASE=http://192.168.1.8:8637 node test-auth-flow.mjs
 *
 * 需要服务端已建账号（HUB_ACCOUNT / HUB_PASSWORD 提供凭据，默认与 pytest 一致）。
 * 没建账号时脚本不会失败退出，而是把该步骤标成"跳过"并说明原因——
 * 服务无账号时 login 返回 503 是设计行为，不是回归。
 */
const BASE = (process.env.HUB_BASE || 'http://127.0.0.1:8637').replace(/\/+$/, '')
const ACCOUNT = process.env.HUB_ACCOUNT || 'unit-test-owner'
const PASSWORD = process.env.HUB_PASSWORD || 'unit-test-only-not-a-real-secret'

const results = []
function record(ok, name, note) {
  results.push({ ok, name, note: note || '' })
  const mark = ok ? '通过' : '失败'
  console.log(`  [${mark}] ${name}${note ? ' —— ' + note : ''}`)
}
function skip(name, note) {
  results.push({ ok: null, name, note: note || '' })
  console.log(`  [跳过] ${name} —— ${note}`)
}

async function req(method, path, { token, body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = 'Bearer ' + token
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data = null
  try { data = await res.json() } catch (e) { data = null }
  return { status: res.status, data, text: res.status === 0 ? '' : String(data && data.hint || '') }
}

async function main() {
  console.log('身份链路验收：' + BASE)
  console.log('账号：' + ACCOUNT)
  console.log('')

  // 1) 口令错误 → 401，且消息不区分原因
  const bad = await req('POST', '/api/auth/login', { body: { username: ACCOUNT, password: 'wrong-password-unit-test' } })
  if (bad.status === 503) {
    skip('错误口令返回 401', '服务端尚未建账号（login=503），本项不适用')
    skip('登录成功拿到会话令牌', '同上')
    skip('GET /api/auth/me 返回 200', '同上')
    skip('登出返回 200', '同上')
    skip('登出后 me 返回 401', '同上')
  } else {
    record(bad.status === 401, '错误口令返回 401', '实际 ' + bad.status)
    record(bad.data && bad.data.detail === '用户名或口令错误', '失败消息不区分原因', JSON.stringify(bad.data))

    // 2) 正确口令 → 拿令牌
    const login = await req('POST', '/api/auth/login', { body: { username: ACCOUNT, password: PASSWORD } })
    const token = login.data && login.data.token
    record(login.status === 200 && !!token, '登录成功拿到会话令牌', 'status=' + login.status)

    // 3) Bearer 带令牌访问 me
    const me = await req('GET', '/api/auth/me', { token })
    record(me.status === 200, 'GET /api/auth/me 返回 200', 'status=' + me.status)
    record(!!(me.data && me.data.username), 'me 带用户名', JSON.stringify(me.data))

    // 3b) 令牌走 query 必须失败（后端明确拒绝，防令牌进日志）
    const q = await fetch(BASE + '/api/auth/me?token=' + encodeURIComponent(token || ''))
    record(q.status === 401, '会话令牌走 query 被拒（401）', 'status=' + q.status)

    // 4) 登出
    const out = await req('POST', '/api/auth/logout', { token })
    record(out.status === 200, '登出返回 200', 'status=' + out.status)

    // 5) 登出后同一令牌失效
    const me2 = await req('GET', '/api/auth/me', { token })
    record(me2.status === 401, '登出后 me 返回 401', 'status=' + me2.status)
  }

  const failed = results.filter((r) => r.ok === false).length
  const skipped = results.filter((r) => r.ok === null).length
  const passed = results.filter((r) => r.ok === true).length
  console.log('')
  console.log(`合计：通过 ${passed} ｜ 失败 ${failed} ｜ 跳过 ${skipped}`)
  process.exit(failed === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('验收脚本异常：' + e.message)
  process.exit(2)
})
