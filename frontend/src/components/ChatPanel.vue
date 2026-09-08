<script setup lang="ts">
import { ref } from 'vue'

import { extractPreferences } from '@/api/preferences'
import ThinkingPanel from '@/components/ThinkingPanel.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'
import { useGenerationStore } from '@/stores/generation'
import { useProfileStore } from '@/stores/profile'
import { useTripsStore } from '@/stores/trips'

const store = useCurrentTripStore()
const generation = useGenerationStore()
const trips = useTripsStore()
const profile = useProfileStore()

const draft = ref('')
const thinking = ref(true)

async function send() {
  if (!draft.value.trim() || !store.trip || generation.phase === 'running') return
  const current = store.trip
  const message = draft.value.trim()
  const done = generation.run(
    '/api/trips/chat',
    { trip: current, message, thinking_effort: thinking.value ? 'high' : 'low', profile: profile.items },
  )
  await done
  if (generation.phase === 'done' && generation.result) {
    // 只在真实改动（version+1）时存快照，纯问答不占撤销栈
    if (generation.result.version !== current.version) trips.saveSnapshot(current)
    const next = { ...generation.result, thinking: generation.thinking, thinkingMs: generation.thinkingMs }
    store.replaceTrip(next)
    trips.upsert(next)
    draft.value = ''
  }
  // 静默抽取长期偏好入档案，失败不影响主流程
  extractPreferences(message)
    .then((items) => profile.addAll(items))
    .catch(() => {})
}

function undo() {
  if (!store.trip) return
  const restored = trips.undo(store.trip)
  if (restored) store.replaceTrip(restored)
}

function fmt(ts?: string) {
  return ts ? ts.slice(5, 16).replace('T', ' ') : ''
}
</script>

<template>
  <div class="no-print flex flex-col rounded-xl border border-teal-200 bg-teal-50/50 p-3">
    <h3 class="mb-2 text-sm font-bold text-slate-700">和 AI 规划师聊两句</h3>

    <!-- 对话历史 -->
    <div class="mb-2 max-h-60 space-y-2 overflow-y-auto pr-1">
      <div
        v-for="(m, i) in store.trip?.chat ?? []"
        :key="i"
        class="max-w-[85%] rounded-xl px-3 py-1.5 text-sm whitespace-pre-wrap"
        :class="m.role === 'user' ? 'ml-auto bg-teal-600 text-white' : 'bg-white text-slate-700'"
        :title="fmt(m.ts)"
      >
        {{ m.content }}
      </div>
    </div>

    <!-- 运行中的进度与思考 -->
    <p v-if="generation.phase === 'running'" class="h-4 text-xs text-teal-700">
      {{ generation.messages.at(-1) ?? '…' }}
    </p>
    <div v-if="generation.phase === 'running'" class="mb-2">
      <ThinkingPanel :text="generation.thinking" running />
    </div>
    <p v-else-if="generation.phase === 'error'" class="text-xs text-red-600">
      {{ generation.error?.message }}
    </p>

    <!-- 输入区 -->
    <form class="flex gap-2" @submit.prevent="send">
      <input
        v-model="draft"
        type="text"
        :disabled="generation.phase === 'running'"
        placeholder="如：第二天别太赶 / 把灵隐寺换成博物馆 / 要花多少钱？"
        class="flex-1 rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        :disabled="generation.phase === 'running' || !draft.trim()"
        class="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
      >
        {{ generation.phase === 'running' ? '…' : '发送' }}
      </button>
      <button
        v-if="store.trip && trips.snapshotCount(store.trip.id!) > 0"
        type="button"
        class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
        title="恢复到上次改动前"
        @click="undo"
      >
        撤销
      </button>
    </form>
    <label class="mt-2 flex w-fit cursor-pointer items-center gap-1.5 text-xs text-slate-500">
      <input v-model="thinking" type="checkbox" class="h-3.5 w-3.5 accent-teal-600" />
      深度思考（取消=快速档）
    </label>
  </div>
</template>
