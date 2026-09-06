<script setup lang="ts">
import { computed } from 'vue'

import { useCurrentTripStore } from '@/stores/currentTrip'

const store = useCurrentTripStore()

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  meal: '餐饮',
  transport: '交通',
  hotel: '住宿',
  shopping: '购物',
}

const rows = computed(() =>
  Object.entries(store.budgetByType)
    .filter(([, v]) => v > 0)
    .map(([type, total]) => ({ label: TYPE_LABEL[type] ?? type, total })),
)

const usagePercent = computed(() => {
  if (!store.trip?.budgetLimit) return null
  return Math.min(100, Math.round((store.budgetGrandTotal / store.trip.budgetLimit) * 100))
})
</script>

<template>
  <div v-if="store.trip" class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-2 flex items-baseline justify-between">
      <h3 class="font-bold">预算</h3>
      <div class="text-sm text-slate-500">
        人均 ¥{{ store.budgetTotal.toFixed(0) }} × {{ store.headcount }} 人 =
        <span class="text-base font-semibold text-slate-800">¥{{ store.budgetGrandTotal.toFixed(0) }}</span>
      </div>
    </div>

    <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
      <span v-for="row in rows" :key="row.label">{{ row.label }} ¥{{ row.total.toFixed(0) }}</span>
      <span v-if="rows.length === 0" class="text-slate-400">暂无费用项</span>
    </div>

    <div v-if="store.trip.budgetLimit != null" class="mt-3">
      <div class="mb-1 flex justify-between text-xs text-slate-500">
        <span>总预算 ¥{{ store.trip.budgetLimit.toFixed(0) }}</span>
        <span>{{ usagePercent }}%</span>
      </div>
      <div class="h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          class="h-full rounded-full transition-all"
          :class="store.overBudget ? 'bg-red-500' : 'bg-teal-500'"
          :style="{ width: `${usagePercent}%` }"
        ></div>
      </div>
      <p v-if="store.overBudget" class="mt-1 text-xs font-medium text-red-600">
        已超出预算 ¥{{ (store.budgetGrandTotal - store.trip.budgetLimit).toFixed(0) }}
      </p>
    </div>
  </div>
</template>
