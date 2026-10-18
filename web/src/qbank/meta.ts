/* meta.ts — 筛选项元数据（题库/来源下拉 + 题型/难度真实分布），懒加载一次；
 * 导入新题后由调用方 force=true 重建（题库分布变了） */
import { ref } from 'vue'
import { api } from './api'

export interface BankRow { bank: string; n: number }
export interface SectionRow { section: string; n: number }

export const banks = ref<BankRow[]>([])       // [{bank, n}]
export const sections = ref<SectionRow[]>([]) // [{section, n}]
export const byType = ref<Record<string, number>>({})   // {题型: 题数}
export const byLevel = ref<Record<string, number>>({})  // {难度: 题数}
const loaded = ref(false)

export async function loadMeta(force?: boolean) {
  if (loaded.value && !force) return
  loaded.value = true
  const [bs, ss, st] = await Promise.all([api('/banks'), api('/sections'), api('/stats')])
  banks.value = (bs && bs.items) || []
  sections.value = (ss && ss.items) || []
  if (st) { byType.value = st.by_type || {}; byLevel.value = st.by_level || {} }
}
