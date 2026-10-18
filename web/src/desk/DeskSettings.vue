<template>
  <div class="page page-settings">
    <div class="card">
      <div class="card-head"><span>服务器</span><span class="conn-dot" :class="{ ok: s.sync.online }"></span></div>
      <div class="hint">{{ s.serverInfo }}</div>
    </div>

    <div class="card">
      <div class="card-head"><span>背景</span></div>
      <div class="bg-grid">
        <div
          v-for="(g, i) in PRESET_BGS"
          :key="i"
          class="bg-cell"
          :class="{ active: s.bgIndex === i && !s.customBg }"
          :style="{ background: g }"
          @click="pickBg(i)"
        ></div>
      </div>
      <div class="btn-row">
        <button class="btn plain" @click="pickBgFromAlbum">从相册选择</button>
        <button class="btn plain" @click="clearBg">恢复默认</button>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><span>关于</span></div>
      <div class="hint">工具箱 · 离线优先 · 数据仅存于本机局域网 · 学习中枢的一部分</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { deskState as s, PRESET_BGS, pickBg, pickBgFromAlbum, clearBg } from './store'

defineOptions({ name: 'DeskSettings' })
</script>
