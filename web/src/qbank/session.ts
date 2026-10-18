/* session.ts — 刷题会话（跨视图共享：复习/错题/备注跳转都复用同一套题卡状态）
 *
 * 旧版是模块级 let S = {...}，五个视图直接改；Vue 版用 reactive 单例，语义不变。
 * feedback 从「暂存 HTML」改为结构化对象 {cls, head, expl, flash}，重渲染靠响应式。
 */
import { reactive } from 'vue'

export interface QbFilters {
  level: string
  qtype: string
  n: number
  onlyNew: boolean
  bank: string
  section: string
  q: string
}

export interface QbFeedback {
  cls: string
  head: string
  expl?: string
  fill?: { i: number; given: string; ok: boolean; ans: string }[] | null
  self?: boolean
  selfDone?: boolean
  flash?: string
}

export interface QbSession {
  items: any[]
  i: number
  given: Record<string, any>
  shown: Record<string, any>
  fb: Record<string, QbFeedback>
  noteEdit: string | null
  res: { ok: number; bad: number; self: number; skip: number }
  label: string
}

function blank(): QbSession {
  return {
    items: [], i: 0, given: {}, shown: {}, fb: {}, noteEdit: null,
    res: { ok: 0, bad: 0, self: 0, skip: 0 }, label: '',
  }
}

export const session = reactive<QbSession>(blank())

export function startSession(items: any[], label: string) {
  Object.assign(session, blank(), { items: items || [], label: label || '' })
}

export function curQuestion() {
  return session.items[session.i] || null
}
