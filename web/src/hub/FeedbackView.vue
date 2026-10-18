<template>
  <div class="card">
    <div class="card-head"><span>最近反馈</span><span class="tag">每日反馈摘要</span></div>
    <div v-if="!items.length" class="empty">还没有反馈记录</div>
    <div v-for="(it, i) in items" :key="i" class="fb-item">
      <div class="fb-head">
        <span class="fb-date">{{ fmtDate(it.date) }}</span>
        <a :href="'obsidian://open?vault=self-improve&file=' + encodeURIComponent('DeepTutor/每日反馈/' + it.name)" target="_blank">打开 →</a>
      </div>
      <div v-if="it.digest" class="fb-digest">{{ it.digest }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { hubState, fmtDate } from './hubStore'

defineOptions({ name: 'FeedbackView' })

const items = computed(() => hubState.feedback || [])
</script>
