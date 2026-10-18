<template>
  <div class="page page-fav">
    <div class="card">
      <div class="card-head">
        <span>当日收藏</span>
        <input type="date" class="date-input" v-model="s.favDate" @change="loadFavorites" />
      </div>
      <div class="seg">
        <button class="seg-btn" :class="{ active: s.favPlatform === 'all' }" @click="switchPlatform('all')">全部</button>
        <button class="seg-btn" :class="{ active: s.favPlatform === 'douyin' }" @click="switchPlatform('douyin')">抖音</button>
        <button class="seg-btn" :class="{ active: s.favPlatform === 'xiaohongshu' }" @click="switchPlatform('xiaohongshu')">小红书</button>
      </div>
      <div v-if="!s.sync.online && !s.favItems.length" class="empty">离线模式，该日期无缓存</div>
      <div v-else-if="s.favLoading && !s.favItems.length" class="empty">加载中…</div>
      <div v-else-if="!s.favItems.length" class="empty">这一天没有新增收藏</div>
      <a v-for="(it, i) in s.favItems" :key="i" class="fav-item" :href="it.url || '#'" target="_blank">
        <div class="fav-body">
          <div class="fav-title">{{ it.title }}</div>
          <div class="fav-meta">{{ it.author }} · {{ (it.collected_at || '').replace('T', ' ').slice(5, 16) }}</div>
        </div>
        <div class="fav-badge" :class="it.platform">{{ it.platform === 'douyin' ? '抖音' : '小红书' }}</div>
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { deskState as s, loadFavorites } from './store'

defineOptions({ name: 'DeskFav' })

function switchPlatform(p: string) {
  s.favPlatform = p
  loadFavorites()
}

onMounted(() => { loadFavorites() })
</script>
