/* notes.ts — 题目备注缓存（题卡显示「有备注」、进度页统一列表） */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from './api'

export interface NoteRow {
  id: string
  note: string
  updated_at: string
  stem?: string
  qtype?: string
  level?: number | null
  bank?: string
  missing?: boolean
}

export const notes = ref<Record<string, NoteRow>>({})  // {qid: {note, updated_at}}
export const notesList = ref<NoteRow[]>([])            // 排好序的列表

export async function loadNotes() {
  const r = await api('/notes')
  const items: NoteRow[] = (r && r.items) || []
  const map: Record<string, NoteRow> = {}
  items.forEach((n) => { map[n.id] = n })
  notes.value = map
  notesList.value = items
}

/* 写备注：空串 = 删除（与 RESTful PUT/DELETE 语义对应：静态 Store 用空串表达删除） */
export async function saveNote(qid: string, text: string) {
  const r = await api('/questions/' + encodeURIComponent(qid) + '/note', { note: text }, 'PUT')
  if (!r || r.error) {
    ElMessage.error(r && r.error === 'not found' ? '题目不存在：' + qid : (r && r.error) || '备注保存失败')
    return false
  }
  await loadNotes()
  ElMessage.success(r.removed ? '备注已删除' : '备注已保存（只属于 ' + qid + '）')
  return true
}

export async function deleteNote(qid: string) {
  const r = await api('/questions/' + encodeURIComponent(qid) + '/note', null, 'DELETE')
  if (!r || r.error) {
    ElMessage.error(r && r.error === 'not found' ? '题目不存在：' + qid : (r && r.error) || '备注删除失败')
    return false
  }
  await loadNotes()
  ElMessage.success('备注已删除')
  return true
}
