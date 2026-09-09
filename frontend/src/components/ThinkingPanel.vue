<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{
  text: string
  running: boolean
  /** 完成后的常驻面板默认折叠，生成进行中默认展开 */
  defaultExpanded?: boolean
  /** 首个思考事件的服务端时刻（epoch ms）；断线重放时凭它还原真实耗时 */
  startTs?: number | null
}>()

const expanded = ref(props.defaultExpanded ?? true)
const body = ref<HTMLElement | null>(null)

// 计时：运行中的面板从挂载起走秒，running 结束时冻结显示；
// 历史/常驻面板（挂载即非 running）不显示时长
const startedAt = Date.now()
const frozenMs = ref<number | null>(null)
const tick = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

if (props.running) {
  timer = setInterval(() => {
    tick.value++
  }, 200)
}

watch(
  () => props.running,
  (running) => {
    if (!running && timer) {
      clearInterval(timer)
      timer = null
      frozenMs.value = Date.now() - baseTs()
    }
  },
)
onUnmounted(() => timer && clearInterval(timer))

const baseTs = () => props.startTs ?? startedAt
const elapsedMs = computed(() =>
  props.running ? Date.now() - baseTs() : frozenMs.value,
)

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
