<template>
  <div>
    <div class="surface" id="omStatus">
      <div class="om-row" style="justify-content:space-between">
        <div>
          <div style="font-weight:600">OpenMAIC · AI 课堂</div>
          <div style="font-size:12px;color:var(--muted);margin-top:3px" v-html="status.line"></div>
          <div style="font-size:12px;color:var(--muted);margin-top:3px">生成时材料会发给 opencode.ai</div>
        </div>
        <div class="om-row">
          <template v-if="status.running">
            <a class="om-btn ghost" :href="status.url" target="_blank" style="text-decoration:none">打开 OpenMAIC</a>
            <button class="om-btn ghost" @click="omStopSvc()">停止服务</button>
          </template>
          <button v-else class="om-btn" :disabled="hubState.om.starting" @click="omStartSvc()">
            {{ hubState.om.starting ? '启动中…' : '启动服务' }}
          </button>
        </div>
      </div>
    </div>

    <div class="grid cols-2" style="margin-top:14px">
      <div class="card">
        <div class="card-head">
          <span>挑文档生成</span>
          <span class="om-row" style="gap:6px">
            <span class="tag">{{ docs.count }} / {{ docs.total }} 篇</span>
            <button class="om-chip mini" @click="omSelAll()">全选</button>
            <button class="om-chip mini" @click="omSelNone()">清空</button>
          </span>
        </div>
        <div class="om-row">
          <button
            v-for="(c, i) in rootChips"
            :key="i"
            class="om-chip"
            :class="{ on: c.active }"
            :title="c.title"
            @click="onRootChip(c.root)"
          >{{ c.label }}</button>
          <button class="om-chip" @click="onRescan">重新扫描</button>
        </div>
        <input v-model="hubState.om.q" class="om-input" placeholder="搜索标题 / 路径 / 内容…" style="margin-top:10px" @input="onSearch">
        <div class="om-list">
          <div v-if="!docs.docs.length" style="font-size:13px;color:var(--muted);padding:10px">
            {{ docs.count === 0 && hubState.om.q ? '没有匹配的文档' : '没有匹配的文档（只索引 .md / .markdown / .txt）' }}
          </div>
          <div
            v-for="(d, i) in docs.docs"
            :key="i"
            class="om-doc"
            :class="{ on: d.on }"
            @click="omToggleDoc(d.absPath)"
          >
            <div class="cb">✓</div>
            <div style="min-width:0;flex:1">
              <div class="t">{{ d.title }}</div>
              <div class="p">{{ d.relPath }}</div>
              <div class="e">{{ d.excerpt }}</div>
              <div class="p" style="margin-top:3px">{{ d.meta }}</div>
            </div>
          </div>
          <div v-if="docs.more > 0" style="text-align:center;margin-top:8px">
            <button class="om-btn ghost" @click="hubState.om.limit += 100">显示更多（还有 {{ docs.more }} 篇）</button>
          </div>
        </div>
      </div>

      <div>
        <div class="card" style="margin-bottom:14px">
          <div class="card-head"><span>生成设置</span></div>
          <div class="om-row" style="margin-bottom:10px">
            <button class="om-chip" :class="{ on: hubState.om.mode === 'merge' }" @click="hubState.om.mode = 'merge'">合成一门课</button>
            <button class="om-chip" :class="{ on: hubState.om.mode === 'each' }" @click="hubState.om.mode = 'each'">每篇各一门</button>
          </div>
          <input v-model="omName" class="om-input" placeholder="课程名（可留空）">
          <div style="font-size:12px;color:var(--muted);margin:10px 0 8px">{{ selInfo.text }}</div>
          <button class="om-btn" :disabled="!selInfo.count" @click="onGenerate">{{ genBtnText }}</button>
          <div style="margin-top:14px;border-top:1px solid var(--card-border);padding-top:12px">
            <div style="font-size:12px;color:var(--muted);margin-bottom:6px">或者只给一个主题</div>
            <div class="om-row">
              <input v-model="omTopic" class="om-input" placeholder="例如：讲清二分查找的原理和一个易错点" style="flex:1;min-width:160px">
              <button class="om-btn ghost" @click="onTopicGenerate">按主题生成</button>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span>生成任务</span><span class="tag">{{ jobs.tag }}</span></div>
          <div v-if="!jobs.jobs.length" style="font-size:13px;color:var(--muted);padding:4px 0">还没有生成任务</div>
          <div v-for="(j, i) in jobs.jobs" :key="i" class="om-job">
            <div class="om-row" style="justify-content:space-between;align-items:flex-start">
              <div style="min-width:0;flex:1">
                <div style="font-size:13px;font-weight:500">{{ j.label }}</div>
                <div style="font-size:11.5px;color:var(--muted);margin-top:2px" v-html="j.state + ' · ' + esc(j.meta)"></div>
              </div>
              <a v-if="j.url" class="om-btn" :href="j.url" target="_blank" style="text-decoration:none">进教室 →</a>
            </div>
            <div class="om-bar"><i :style="{ width: j.progress + '%' }"></i></div>
            <div v-if="j.error" style="font-size:11.5px;color:var(--red);margin-top:5px">{{ j.error }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  hubState, esc,
  omStatusView, omStartSvc, omStopSvc, omRootChipsView, omDocsView, omSelInfo, omToggleDoc,
  omSelAll, omSelNone, omGenerate, omTopicGenerate, omJobsView, omLoadDocs,
} from './hubStore'

defineOptions({ name: 'ClassroomView' })

const omName = ref('')
const omTopic = ref('')

const status = computed(() => omStatusView())
const rootChips = computed(() => omRootChipsView())
const docs = computed(() => omDocsView())
const selInfo = computed(() => omSelInfo())
const jobs = computed(() => omJobsView())
const genBtnText = computed(() => {
  if (!selInfo.value.count) return '生成课堂'
  return hubState.om.mode === 'merge' ? '生成课堂（1 门）' : '生成课堂（' + selInfo.value.count + ' 门）'
})

function onRootChip(root: string) {
  hubState.om.root = root
  hubState.om.limit = 100
}
function onSearch() { hubState.om.limit = 100 }
function onRescan() { omLoadDocs(true).catch(() => {}) }

async function onGenerate() {
  try { await omGenerate(omName.value.trim()) }
  catch (e: any) { /* showErr 已由调用方设置 */ }
}
async function onTopicGenerate() {
  try { await omTopicGenerate(omTopic.value.trim()) }
  catch (e: any) { /* showErr 已由调用方设置 */ }
}
</script>
