<template>
  <div>
    <div class="surface">
      <div class="cell" v-for="(s, i) in stats" :key="i">
        <div class="v" :class="s.cls">{{ s.v }}<small>{{ s.u }}</small></div>
        <div class="k">{{ s.k }}</div>
      </div>
    </div>
    <div class="grid cols-2">
      <div class="card">
        <div class="card-head"><span>今日任务</span><span class="tag">{{ diaryDateText }}</span></div>
        <div v-if="!hubState.today || !hubState.today.diary" class="empty">
          今天还没有写日记<br><a href="obsidian://open?vault=self-improve" target="_blank">打开 Obsidian 写日记 →</a>
        </div>
        <ul v-else-if="hubState.tasks.length" class="task-list">
          <li
            v-for="t in hubState.tasks"
            :key="t.index"
            :class="{ done: t.done }"
            @click="onToggleTask(t)"
          >
            <span class="box"></span><span class="t">{{ t.title }}</span>
            <span v-if="t.score" class="sc">+{{ t.score }}</span>
          </li>
        </ul>
        <div v-else class="empty">暂无任务</div>
      </div>
      <div>
        <div class="card" style="margin-bottom:14px">
          <div class="card-head"><span>复习到期</span><span class="tag">{{ dueTag }}</span></div>
          <div v-if="!dueList.length" class="empty">今日无到期复习 ✨</div>
          <HubRevItem v-for="(r, i) in dueList" :key="i" :item="r" />
        </div>
        <div class="card">
          <div class="card-head"><span>今日 DeepTutor</span></div>
          <template v-if="notes.length">
            <div v-for="(g, i) in notes" :key="i" style="margin-bottom:8px">
              <div style="font-size:12px;color:var(--muted);margin-bottom:4px">{{ g.kind }}</div>
              <div v-for="(it, j) in g.items" :key="j" style="font-size:13px">
                <a :href="obsidianFileUrl(it.path)" target="_blank">{{ it.name }}</a>
              </div>
            </div>
          </template>
          <div v-else class="empty">今日暂无 DeepTutor 产出</div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head"><span>近 30 天打卡</span><span class="tag">完成任务数</span></div>
      <div class="heat">
        <div v-for="(d, i) in hubState.heat" :key="i" class="cell" :class="d.cls" :title="d.tip">
          <span class="tip">{{ d.tip }}</span>
        </div>
      </div>
      <div class="heat-legend">少 <span class="cell"></span><span class="cell l1"></span><span class="cell l2"></span><span class="cell l3"></span><span class="cell l4"></span> 多</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import HubRevItem from './HubRevItem.vue'
import { hubState, todayStatsView, todayNotesView, obsidianFileUrl, toggleTask, fmtDate } from './hubStore'

defineOptions({ name: 'TodayView' })

const stats = computed(() => todayStatsView())
const diaryDateText = computed(() => (hubState.today && hubState.today.diary ? fmtDate(hubState.date) : '无日记'))
const dueList = computed(() => {
  const t = hubState.today
  return t && t.review && t.review.due ? t.review.due.slice(0, 5) : []
})
const dueTag = computed(() => dueList.value.length + ' 条')
const notes = computed(() => todayNotesView())

async function onToggleTask(t: { index: number; done: boolean }) {
  await toggleTask(t.index, !t.done)
}
</script>
