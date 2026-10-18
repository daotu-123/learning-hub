<template>
  <div class="grid cols-2" id="libGrid">
    <div v-for="(r, i) in roots" :key="i" class="lib-item">
      <div class="ic" v-html="r.icon"></div>
      <div style="flex:1">
        <div class="n">{{ r.name }}</div>
        <div class="c">{{ r.count }} 篇{{ r.recent.length ? ' · 最近：' + r.recent[0].name : '' }}</div>
      </div>
    </div>
    <div class="lib-item">
      <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg></div>
      <div style="flex:1">
        <div class="n">知识图谱</div>
        <div class="c">静态可拖拽图谱（F 盘）</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { hubState } from './hubStore'

defineOptions({ name: 'LibraryView' })

const roots = computed(() => (hubState.library && hubState.library.roots) || [])
</script>
