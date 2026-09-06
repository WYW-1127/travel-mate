<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useGenerationStore } from '@/stores/generation'
import { useTripsStore } from '@/stores/trips'

const router = useRouter()
const generation = useGenerationStore()
const trips = useTripsStore()

const latest = computed(() => generation.messages.at(-1) ?? '…')

onMounted(() => {
  // 直接访问本页但没有进行中的任务 → 回首页
  if (generation.phase === 'idle') router.replace({ name: 'home' })
})

// 结果落地：存库并跳详情（phase 响应式监听，不轮询）
watch(
  () => generation.phase,
  (phase) => {
    if (phase === 'done' && generation.result) {
      const saved = trips.upsert(generation.result)
      router.replace({ name: 'trip-detail', params: { id: saved.id! } })
    }
  },
)

function backHome() {
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
