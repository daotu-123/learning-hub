<template>
  <div class="page page-diary">
    <div class="card diary-card">
      <div class="card-head">
        <span>文档编辑</span>
        <span class="save-tag">{{ s.diarySaveTag }}</span>
      </div>
      <div class="doc-selector">
        <div class="seg">
          <button class="seg-btn" :class="{ active: s.docType === 'diary' }" @click="switchDocType('diary')">日记</button>
          <button class="seg-btn" :class="{ active: s.docType === 'weekly' }" @click="switchDocType('weekly')">周记</button>
          <button class="seg-btn" :class="{ active: s.docType === 'monthly' }" @click="switchDocType('monthly')">月记</button>
        </div>
        <input v-if="s.docType === 'diary'" type="date" class="date-input doc-key" v-model="s.docKeyDiary" @change="loadDiary" />
        <input v-if="s.docType === 'weekly'" type="week" class="date-input doc-key" v-model="s.docKeyWeekly" @change="loadDiary" />
        <input v-if="s.docType === 'monthly'" type="month" class="date-input doc-key" v-model="s.docKeyMonthly" @change="loadDiary" />
      </div>
      <div class="diary-meta">{{ s.diaryMeta }}</div>
      <textarea class="diary-editor" v-model="s.diaryContent" placeholder="编辑文档内容…" spellcheck="false" @input="renderDiaryImgs"></textarea>
      <div class="diary-imgs">
        <template v-if="s.diaryImgs.length">
          <div class="diary-thumb" v-for="(rel, i) in s.diaryImgs" :key="i" @click="viewer = diaryImgUrl(rel)">
            <img :src="diaryImgUrl(rel)" loading="lazy" />
          </div>
        </template>
        <div v-else class="empty">文档中的图片将显示在这里（可点开查看/下载）</div>
      </div>
      <div class="btn-row">
        <button class="btn primary" @click="saveDiary">保存并同步</button>
        <button class="btn plain" @click="pickImg">📷 插图</button>
        <button class="btn plain" @click="loadDiary">重新加载</button>
      </div>
      <input ref="imgInput" type="file" accept="image/*" class="hidden-input" @change="onImg" />
      <div class="hint">📷 图片将上传到 PC Obsidian「工作台照片/月份/」并插入文档；PC 日记里的 ![[图片]] 也会显示在这里，点开可下载</div>
    </div>

    <!-- 图片查看器 -->
    <div v-if="viewer" class="viewer" @click.self="viewer = ''">
      <img :src="viewer" alt="" />
      <div class="viewer-bar">
        <button class="btn primary" @click="download(viewer)">下载到相册</button>
        <button class="btn plain" @click="viewer = ''">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  deskState as s, switchDocType, loadDiary, saveDiary, renderDiaryImgs,
  diaryImgUrl, uploadDiaryImage, native,
} from './store'

defineOptions({ name: 'DeskDiary' })

const imgInput = ref<HTMLInputElement>()
const viewer = ref('')

function pickImg() { imgInput.value?.click() }
function onImg(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) uploadDiaryImage(f)
  ;(e.target as HTMLInputElement).value = ''
}
function download(url: string) {
  if (!native.downloadImage(url)) alert('当前环境不支持下载')
}

onMounted(() => { loadDiary() })
</script>
