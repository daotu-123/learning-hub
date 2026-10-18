/* QbQuestionCard.vue — 题卡：选择题/判断题/自评题三态 + 判分反馈 + 快捷键 + 备注区
 *
 * 逻辑从旧版 index.html 的 renderQ/submitQ/bindSelfEval 平移：
 *  given/shown/fb 全部存外部 session store（跨视图共享：复习/错题/备注跳转进来都能续上）。
 */
<template>
  <div class="card">
    <div class="q-head">
      <span class="qtype-badge" :style="{ background: qm.color }"><span v-html="qm.icon"></span>{{ q.qtype || '问答' }}</span>
      <span class="lv-badge" :style="{ borderColor: lv.c, color: lv.c }">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M4 18V9M10 18V4M16 18v-6M22 18h-2"/></svg>
        {{ lvKey ? '难度 ' + lvKey + ' ' + lv.name : lv.name }}
      </span>
      <span class="q-progress">第 <b>{{ (index || 0) + 1 }}</b> / {{ total }} 题<i class="meta" style="margin-left:8px">{{ label }}</i></span>
      <span v-if="my" class="note-flag">有备注</span>
    </div>
    <div class="q-src meta">{{ src }}</div>
    <div class="q">{{ q.stem }}</div>

    <template v-if="isChoice">
      <div v-if="isJudge" class="judge-row">
        <button v-for="(o, k) in effOpts" :key="k" class="opt judge" :class="optCls(o, k)"
               :data-l="letterOf(o, k)" @click="choose(o, k)">
          <span v-html="letterOf(o, k) === '对' ? SVG_CK : SVG_XX"></span>
          <span>{{ letterOf(o, k) }}</span>
        </button>
      </div>
      <template v-else>
        <div v-if="isMulti" class="meta" style="margin:-6px 0 8px">多选题：可点选多个选项，提交后按组合判分</div>
        <button v-for="(o, k) in effOpts" :key="k" class="opt" :class="optCls(o, k)"
               :data-l="letterOf(o, k)" @click="choose(o, k)">
          <span class="k">{{ letterOf(o, k) }}</span><span class="t">{{ optText(o, letterOf(o, k)) }}</span>
        </button>
      </template>
    </template>
    <template v-else-if="isFill">
      <div class="meta" style="margin:-6px 0 8px">填空题：每空都要填，提交后逐空判对错（多空可用 | 分隔一次粘贴）</div>
      <div v-for="(t, k) in fillTexts" :key="k" class="row" style="align-items:center;margin-bottom:8px">
        <span class="meta" style="width:52px">第 {{ k + 1 }} 空</span>
        <el-input v-model="fillTexts[k]" :placeholder="'第 ' + (k + 1) + ' 空'" size="default"
                  style="flex:1" :disabled="!!shown" @keyup.enter="submit" />
      </div>
    </template>
    <textarea v-else v-model="freeText" placeholder="先自己答，再点提交看参考答案（自评）"></textarea>

    <div class="row" style="margin-top:10px">
      <button class="act" @click="submit">提交</button>
      <button class="ghost" @click="skip">跳过</button>
      <button class="ghost" style="margin-left:auto" @click="emit('next')">下一题</button>
    </div>

    <div v-if="fb" class="fb" :class="fb.cls">
      <div>{{ fb.head }}</div>
      <div v-if="fb.fill" class="meta" style="margin-top:4px">
        <div v-for="d in fb.fill" :key="d.i" :style="{ color: d.ok ? 'var(--ok, #3B6D11)' : 'var(--bad, #A32D2D)' }">
          第 {{ d.i }} 空：<template v-if="d.given">你填「{{ d.given }}」</template><template v-else>（未填）</template>
          {{ d.ok ? '✓' : '✗ 应为「' + d.ans + '」' }}
        </div>
      </div>
      <div v-if="fb.expl">题解：{{ fb.expl }}</div>
      <div v-if="fb.self && !fb.selfDone" class="row" style="margin-top:6px">
        <button class="ghost" @click="selfEval('correct')">我答对了</button>
        <button class="ghost" @click="selfEval('wrong')">答错了</button>
      </div>
      <div v-if="fb.flash" class="meta">{{ fb.flash }}</div>
    </div>

    <QbNotePad v-model:editing="noteEditing" :qid="q.id" />

    <div class="meta" style="margin-top:10px">
      <template v-if="isJudge">快捷键：<span class="kbd">1</span> 对 · <span class="kbd">2</span> 错 · <span class="kbd">T</span>/<span class="kbd">F</span> 也可 · <span class="kbd">Enter</span> 提交/下一题 · <span class="kbd">→</span> 下一题</template>
      <template v-else-if="isChoice">快捷键：<span class="kbd">A</span>–<span class="kbd">H</span> 或 <span class="kbd">1</span>–<span class="kbd">8</span> 选择 · <span class="kbd">Enter</span> 提交/下一题 · <span class="kbd">→</span> 下一题</template>
      <template v-else>快捷键：<span class="kbd">Enter</span> 提交/下一题 · <span class="kbd">→</span> 下一题</template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElInput } from 'element-plus'
import { api } from './api'
import { session } from './session'
import { notes } from './notes'
import { bump } from './bus'
import { qtMeta, lvMeta, fmtDue, optLetter, optText } from './util'
import QbNotePad from './QbNotePad.vue'

const props = defineProps<{ q: any; index?: number; total?: number; label?: string }>()
const emit = defineEmits<{ (e: 'next'): void }>()

const SVG_CK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
const SVG_XX = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>'

const qm = computed(() => qtMeta(props.q.qtype))
const lv = computed(() => lvMeta(props.q.level))
const lvKey = computed(() => (props.q.level == null ? '' : String(props.q.level)))
const isJudge = computed(() => /判断/.test(props.q.qtype || '') && !(props.q.options || []).length)
const isMulti = computed(() => /多选/.test(props.q.qtype || ''))
/* 可判分填空：qtype 含填空且 answer 用 | 分隔各空（PDF 摘录编辑器保存的挖空题）。
   老填空数据（answer 无 |）不命中，继续走自评 textarea——向后兼容。 */
const isFill = computed(() => /填空/.test(props.q.qtype || '')
  && (props.q.answer || '').indexOf('|') >= 0)
const fillCount = computed(() => (isFill.value ? (props.q.answer || '').split('|').length : 0))
const fillTexts = ref<string[]>([])
watch(() => [props.q.id, fillCount.value], () => {
  const prev = String(session.given[props.q.id] || '').split('|')
  fillTexts.value = Array.from({ length: fillCount.value }, (_, k) => (prev[k] != null ? prev[k] : ''))
}, { immediate: true })
const effOpts = computed<string[]>(() => (props.q.options || []).length ? props.q.options : (isJudge.value ? ['对', '错'] : []))
const isChoice = computed(() => effOpts.value.length > 0)
const given = computed(() => String(session.given[props.q.id] || ''))
const shown = computed(() => session.shown[props.q.id] || null)
const fb = computed(() => session.fb[props.q.id] || null)
const my = computed(() => notes.value[props.q.id] || null)
const src = computed(() => [props.q.id, props.q.sec, props.q.bank,
  props.q.source_class === '自定义' ? '自定义导入' : ''].filter(Boolean).join(' · '))

const freeText = ref('')
const noteEditing = ref(false)

function letterOf(o: any, k: number) { return optLetter(o, k, isJudge.value) }

/* 提交后按服务端判分结果着色：正确的绿、选错的红（与旧版 isRight 同逻辑） */
function isRight(letter: string) {
  const sh = shown.value
  if (!sh) return false
  const ans = String(sh.answer || '')
  if (ans === '对' || ans === '错') {
    if (letter === '对' || letter === '错') return letter === ans
    const opts = props.q.options || []
    for (let k = 0; k < opts.length; k++) {
      const t = String(opts[k])
      const isTrue = /对|正确|√|✓/.test(t), isFalse = /错|错误|×|✗/.test(t)
      if ((ans === '对' && isTrue) || (ans === '错' && isFalse)) return optLetter(opts[k], k, false) === letter
    }
    return false
  }
  return ((ans.toUpperCase().match(/[A-H]/g) || []) as string[]).includes(letter)
}

function optCls(o: any, k: number) {
  const letter = letterOf(o, k)
  const sel = given.value.includes(letter) ? ' sel' : ''
  const mark = shown.value ? (isRight(letter) ? ' right' : (given.value.includes(letter) ? ' wrong' : '')) : ''
  return (isJudge.value ? ' judge' : '') + sel + mark
}

function choose(o: any, k: number) {
  if (shown.value) return
  const letter = letterOf(o, k)
  if (isMulti.value) {
    const cur = (given.value || '').split('').filter(Boolean)
    const next = cur.includes(letter) ? cur.filter((x) => x !== letter) : [...cur, letter].sort()
    session.given[props.q.id] = next.join('')
  } else {
    session.given[props.q.id] = letter
  }
}

function chooseByLetter(letter: string) {
  const k = effOpts.value.findIndex((o, i) => letterOf(o, i) === letter)
  if (k >= 0) choose(effOpts.value[k], k)
}

async function submit() {
  const q = props.q
  if (session.shown[q.id]) { emit('next'); return }          // 已提交过：再按=下一题
  let givenRaw: string
  if (isFill.value) {
    session.given[q.id] = fillTexts.value.map((t) => t.trim()).join('|')   // 多空按 | 拼接传给判分
    givenRaw = session.given[q.id]
    if (!fillTexts.value.some((t) => t.trim())) { ElMessage.warning('每空都要填'); return }
  } else {
    givenRaw = isChoice.value ? String(session.given[q.id] || '') : (freeText.value || '')
  }
  if (!givenRaw.trim()) { ElMessage.warning('先作答再提交'); return }
  const r = await api('/questions/' + encodeURIComponent(q.id) + '/grade', { given: givenRaw })
  if (!r) return
  if (r.error) { ElMessage.error(r.error === 'not found' ? '题目不存在：' + q.id : r.error); return }
  session.shown[q.id] = r
  if (r.self) {
    session.fb[q.id] = { cls: 'info', head: '参考答案：' + (r.answer || ''), expl: r.explanation || '', self: true }
  } else {
    r.correct ? session.res.ok++ : session.res.bad++
    session.fb[q.id] = {
      cls: r.correct ? 'ok' : 'bad', self: false, fill: r.fill || null,
      head: (r.correct ? '✓ 答对了' : '✗ 答错了') + '　正确答案：' + (r.answer || ''),
      expl: r.explanation || '',
    }
    const m = await api('/progress/' + encodeURIComponent(q.id), { result: r.correct ? 'correct' : 'wrong' }, 'PUT')
    if (m) session.fb[q.id].flash = '下次复习：' + fmtDue(m.due) + (m.streak > 1 ? ' · 连续答对 ' + m.streak + ' 次' : '')
    bump()
  }
}

async function selfEval(result: 'correct' | 'wrong') {
  const q = props.q
  const m = await api('/progress/' + encodeURIComponent(q.id), { result }, 'PUT')
  session.res.self++
  const f = session.fb[q.id]
  if (f) {
    f.selfDone = true
    f.flash = m
      ? (result === 'correct' ? '已记为掌握 · 下次复习 ' + fmtDue(m.due)
                              : '已进错题本 · 明天再来 · 下次复习 ' + fmtDue(m.due))
      : (result === 'correct' ? '已记为掌握' : '已进错题本')
  }
  bump()
}

async function skip() {
  await api('/progress/' + encodeURIComponent(props.q.id), { result: 'skip' }, 'PUT')
  session.res.skip++
  bump()
  emit('next')
}

/* ---- 键盘快捷键（与旧版一致：判断题 1/T 对、2/F 错；选择题 A-H/1-8；Enter 提交/下一题；→ 下一题）---- */
function onKey(e: KeyboardEvent) {
  if (noteEditing.value) {
    if (e.key === 'Escape') { e.preventDefault(); noteEditing.value = false }
    return
  }
  const t = e.target as HTMLElement | null
  if (t && /INPUT|TEXTAREA|SELECT/.test(t.tagName)) return
  const q = props.q
  const done = !!session.shown[q.id]
  if (e.key === 'Enter') { e.preventDefault(); done ? emit('next') : submit(); return }
  if (e.key === 'ArrowRight') { e.preventDefault(); emit('next'); return }
  const m = e.key.toLowerCase().match(/^([a-h1-8])$/)
  if (isJudge.value) {
    const jk = e.key.toLowerCase()
    if (jk === '1' || jk === 't') chooseByLetter('对')
    if (jk === '2' || jk === 'f') chooseByLetter('错')
    return
  }
  if (m && !done) {
    const k = m[1]
    chooseByLetter((k >= '1' && k <= '8') ? String.fromCharCode(64 + Number(k)) : k.toUpperCase())
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>
