<template>
  <div class="rev-item">
    <span class="rev-badge" :class="v.due ? 'due' : 'normal'">{{ v.due ? '今日' : '进行中' }}</span>
    <div class="rev-info">
      <div class="rev-concept">{{ v.concept }}</div>
      <div class="rev-meta" v-html="v.meta"></div>
    </div>
    <button class="rev-done" title="完成复习，推进间隔" @click="onDone">✓</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { revItemView, reviewDone } from './hubStore'

const props = defineProps<{ item: any }>()
const v = computed(() => revItemView(props.item))

async function onDone() {
  await reviewDone(v.value.concept)
}
</script>
