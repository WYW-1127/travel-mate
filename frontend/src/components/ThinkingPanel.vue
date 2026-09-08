<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{
  text: string
  running: boolean
  /** 完成后的常驻面板默认折叠，生成进行中默认展开 */
  defaultExpanded?: boolean
  /** 思考耗时毫秒（完成方传入；运行中面板自走计时） */
  durationMs?: number | null
}>()

const expanded = ref(props.defaultExpanded ?? true)
const body = ref<HTMLElement | null>(null)

// 运行中本地走秒；结束后优先用外部传入的精确耗时（从首个 thinking 事件计起）
const startedAt = ref<number | null>(null)
const tick = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

function ensureTimer() {
  if (timer || !props.running) return
  startedAt.value = Date.now()
  timer = setInterval(() => {
    tick.value++
  }, 200)
}

function stopTimer() {
  if (timer) clearInterval(timer)
  timer = null
}

watch(
  () => props.running,
  (running) => {
    if (running) ensureTimer()
    else stopTimer()
  },
  { immediate: true },
)

onUnmounted(stopTimer)

const elapsedMs = computed(() => {
  if (!props.running) return props.durationMs ?? null
  if (startedAt.value === null) return null
  return Date.now() - startedAt.value // tick 仅用于触发响应式刷新
})

function fmt(ms: number | null): string {
  if (ms === null) return ''
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} 秒`
  const m = Math.floor(s / 60)
  return `${m} 分 ${Math.round(s - m * 60)} 秒`
}

// 有新思考内容时保持滚动到底部
watch(
  () => props.text,
  async () => {
    if (!expanded.value) return
    await nextTick()
    body.value?.scrollTo({ top: body.value.scrollHeight })
  },
)
</script>

<template>
  <div v-if="text" class="no-print rounded-lg border border-slate-200 bg-slate-50 text-left">
    <button
      class="flex w-full items-center gap-2 px-3 py-2 text-xs text-slate-500 hover:text-slate-700"
      @click="expanded = !expanded"
    >
      <span>{{ expanded ? '▾' : '▸' }}</span>
      <span>AI 思考过程</span>
      <span v-if="running" class="inline-block h-3 w-3 animate-pulse rounded-full bg-teal-400"></span>
      <span v-if="fmt(elapsedMs)" class="text-slate-400">· {{ fmt(elapsedMs) }}</span>
      <span class="ml-auto text-slate-400">{{ text.length }} 字</span>
    </button>
    <div
      v-show="expanded"
      ref="body"
      class="max-h-48 overflow-y-auto whitespace-pre-wrap border-t border-slate-200 px-3 py-2 font-mono text-xs leading-5 text-slate-500"
      >{{ text }}</div
    >
  </div>
</template>
