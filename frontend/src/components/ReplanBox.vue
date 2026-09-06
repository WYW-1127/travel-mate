<script setup lang="ts">
import { ref } from 'vue'

import ThinkingPanel from '@/components/ThinkingPanel.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'
import { useGenerationStore } from '@/stores/generation'
import { useTripsStore } from '@/stores/trips'

const store = useCurrentTripStore()
const generation = useGenerationStore()
const trips = useTripsStore()

const request = ref('')
const thinking = ref(true)

async function submit() {
  if (!request.value.trim() || !store.trip || generation.phase === 'running') return
  const current = store.trip
  const done = generation.run(
    '/api/trips/replan',
    { trip: current, request: request.value.trim(), thinking_effort: thinking.value ? 'high' : 'low' },
  )
  await done
  if (generation.phase === 'done' && generation.result) {
    trips.saveSnapshot(current)
    const next = { ...generation.result, thinking: generation.thinking }
    store.replaceTrip(next)
    trips.upsert(next)
    request.value = ''
  }
}

function undo() {
  if (!store.trip) return
  const restored = trips.undo(store.trip)
  if (restored) store.replaceTrip(restored)
}
</script>

<template>
  <div class="no-print rounded-xl border border-teal-200 bg-teal-50/50 p-3">
    <div class="flex gap-2">
      <input
        v-model="request"
        :disabled="generation.phase === 'running'"
        placeholder="想调整？用一句话告诉 AI，如：第一天别太赶，不去长江索道"
        class="flex-1 rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none disabled:opacity-50"
        @keyup.enter="submit"
      />
      <button
        :disabled="generation.phase === 'running' || !request.trim()"
        class="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
        @click="submit"
      >
        {{ generation.phase === 'running' ? '调整中…' : '调整行程' }}
      </button>
      <button
        v-if="store.trip && trips.snapshotCount(store.trip.id!) > 0"
        class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
        title="恢复到本次调整前"
        @click="undo"
      >
        撤销
      </button>
    </div>
    <label class="mt-2 flex w-fit cursor-pointer items-center gap-1.5 text-xs text-slate-500">
      <input v-model="thinking" type="checkbox" class="h-3.5 w-3.5 accent-teal-600" />
      深度思考（取消=快速档）
    </label>
    <p v-if="generation.phase === 'running'" class="mt-2 h-4 text-xs text-teal-700">
      {{ generation.messages.at(-1) ?? '…' }}
    </p>
    <div v-if="generation.phase === 'running'" class="mt-2">
      <ThinkingPanel :text="generation.thinking" running />
    </div>
    <p v-else-if="generation.phase === 'error'" class="mt-2 text-xs text-red-600">
      {{ generation.error?.message }}
    </p>
  </div>
</template>
