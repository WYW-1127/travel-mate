<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { extractPreferences } from '@/api/preferences'
import { useGenerationStore } from '@/stores/generation'
import { useProfileStore } from '@/stores/profile'

const router = useRouter()
const generation = useGenerationStore()
const profile = useProfileStore()

const form = reactive({
  destination: '',
  days: 3,
  startDate: '',
  adults: 2,
  children: 0,
  budgetLimit: null as number | null,
  preferences: '',
  thinking: true,
})
const error = ref('')

onMounted(() => {
  // 偏好档案预填：可见可改，直接落在输入框里
  if (!form.preferences && profile.items.length) {
    form.preferences = profile.items.join('；')
  }
})

function submit() {
  if (!form.destination.trim()) {
    error.value = '请填写目的地'
    return
  }
  error.value = ''
  if (form.preferences.trim()) {
    // 静默抽取长期偏好入档案，失败不影响生成
    extractPreferences(form.preferences.trim())
      .then((items) => profile.addAll(items))
      .catch(() => {})
  }
  generation.run('/api/trips/generate', {
    destination: form.destination.trim(),
    days: form.days,
    startDate: form.startDate || null,
    travelers: { adults: form.adults, children: form.children },
    budgetLimit: form.budgetLimit,
    preferences: form.preferences,
    thinking_effort: form.thinking ? 'high' : 'low',
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

      <div v-if="profile.items.length" class="flex flex-wrap items-center gap-1.5">
        <span class="text-xs text-slate-400">记住的偏好：</span>
        <span
          v-for="(p, i) in profile.items"
          :key="p"
          class="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
        >
          {{ p }}
          <button type="button" class="text-slate-400 hover:text-red-500" @click="profile.remove(i)">×</button>
        </span>
      </div>

      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

      <label class="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
        <input v-model="form.thinking" type="checkbox" class="h-4 w-4 accent-teal-600" />
        AI 深度思考
        <span class="text-xs text-slate-400">勾选=深度（慢但动线节奏更合理），取消=快速</span>
      </label>

      <button
        type="submit"
        class="w-full rounded-lg bg-teal-600 py-2.5 font-medium text-white transition hover:bg-teal-700 disabled:opacity-50"
      >
        ✨ 生成行程
      </button>
    </form>
  </div>
</template>
