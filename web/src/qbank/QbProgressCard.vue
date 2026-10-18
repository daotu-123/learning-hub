<template>
  <div class="card"><b>进度备份</b>
    <div class="row" style="margin-top:8px">
      <button class="ghost" @click="exportProg">导出进度 JSON</button>
      <button class="ghost" @click="fileRef && fileRef.click()">导入进度 JSON</button>
      <input ref="fileRef" type="file" accept=".json,application/json" class="hide" @change="onFile">
    </div>
    <textarea v-model="exportBox" readonly style="margin-top:10px;min-height:110px;font-family:Consolas,monospace;font-size:12px"
      placeholder="导出会显示在这里：长按全选复制即可备份；也可把备份 JSON 粘贴到这里，点下方按钮导入"></textarea>
    <button class="ghost" style="margin-top:8px" @click="importFromText">从文本导入进度</button>
    <div class="meta" style="margin-top:6px">导出可用于备份；换设备/换库后导入即合并恢复（不覆盖未出现的题）</div>
  </div>
</template>

<script setup lang="ts">
/* QbProgressCard.vue — 进度备份：导出 JSON 到文本框（离线可复制）/ 从文本或文件导入合并 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from './api'
import { bump } from './bus'

const exportBox = ref('')
const fileRef = ref<HTMLInputElement | null>(null)

function parseProg(t: string) {
  const d = JSON.parse(t)
  const prog = d && typeof d === 'object' ? (d.progress || d) : null
  if (!prog || typeof prog !== 'object') throw new Error('bad format')
  return prog
}

async function exportProg() {
  const r = await api('/progress')
  if (!r) return
  const n = Object.keys(r.progress || {}).length
  exportBox.value = JSON.stringify(r, null, 1)
  ElMessage.success('已生成 ' + n + ' 条进度文本，长按复制即可备份')
}

async function importProg(prog: any) {
  const r = await api('/progress', { progress: prog })
  if (r) { ElMessage.success('已导入 ' + r.imported + ' 条进度'); bump() }
}

function onFile(e: Event) {
  const el = e.target as HTMLInputElement
  const f = el.files && el.files[0]
  el.value = ''
  if (!f) return
  const rd = new FileReader()
  rd.onload = async () => {
    try { await importProg(parseProg(String(rd.result))) } catch (err) { ElMessage.error('文件解析失败：需要本工具导出的进度 JSON') }
  }
  rd.onerror = () => ElMessage.error('文件读取失败')
  rd.readAsText(f)
}

async function importFromText() {
  const txt = (exportBox.value || '').trim()
  if (!txt) { ElMessage.error('先把导出的进度 JSON 粘贴进上面的文本框'); return }
  try { await importProg(parseProg(txt)); exportBox.value = '' } catch (err) { ElMessage.error('解析失败：需要本工具导出的进度 JSON') }
}
</script>
