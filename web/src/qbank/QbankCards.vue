<template>
  <section>
    <div class="card">
      <div class="row">
        <el-input v-model="kw" placeholder="搜知识点，如：V形块 / 轴承 / 粗糙度" style="width:260px"
                  clearable @keyup.enter="go" />
        <label>章节
          <el-select v-model="chapter" placeholder="全部章节" clearable style="width:220px" @change="go">
            <el-option v-for="c in chapters" :key="c.chapter" :value="c.chapter"
                       :label="c.chapter + '（' + c.n + '）'" />
          </el-select>
        </label>
        <button class="act" @click="go">搜索</button>
        <span class="sub">{{ items.length }} 张卡</span>
      </div>
    </div>
    <template v-if="groups.length">
      <div v-for="[ch, list] in groups" :key="ch" class="card">
        <b>{{ ch }}</b><div class="meta" style="margin:2px 0 10px">{{ list.length }} 张</div>
        <div v-for="c in list" :key="c.name + c.topic" class="card-item">
          <h4>{{ c.name }}</h4>
          <p>{{ c.body }}</p>
          <div class="meta">{{ c.topic }}{{ (c.qids && c.qids.length) ? ' · 对应题号 ' + c.qids.join('、') : '' }}</div>
        </div>
      </div>
    </template>
    <div v-else class="card empty">没找到，换个关键词</div>
  </section>
</template>

<script setup lang="ts">
/* QbankCards.vue — 知识点卡片：按章节分组浏览/搜索 */
import { computed, onMounted, ref } from 'vue'
import { ElInput, ElSelect, ElOption } from 'element-plus'
import { api } from './api'

interface CardRow { chapter: string; topic: string; name: string; body: string; qids: string[] }
interface ChapterRow { chapter: string; n: number }

const kw = ref('')
const chapter = ref('')
const items = ref<CardRow[]>([])
const chapters = ref<ChapterRow[]>([])

const groups = computed<[string, CardRow[]][]>(() => {
  const by: Record<string, CardRow[]> = {}
  items.value.forEach((c) => { (by[c.chapter] = by[c.chapter] || []).push(c) })
  return Object.entries(by)
})

async function go() {
  const p = new URLSearchParams({ limit: '500' })
  if (kw.value) p.set('q', kw.value)
  if (chapter.value) p.set('chapter', chapter.value)
  const r = await api('/cards?' + p.toString())
  items.value = (r && r.items) || []
}

onMounted(async () => {
  const ch = await api('/chapters')
  chapters.value = (ch && ch.items) || []
  await go()
})
</script>
