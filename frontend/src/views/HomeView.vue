<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useGenerationStore } from '@/stores/generation'

const router = useRouter()
const generation = useGenerationStore()

const form = reactive({
  destination: '',
  days: 3,
  startDate: '',
  adults: 2,
  children: 0,
  budgetLimit: null as number | null,
  preferences: '',
})
const error = ref('')

function submit() {
  if (!form.destination.trim()) {
    error.value = '请填写目的地'
    return
  }
  error.value = ''
  generation.run('/api/trips/generate', {
    destination: form.destination.trim(),
    days: form.days,
    startDate: form.startDate || null,
    travelers: { adults: form.adults, children: form.children },
    budgetLimit: form.budgetLimit,
    preferences: form.preferences,
  })
  router.push({ name: 'generating' })
}
</script>

<template>
  <div class="mx-auto max-w-2xl">
    <h1 class="mb-1 text-2xl font-bold">规划一次旅行</h1>
    <p class="mb-6 text-sm text-slate-500">告诉我们你的想法，AI 生成逐日行程，可编辑、上地图、算预算。</p>

    <form class="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm" @submit.prevent="submit">
      <div class="grid grid-cols-3 gap-4">
        <label class="col-span-2 block">
          <span class="mb-1 block text-sm font-medium">目的地 *</span>
          <input
            v-model="form.destination"
            placeholder="如：重庆、成都、西安"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-sm font-medium">天数</span>
          <input
            v-model.number="form.days"
            type="number"
            min="1"
            max="15"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </label>
      </div>

      <div class="grid grid-cols-4 gap-4">
        <label class="block">
          <span class="mb-1 block text-sm font-medium">出发日期</span>
          <input
            v-model="form.startDate"
            type="date"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-sm font-medium">成人</span>
          <input
            v-model.number="form.adults"
            type="number"
            min="1"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-sm font-medium">儿童</span>
          <input
            v-model.number="form.children"
            type="number"
            min="0"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-sm font-medium">总预算（元）</span>
          <input
            v-model.number="form.budgetLimit"
            type="number"
            min="0"
            placeholder="选填"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </label>
      </div>

      <label class="block">
        <span class="mb-1 block text-sm font-medium">偏好与要求</span>
        <textarea
          v-model="form.preferences"
          rows="3"
          placeholder="如：带 5 岁孩子，不想太赶，喜欢夜景和美食，不去网红店"
          class="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
        ></textarea>
      </label>

      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

      <button
        type="submit"
        class="w-full rounded-lg bg-teal-600 py-2.5 font-medium text-white transition hover:bg-teal-700 disabled:opacity-50"
      >
        ✨ 生成行程
      </button>
    </form>
  </div>
</template>
