<template>
  <div class="page page-photos">
    <div class="card">
      <div class="card-head"><span>照片同步</span><span class="muted sm">{{ s.photoCount }}</span></div>
      <input ref="fileInput" type="file" accept="image/*" class="hidden-input" @change="onFile" />
      <button class="btn primary block" @click="fileInput?.click()">
        {{ s.photoBusy ? '上传中…' : '选择照片上传 → 同步到 Obsidian' }}
      </button>
      <div class="hint">照片将同步到 PC Obsidian 的「工作台照片/月份/」目录（需在线）</div>
    </div>
    <div class="card">
      <div class="card-head"><span>已同步照片</span></div>
      <div v-if="!s.sync.online" class="empty">离线模式：照片需连接 PC 查看</div>
      <div v-else-if="!s.photos.length" class="empty">暂无照片</div>
      <div v-else class="photo-grid">
        <div v-for="(p, i) in s.photos" :key="i" class="photo-item">
          <img :src="photoUrl(p.url)" loading="lazy" @click="open(p.url)" />
          <div class="photo-date">{{ p.month }} {{ (p.name || '').replace('.jpg', '').slice(0, 8) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { deskState as s, loadPhotos, uploadPhoto } from './store'

defineOptions({ name: 'DeskPhotos' })

const fileInput = ref<HTMLInputElement>()

function photoUrl(url: string) {
  // M2c-P3：服务端给的 url 形如 /photos/2026-08/x.jpg?sig=…&exp=…
  // 它是**相对路径**（因为服务端不知道前端从哪个 origin 访问），
  // 这里只补服务器前缀，**绝不追加任何令牌**——签名本身就是凭据。
  return s.server.replace(/\/+$/, '') + url
}
function open(url: string) { window.open(photoUrl(url)) }
function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) uploadPhoto(f)
  ;(e.target as HTMLInputElement).value = ''
}

onMounted(() => { loadPhotos() })
</script>
