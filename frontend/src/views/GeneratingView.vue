<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import { postJson } from '@/api/client'
import ThinkingPanel from '@/components/ThinkingPanel.vue'
import { useGenerationStore } from '@/stores/generation'
import { useTripsStore } from '@/stores/trips'
import { clearGenMarker, loadGenMarker } from '@/utils/genMarker'

const router = useRouter()
const generation = useGenerationStore()
const trips = useTripsStore()

const latest = computed(() => generation.messages.at(-1) ?? '…')

onMounted(() => {
  if (generation.phase !== 'idle') return
  const marker = loadGenMarker()
  if (marker) {
    // 断线重连：上次生成被刷新/关闭打断，重放后台任务的事件流领回行程
    generation.run(`/api/trips/gen-jobs/${marker.id}/replay`, {})
    return
  }
  router.replace({ name: 'home' })
})

// 结果落地：带上思考文本存库并跳详情（phase 响应式监听，不轮询）
watch(
  () => generation.phase,
  (phase) => {
    if (phase === 'done' && generation.result) {
      clearGenMarker()
      const saved = trips.upsert({
        ...generation.result,
        thinking: generation.thinking,
        thinkingMs: generation.thinkingMs,
      })
      router.replace({ name: 'trip-detail', params: { id: saved.id! } })
    }
    // error 时不清标记：刷新导致的断连里任务还在后台跑，回本页可重放重连；
    // 标记由 15 分钟自然过期兜底
  },
)

function backHome() {
  const marker = loadGenMarker()
  if (marker) {
    // 真正取消后台任务（释放 GLM/配额），失败无声
    postJson(`/api/trips/gen-jobs/${marker.id}/cancel`, {}).catch(() => {})
    clearGenMarker()
  }
  generation.stop?.()
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="mx-auto max-w-xl py-16 text-center">
    <template v-if="generation.phase === 'running'">
      <div class="mx-auto mb-6 h-12 w-12 animate-spin rounded-full border-4 border-teal-200 border-t-teal-600"></div>
      <h2 class="mb-2 text-xl font-bold">正在为你规划行程…</h2>
      <p class="h-5 text-slate-500">{{ latest }}</p>
      <div class="mx-auto mt-6 max-w-xl">
        <ThinkingPanel :text="generation.thinking" running />
      </div>
      <button class="mt-8 text-sm text-slate-400 hover:text-slate-600" @click="backHome">取消，返回</button>
    </template>

    <template v-else-if="generation.phase === 'error'">
      <div class="mb-4 text-4xl">😕</div>
      <h2 class="mb-2 text-xl font-bold text-red-600">生成失败</h2>
      <p class="mx-auto mb-6 max-w-sm text-sm text-slate-500">{{ generation.error?.message }}</p>
      <button class="rounded-lg bg-teal-600 px-6 py-2 text-white hover:bg-teal-700" @click="backHome">
        返回重新填写
      </button>
    </template>

    <!-- done 状态在 watch 中立即跳转，此处仅兜底 -->
    <template v-else>
      <div class="mx-auto mb-6 h-12 w-12 animate-spin rounded-full border-4 border-teal-200 border-t-teal-600"></div>
      <p class="text-slate-500">即将打开行程…</p>
    </template>
  </div>
</template>
