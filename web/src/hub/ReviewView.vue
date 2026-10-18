<template>
  <div>
    <div class="surface">
      <div class="cell" v-for="(s, i) in stats" :key="i">
        <div class="v" :class="s.cls">{{ s.v }}<small>{{ s.u }}</small></div>
        <div class="k">{{ s.k }}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><span>到期复习</span><span class="tag">艾宾浩斯间隔</span></div>
      <div v-if="!due.length" class="empty">没有到期复习 ✨</div>
      <HubRevItem v-for="(r, i) in due" :key="i" :item="r" />
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head"><span>全部进行中</span></div>
      <div v-if="!activeItems.length" class="empty">暂无进行中的复习</div>
      <HubRevItem v-for="(r, i) in activeItems" :key="i" :item="r" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import HubRevItem from './HubRevItem.vue'
import { hubState, reviewStatsView } from './hubStore'

defineOptions({ name: 'ReviewView' })

const stats = computed(() => reviewStatsView())
const due = computed(() => (hubState.review && hubState.review.due) || [])
const activeItems = computed(() => (hubState.review && hubState.review.active_items) || [])
</script>
