<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  text: string
  running: boolean
  /** 完成后的常驻面板默认折叠，生成进行中默认展开 */
  defaultExpanded?: boolean
}>()

const expanded = ref(props.defaultExpanded ?? true)
const body = ref<HTMLElement | null>(null)

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
