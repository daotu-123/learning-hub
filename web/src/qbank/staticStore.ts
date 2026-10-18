/* static-store.ts — 题库纯前端静态 Store（合并单 App 后固定走此模式）
 *
 * 从 mech-qbank/web/src/store/static-store.js 逐行移植为 TS，
 * 判分与间隔逻辑与 app/core.py 的 Store 同源：
 *   · 判断题：对/正确/√/T/1 → '对'，错/×/F/0 → '错'；带 A.对/B.错 选项时按选项文本映射
 *   · 选择题：答案为纯字母串时集合严格相等（多选必须全选对）；历史数据兜底取开头字母串
 *   · 其余（问答/计算/长答案）自评：correct=null
 *   · 间隔：答对按 DATA.intervals（默认 1/3/7/15/30/60 天，streak 封顶），答错次日必回，跳过 3 天后回
 */

export interface QBankQuestion {
  id: string
  stem: string
  qtype: string
  level: number | null
  options: string[]
  answer: string
  explanation: string
  bank: string
  section_path: string
  cat_name: string
  source_class: string
}
export interface QBankCard {
  chapter: string
  topic: string
  name: string
  body: string
  qids: string[]
  source_class: string
}
export interface QBankData {
  schema?: number
  intervals?: number[]
  questions?: QBankQuestion[]
  cards?: QBankCard[]
}
export interface ProgRow {
  state: string
  streak: number
  wrong: number
  due: string | null
  last_seen: string | null
}

const INTERVALS = [1, 3, 7, 15, 30, 60]
const WRONG_BACK = 1
const SKIP_BACK = 3
const PROG_KEY = 'mech-qbank-progress'
const CUSTOM_KEY = 'mech-qbank-custom'
const CKEY = 'mech-qbank-checkin'
const NKEY = 'mech-qbank-notes'
const TRUE_SET: Record<string, number> = { '对': 1, '正确': 1, '是': 1, '√': 1, '✓': 1, 'true': 1, 't': 1, 'yes': 1, 'y': 1, '1': 1 }
const FALSE_SET: Record<string, number> = { '错': 1, '错误': 1, '否': 1, '×': 1, '✗': 1, 'x': 1, 'false': 1, 'f': 1, 'no': 1, '0': 1, '2': 1 }

function pad(n: number) { return String(n).padStart(2, '0') }
function isoLocal(d: Date) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}
function nowIso() { return isoLocal(new Date()) }
function isoPlusDays(days: number) { return isoLocal(new Date(Date.now() + days * 86400000)) }
function todayStr() { const d = new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) }
function clampInt(v: any, def: number, lo: number, hi: number) {
  const n = parseInt(v, 10)
  if (isNaN(n)) return def
  return Math.max(lo, Math.min(hi, n))
}
function uniq(arr: string[]) {
  const s: Record<string, number> = {}; const out: string[] = []
  ;(arr || []).forEach((x) => { if (!s[x]) { s[x] = 1; out.push(x) } })
  return out
}
function sameSet(a: string[], b: string[]) {
  if (a.length !== b.length) return false
  const s: Record<string, number> = {}; a.forEach((x) => { s[x] = 1 })
  return b.every((x) => s[x])
}
function normJudge(s: any): string | null {
  s = String(s == null ? '' : s).trim().toLowerCase().replace(/[。.]+$/, '')
  if (TRUE_SET[s]) return '对'
  if (FALSE_SET[s]) return '错'
  return null
}
function sec0(sp: any) { return String(sp || '').split(' › ')[0].trim() }
function monthStr(d: Date) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) }
function dayKey(d: Date) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) }
function addDays(d: Date, n: number) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n) }
function validDay(d: any) {
  if (typeof d !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(d)) return false
  const p = d.split('-'), dt = new Date(+p[0], +p[1] - 1, +p[2])
  return dt.getFullYear() === +p[0] && dt.getMonth() === +p[1] - 1 && dt.getDate() === +p[2]
}

export interface QBankStore {
  grade(qid: string, given: any): any
  mark(qid: string, result: string): any
  pick(o: any): any[]
  search(qw: string, limit: any): any[]
  banks(): any[]
  sections(): any[]
  cards(kw: string, chapter: string, limit: any): any[]
  chapters(): any[]
  wrong_list(limit: any): any[]
  stats(): any
  export_progress(): any
  import_progress(p: any): number
  merge_questions(list: any[], mode: string): any
  custom_list(): any[]
  clear_custom(): number
  export_template(): any
  checkin(month?: string): any
  manual_checkin(): any
  export_checkin(): any
  import_checkin(data: any): number
  notes_list(): any[]
  set_note(id: string, text: string, flag?: boolean): any
  note_delete?(id: string): any
  note_list?(): any[]
  question(qid: string): any
}

export function make(DATA: QBankData, storage: Storage | null): QBankStore {
  DATA = DATA || {}
  const IV = (Array.isArray(DATA.intervals) && DATA.intervals.length)
    ? DATA.intervals.slice() : INTERVALS
  const builtin: QBankQuestion[] = DATA.questions || []
  const cardsList: QBankCard[] = DATA.cards || []
  const builtinById: Record<string, QBankQuestion> = {}
  builtin.forEach((q) => { builtinById[q.id] = q })

  // ---- 自定义题库（导入的用户题；与内置合并后参与全部查询）----
  function loadCustom(): QBankQuestion[] {
    try {
      const raw = storage && storage.getItem(CUSTOM_KEY)
      const arr = raw ? JSON.parse(raw) : []
      return Array.isArray(arr) ? arr : []
    } catch (e) { return [] }
  }
  function saveCustom() {
    try { storage && storage.setItem(CUSTOM_KEY, JSON.stringify(custom)) } catch (e) { /* 存满不打断 */ }
  }
  let custom: QBankQuestion[] = loadCustom()
  let questions: QBankQuestion[] = builtin.concat(custom)
  let byId: Record<string, QBankQuestion> = {}
  function reindex() {
    byId = {}
    questions.forEach((q) => { byId[q.id] = q })
  }
  reindex()

  function normCustomQ(raw: any): { err?: string; ok?: boolean; q?: QBankQuestion } {
    if (!raw || typeof raw !== 'object') return { err: '不是合法题目对象' }
    const id = String(raw.id == null ? '' : raw.id).trim()
    const stem = String(raw.stem == null ? '' : raw.stem).trim()
    if (!id) return { err: '缺少 id（题号）' }
    if (!stem) return { err: '缺少题干（stem）：' + id }
    if (builtinById[id]) return { err: 'id 与内置题重复，换一个 id：' + id }
    return {
      ok: true, q: {
        id: id, stem: stem,
        qtype: String(raw.qtype == null ? '' : raw.qtype).trim() || '问答',
        level: (raw.level == null || raw.level === '') ? null : clampInt(raw.level, 0, 1, 5),
        options: Array.isArray(raw.options) ? raw.options.map((x: any) => String(x)) : [],
        answer: String(raw.answer == null ? '' : raw.answer),
        explanation: String(raw.explanation == null ? '' : raw.explanation),
        bank: String(raw.bank == null ? '' : raw.bank).trim() || '我的题库',
        section_path: String(raw.section_path == null ? '' : raw.section_path).trim(),
        cat_name: String(raw.cat_name == null ? '' : raw.cat_name).trim(),
        source_class: '自定义',
      },
    }
  }

  // 合并导入：mode 'skip'（默认，撞已导入题号跳过）/ 'cover'（覆盖）
  function mergeQuestions(list: any[], mode: string) {
    mode = mode === 'cover' ? 'cover' : 'skip'
    const res = { added: 0, updated: 0, skipped: 0, rejected: [] as { id: string; err: string }[] }
    let changed = false
    ;(Array.isArray(list) ? list : []).forEach((raw) => {
      const rid = raw && typeof raw === 'object' ? String(raw.id == null ? '' : raw.id).trim() : ''
      const r = normCustomQ(raw)
      if (r.err) { res.rejected.push({ id: rid || '（无 id）', err: r.err }); return }
      let hit = -1
      for (let i = 0; i < custom.length; i++) if (custom[i].id === r.q!.id) { hit = i; break }
      if (hit >= 0) {
        if (mode === 'cover') { custom[hit] = r.q!; res.updated++; changed = true }
        else res.skipped++
      } else {
        custom.push(r.q!); res.added++; changed = true
      }
    })
    if (changed) {
      questions = builtin.concat(custom)
      reindex()
      saveCustom()
    }
    return res
  }

  function customList() {
    return custom.map((q) => ({ id: q.id, qtype: q.qtype, level: q.level, stem: q.stem, bank: q.bank }))
  }

  function clearCustom() {
    const n = custom.length
    custom = []
    questions = builtin.concat(custom)
    reindex()
    saveCustom()
    return n
  }

  function exportTemplate() {
    return {
      _readme: 'mech-qbank 题库导入模板。questions 数组里每行一题：id 必填且不能与内置题重复；qtype 建议取 判断/单选/多选/问答/填空/计算；level 为 1-5 难度（可省）；有 options 时按选择题渲染，answer 写正确选项字母（如 "A" 或 "AB"）；answer 留空表示答案待补（自评练习）。bank 可用来分组，导入后出现在「题库」筛选里。',
      questions: [
        { id: 'MY001', qtype: '单选', level: 2, bank: '我的题库', section_path: '机械制图',
          stem: '表面粗糙度评定参数中，最常用的是（　）。',
          options: ['A. Ra', 'B. Rx', 'C. Ry'], answer: 'A',
          explanation: 'Ra 为轮廓算术平均偏差，是国标最常用的评定参数。' },
        { id: 'MY002', qtype: '判断', level: 1, bank: '我的题库', section_path: '机械制图',
          stem: '游标卡尺的读数由主尺整数部分与游标小数部分相加得到。',
          options: [], answer: '对', explanation: '' },
        { id: 'MY003', qtype: '问答', level: 3, bank: '我的题库', section_path: '液压与气动',
          stem: '简述先导式溢流阀相对于直动式溢流阀的主要优点。',
          options: [], answer: '', explanation: '先导式先导阀先动作、主阀口后开启，压力更稳定，适合高压大流量。' },
      ],
    }
  }

  // ---- 进度（localStorage；隐私模式/存满时退化为内存，本会话仍可刷题）----
  function loadProg(): Record<string, ProgRow> {
    try {
      const raw = storage && storage.getItem(PROG_KEY)
      return raw ? (JSON.parse(raw) || {}) : {}
    } catch (e) { return {} }
  }
  const prog: Record<string, ProgRow> = loadProg()
  function saveProg() {
    try { storage && storage.setItem(PROG_KEY, JSON.stringify(prog)) } catch (e) { /* 不打断刷题 */ }
  }

  function pubRow(q: QBankQuestion) {
    return {
      id: q.id, stem: q.stem, qtype: q.qtype, level: q.level,
      options: q.options || [], cat: q.cat_name, bank: q.bank,
      source_class: q.source_class, sec: sec0(q.section_path),
    }
  }

  // ---- 判分（与 core.py Store.grade 同源）----
  function grade(qid: string, given: any) {
    const q = byId[qid]
    if (!q) return { error: 'not found' }
    const ansRaw = (q.answer || '').trim()
    if (!ansRaw || ansRaw.indexOf('待补') >= 0) {
      return { answer: ansRaw || '（答案待补）', explanation: q.explanation, correct: null, self: true }
    }
    const ans = ansRaw.replace(/\*\*/g, '').trim()
    const qt = q.qtype || ''
    const opts = q.options || []
    // 1) 判断题
    const j = normJudge(ans)
    if (j && (!opts.length || qt.indexOf('判断') >= 0)) {
      let gj = normJudge(given)
      if (gj === null && opts.length) {
        const m = /^\s*([A-H])/.exec(String(given || '').toUpperCase())
        if (m) {
          const idx = m[1].charCodeAt(0) - 65
          if (idx >= 0 && idx < opts.length) {
            const t = String(opts[idx])
            if (/对|正确|√|✓/.test(t)) gj = '对'
            else if (/错|错误|×|✗/.test(t)) gj = '错'
          }
        }
      }
      return { answer: j, explanation: q.explanation, correct: gj === j }
    }
    // 2) 选择题
    let letters: string[] | null = null
    if (/^[A-H][A-H、,，\s\/]{0,15}$/.test(ans)) letters = uniq(ans.toUpperCase().match(/[A-H]/g) || [])
    if (!letters && /单选|多选|选择|选型/.test(qt)) {
      const m2 = /^([A-H](?:\s*[、,，/]?\s*[A-H])*)\s*[（(：:．.]/.exec(ans)
      if (m2) letters = uniq(m2[1].toUpperCase().match(/[A-H]/g) || [])
    }
    if (letters && (/单选|多选|选择|选型/.test(qt) || opts.length)) {
      const g = uniq(String(given || '').toUpperCase().match(/[A-H]/g) || [])
      return { answer: ans, explanation: q.explanation, correct: g.length > 0 && sameSet(g, letters) }
    }
    // 3) 其余自评
    return { answer: ans, explanation: q.explanation, correct: null, self: true }
  }

  // ---- 进度（与 core.py Store.mark 同源）----
  function mark(qid: string, result: string) {
    const st = prog[qid] || { state: 'new', streak: 0, wrong: 0, due: null, last_seen: null }
    let streak = st.streak || 0, wrong = st.wrong || 0, state = st.state || 'new'
    let days: number
    if (result === 'correct') {
      streak += 1; state = 'correct'
      days = IV[Math.min(streak, IV.length) - 1]
    } else if (result === 'wrong') {
      streak = 0; wrong += 1; state = 'wrong'; days = WRONG_BACK
    } else {
      days = SKIP_BACK
    }
    const due = isoPlusDays(days)
    prog[qid] = { state: state, streak: streak, wrong: wrong, due: due, last_seen: nowIso() }
    saveProg()
    return { ok: true, state: state, streak: streak, wrong: wrong, due: due }
  }

  // ---- 组卷（与 core.py Store.pick 同语义）----
  function pick(o: any) {
    o = o || {}
    const n = clampInt(o.n, 10, 1, 100)
    const level = o.level, qtype = o.qtype, bank = o.bank, section = o.section
    const onlyNew = !!o.only_new, review = !!o.review
    let lv = 0
    if (level != null && level !== '') lv = clampInt(level, 0, 1, 5)
    const seg = String(section == null ? '' : section).trim()
    const now = nowIso()
    const list = questions.filter((q) => {
      if (lv && (q.level || 0) !== lv) return false
      if (qtype && String(q.qtype || '').indexOf(qtype) < 0) return false
      if (bank && (q.bank || '') !== bank) return false
      if (seg && sec0(q.section_path) !== seg) return false
      const p = prog[q.id]
      if (review) {
        if (!p || !p.due || p.due > now) return false
      } else if (onlyNew) {
        if (p && (p.state === 'correct' || p.state === 'wrong')) return false
      }
      return true
    })
    if (review) {
      list.sort((a, b) => {
        const da = prog[a.id].due || '', db = prog[b.id].due || ''
        return da < db ? -1 : da > db ? 1 : (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
      })
      return list.slice(0, n).map(pubRow)
    }
    // Fisher-Yates 洗牌，模拟服务端 ORDER BY RANDOM()
    for (let i = list.length - 1; i > 0; i--) {
      const j2 = Math.floor(Math.random() * (i + 1))
      const t = list[i]; list[i] = list[j2]; list[j2] = t
    }
    return list.slice(0, n).map(pubRow)
  }

  function search(kw: string, limit: any) {
    limit = clampInt(limit, 50, 1, 100)
    kw = String(kw == null ? '' : kw).trim()
    if (!kw) return []
    const k = kw.toLowerCase()
    return questions.filter((q) => String(q.stem || '').toLowerCase().indexOf(k) >= 0)
      .sort(byIdAsc).slice(0, limit).map(pubRow)
  }

  function banks() {
    const m: Record<string, number> = {}
    questions.forEach((q) => { const b = q.bank || ''; m[b] = (m[b] || 0) + 1 })
    return Object.keys(m).map((b) => ({ bank: b, n: m[b] }))
      .sort((a, b) => b.n - a.n || (a.bank < b.bank ? -1 : a.bank > b.bank ? 1 : 0))
  }

  function sections() {
    const m: Record<string, number> = {}
    questions.forEach((q) => {
      const s = sec0(q.section_path)
      if (s) m[s] = (m[s] || 0) + 1
    })
    return Object.keys(m).map((s) => ({ section: s, n: m[s] }))
      .sort((a, b) => b.n - a.n)
  }

  function cards(kw: string, chapter: string, limit: any) {
    limit = clampInt(limit, 500, 1, 1000)
    kw = String(kw == null ? '' : kw).trim().toLowerCase()
    chapter = chapter || ''
    return cardsList.filter((c) => {
      if (chapter && (c.chapter || '') !== chapter) return false
      if (kw) {
        const blob = [c.name, c.body, c.topic].map((x) => String(x || '').toLowerCase()).join(' ')
        if (blob.indexOf(kw) < 0) return false
      }
      return true
    }).slice(0, limit).map((c) => ({
      chapter: c.chapter, topic: c.topic, name: c.name, body: c.body,
      qids: c.qids || [], source_class: c.source_class,
    }))
  }

  function chapters() {
    const m: Record<string, number> = {}
    cardsList.forEach((c) => { const ch = c.chapter || ''; m[ch] = (m[ch] || 0) + 1 })
    return Object.keys(m).sort().map((ch) => ({ chapter: ch, n: m[ch] }))
  }

  function wrongList(limit: any) {
    limit = clampInt(limit, 200, 1, 500)
    return Object.keys(prog).filter((id) => (prog[id].wrong || 0) > 0 && byId[id])
      .map((id) => {
        const d = pubRow(byId[id]) as any
        d.wrong = prog[id].wrong; d.streak = prog[id].streak; d.state = prog[id].state
        return d
      })
      .sort((a, b) => b.wrong - a.wrong || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
      .slice(0, limit)
  }

  function stats() {
    const byLevel: Record<string, number> = {}, byClass: Record<string, number> = {}, byType: Record<string, number> = {}
    questions.forEach((q) => {
      const lv = q.level == null ? '?' : String(q.level)
      byLevel[lv] = (byLevel[lv] || 0) + 1
      const sc = q.source_class || '未标注'
      byClass[sc] = (byClass[sc] || 0) + 1
      const t = (q.qtype || '未标注').split('/')[0].split('·')[0]
      byType[t] = (byType[t] || 0) + 1
    })
    let answered = 0, ok = 0, wrong = 0, due = 0, today = 0, todayOk = 0
    const now = nowIso(), td = todayStr()
    Object.keys(prog).forEach((id) => {
      const p = prog[id]
      if (p.state === 'correct' || p.state === 'wrong') answered++
      if (p.state === 'correct') ok++
      if ((p.wrong || 0) > 0) wrong++
      if (p.due && p.due <= now) due++
      if (p.last_seen && p.last_seen >= td) { today++; if (p.state === 'correct') todayOk++ }
    })
    return {
      mode: 'static', total: questions.length, cards: cardsList.length,
      answered: answered, correct: ok, wrong: wrong, due: due, today: today, today_ok: todayOk,
      by_level: byLevel, by_class: byClass, by_type: byType, intervals: IV.slice(),
    }
  }

  function exportProgress() {
    const out: Record<string, any> = {}
    Object.keys(prog).forEach((id) => {
      const p = prog[id]
      out[id] = { state: p.state, streak: p.streak, wrong: p.wrong, due: p.due, last_seen: p.last_seen }
    })
    return out
  }

  function importProgress(data: any) {
    let n = 0
    Object.keys(data || {}).forEach((pid) => {
      const v = data[pid]
      if (!pid || !v || typeof v !== 'object') return
      prog[pid] = {
        state: String(v.state == null ? 'new' : v.state),
        streak: clampInt(v.streak, 0, 0, 9999),
        wrong: clampInt(v.wrong, 0, 0, 99999),
        due: String(v.due || '') || null,
        last_seen: String(v.last_seen || '') || null,
      }
      n++
    })
    if (n) saveProg()
    return n
  }

  // ---- 学习打卡：答题自动打卡（progress.last_seen 聚合）+ 手动补签 ----
  function loadManual(): string[] {
    try {
      const raw = storage && storage.getItem(CKEY)
      const arr = raw ? JSON.parse(raw) : []
      return Array.isArray(arr) ? arr.filter(validDay) : []
    } catch (e) { return [] }
  }
  function saveManual(days: string[]) {
    try { storage && storage.setItem(CKEY, JSON.stringify(days)) } catch (e) { /* 存满不打断 */ }
  }
  let manualDays: string[] = loadManual()

  // 按日聚合答题量（自动打卡的计数来源）
  function perDay(): Record<string, { n: number; ok: number }> {
    const m: Record<string, { n: number; ok: number }> = {}
    Object.keys(prog).forEach((id) => {
      const p = prog[id]
      const d = (p.last_seen || '').slice(0, 10)
      if (!validDay(d)) return
      const e = m[d] || (m[d] = { n: 0, ok: 0 })
      e.n++
      if (p.state === 'correct') e.ok++
    })
    return m
  }

  function checkin(ym?: string) {
    ym = ym || monthStr(new Date())
    if (!/^\d{4}-\d{2}$/.test(ym)) ym = monthStr(new Date())
    const per = perDay()
    const mset: Record<string, number> = {}
    manualDays.forEach((d) => { mset[d] = 1 })
    const all: Record<string, number> = {}
    Object.keys(per).forEach((d) => { all[d] = 1 })
    Object.keys(mset).forEach((d) => { all[d] = 1 })
    const today = todayStr()
    const todayInfo = per[today] || { n: 0, ok: 0 }
    const checkedToday = todayInfo.n > 0 || !!mset[today]
    // 连续天数：今天打了从今天往前数；今天没打则算截至昨天的
    let d = new Date()
    if (!all[today]) d = addDays(d, -1)
    let streak = 0
    while (all[dayKey(d)]) { streak++; d = addDays(d, -1) }
    // 当月日历格子
    const parts = ym.split('-'), y = +parts[0], mo = +parts[1]
    const ndays = new Date(y, mo, 0).getDate()
    const lead = (new Date(y, mo - 1, 1).getDay() + 6) % 7
    const cells: { day: number; n: number; ok: number; manual: boolean; today: boolean }[] = []
    for (let i = 1; i <= ndays; i++) {
      const key = ym + '-' + pad(i)
      const e = per[key] || { n: 0, ok: 0 }
      cells.push({ day: i, n: e.n, ok: e.ok, manual: !!mset[key], today: key === today })
    }
    return {
      today: today, checked_today: checkedToday, today_n: todayInfo.n, today_ok: todayInfo.ok,
      streak: streak, total_days: Object.keys(all).length, manual_count: manualDays.length,
      month: ym, lead: lead, days: cells,
    }
  }

  function manualCheckin() {
    const t = todayStr()
    const ti = perDay()[t]
    if (manualDays.indexOf(t) < 0 && !(ti && ti.n > 0)) {
      manualDays.push(t)
      manualDays.sort()
      saveManual(manualDays)
    }
    return checkin()
  }

  function exportCheckin() { return { manual: manualDays.slice() } }

  function importCheckin(data: any) {
    let n = 0
    const list = data && Array.isArray(data.manual) ? data.manual : (Array.isArray(data) ? data : [])
    list.forEach((d: any) => {
      if (validDay(d) && manualDays.indexOf(d) < 0) {
        manualDays.push(d); n++
      }
    })
    if (n) { manualDays.sort(); saveManual(manualDays) }
    return n
  }

  // ---- 题目备注 ----
  const NOTE_MAX = 2000
  function loadNotes(): Record<string, { note: string; updated_at: string }> {
    try {
      const raw = storage && storage.getItem(NKEY)
      const obj = raw ? JSON.parse(raw) : {}
      const out: Record<string, { note: string; updated_at: string }> = {}
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
        Object.keys(obj).forEach((qid) => {
          const v = obj[qid]
          if (v && typeof v.note === 'string' && v.note.trim()) {
            out[qid] = { note: v.note, updated_at: String(v.updated_at || '') }
          }
        })
      }
      return out
    } catch (e) { return {} }
  }
  function saveNotes(obj: any) {
    try { storage && storage.setItem(NKEY, JSON.stringify(obj)) } catch (e) { /* 存满不打断 */ }
  }
  const noteMap = loadNotes()

  function notesList() {
    const out: any[] = []
    Object.keys(noteMap).forEach((qid) => {
      const v = noteMap[qid], q = byId[qid]
      out.push(q
        ? { id: qid, note: v.note, updated_at: v.updated_at, stem: q.stem, qtype: q.qtype,
            level: q.level, bank: q.bank, missing: false }
        : { id: qid, note: v.note, updated_at: v.updated_at, stem: '', qtype: '',
            level: null, bank: '', missing: true })
    })
    out.sort((a, b) => {
      const ua = a.updated_at || '', ub = b.updated_at || ''
      if (ua !== ub) return ua < ub ? 1 : -1
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
    })
    return out
  }

  function setNote(qid: string, note: string) {
    qid = String(qid == null ? '' : qid).trim()
    if (!qid) return { error: '缺少题号 id' }
    if (!byId[qid]) return { error: 'not found' }
    note = String(note == null ? '' : note).replace(/\r\n/g, '\n').trim().slice(0, NOTE_MAX)
    if (!note) {
      delete noteMap[qid]
      saveNotes(noteMap)
      return { ok: true, id: qid, note: '', updated_at: '', removed: true }
    }
    const now = nowIso()
    noteMap[qid] = { note: note, updated_at: now }
    saveNotes(noteMap)
    return { ok: true, id: qid, note: note, updated_at: now, removed: false }
  }

  function question(qid: string) {
    const q = byId[String(qid || '')]
    return q ? pubRow(q) : null
  }

  function byIdAsc(a: any, b: any) { return a.id < b.id ? -1 : a.id > b.id ? 1 : 0 }

  return {
    grade: grade, mark: mark, pick: pick, search: search, banks: banks, sections: sections,
    cards: cards, chapters: chapters, wrong_list: wrongList, stats: stats,
    export_progress: exportProgress, import_progress: importProgress,
    merge_questions: mergeQuestions, custom_list: customList, clear_custom: clearCustom,
    export_template: exportTemplate,
    checkin: checkin, manual_checkin: manualCheckin,
    export_checkin: exportCheckin, import_checkin: importCheckin,
    notes_list: notesList, set_note: setNote, question: question,
  }
}

export { INTERVALS, WRONG_BACK, SKIP_BACK, PROG_KEY, NKEY as NOTES_KEY, CKEY as CHECKIN_KEY }
