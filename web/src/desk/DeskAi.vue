<template>
  <div class="page page-ai">
    <div class="ai-chat" ref="chatEl">
      <div v-if="!s.aiMsgs.length" class="ai-welcome">
        <div class="ai-welcome-title">👋 我是你的 AI 数字同事</div>
        <div class="ai-welcome-sub">我能读懂你的学习、使用、健康、任务与收藏数据<br>随时总结、分析、给建议、定计划</div>
        <div class="ai-chips">
          <button v-for="q in chips" :key="q.q" class="chip" @click="ask(q.q)">{{ q.label }}</button>
        </div>
      </div>
      <div v-for="(m, i) in s.aiMsgs" :key="i" class="ai-msg" :class="m.role" v-html="m.content"></div>
      <div v-if="s.aiBusy" class="ai-msg assistant">…</div>
    </div>
    <div class="ai-inputbar">
      <input class="text-input ai-input" v-model="s.aiInput" placeholder="问点什么…" @keydown.enter="sendAi()" />
      <button class="btn primary ai-send" @click="sendAi()">发送</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { deskState as s, sendAi } from './store'

defineOptions({ name: 'DeskAi' })

const chatEl = ref<HTMLElement>()
const chips = [
  { label: '📊 今日总结', q: '总结一下我今天的学习情况' },
  { label: '⏱ 使用分析', q: '分析我今天的使用时间和效率，给建议' },
  { label: '📋 明日计划', q: '根据我的情况制定明天的学习计划' },
  { label: '🎯 薄弱点建议', q: '看看我的考研薄弱点，给复习建议' },
  { label: '🔙 复盘昨天', q: '复盘一下昨天的情况，找出问题' },
  { label: '📅 本周总结', q: '总结一下本周的学习和使用情况' },
  { label: '⚡ 高效时段', q: '分析我的高效时段，什么时候学习效率最高' },
  { label: '📌 任务排序', q: '帮我给未完成任务排个优先级，今天先做什么' },
  { label: '🏃 健康建议', q: '根据我的睡眠和运动数据给健康建议' },
]

function ask(q: string) {
  s.aiInput = q
  sendAi()
}

/* 概览页快捷输入条：跳转后自动提问 */
onMounted(() => {
  ;(window as any).__deskAiAsk = (q: string) => ask(q)
})

watch(() => s.aiMsgs.length, () => {
  requestAnimationFrame(() => {
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  })
})
</script>
