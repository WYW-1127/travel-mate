<script setup lang="ts">
import { useTripsStore } from '@/stores/trips'

const trips = useTripsStore()
</script>

<template>
  <div class="mx-auto max-w-3xl">
    <h1 class="mb-6 text-2xl font-bold">我的行程</h1>

    <p v-if="trips.sorted.length === 0" class="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-400">
      还没有行程，去「规划行程」创建一个吧
    </p>

    <ul class="space-y-3">
      <li
        v-for="trip in trips.sorted"
        :key="trip.id"
        class="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
      >
        <RouterLink :to="{ name: 'trip-detail', params: { id: trip.id } }" class="flex-1">
          <div class="font-medium text-teal-700 hover:underline">
            {{ trip.title || trip.destination }}
            <span v-if="(trip.version ?? 1) > 1" class="ml-1 text-xs text-slate-400">v{{ trip.version }}</span>
          </div>
          <div class="mt-1 text-sm text-slate-500">
            {{ trip.destination }} · {{ trip.days.length }} 天 ·
            {{ trip.days.reduce((n, d) => n + d.activities.length, 0) }} 个活动
          </div>
        </RouterLink>
        <div class="no-print flex gap-2 text-sm">
          <button
            class="rounded-lg border border-slate-200 px-3 py-1.5 hover:bg-slate-50"
            @click="trips.duplicate(trip.id!)"
          >
            复制
          </button>
          <button
            class="rounded-lg border border-red-200 px-3 py-1.5 text-red-600 hover:bg-red-50"
            @click="trips.remove(trip.id!)"
          >
            删除
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>
