/* bus.ts — 数据变更版本号 + 视图切换
 *
 * dataVersion：导入题目/打卡/写备注后 bump()，进度页等监听它刷新统计，
 *   免去旧版「if 当前页可见就重载」的手动判断。
 * view/goView：合并单 App 后题库不再是独立路由应用，五页在组件内切换，
 *   深度链（#/qbank/stats）只用于首次进入时定位。
 */
import { ref } from 'vue'

export type QbView = 'quiz' | 'review' | 'wrong' | 'cards' | 'stats'

export const dataVersion = ref(0)
export function bump() { dataVersion.value++ }

export const view = ref<QbView>('quiz')
export function goView(v: QbView) { view.value = v }
