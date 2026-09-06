<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AMapView, { type MapPoint } from '@/components/AMapView.vue'
import BudgetPanel from '@/components/BudgetPanel.vue'
import DayTimeline from '@/components/DayTimeline.vue'
import ReplanBox from '@/components/ReplanBox.vue'
import ThinkingPanel from '@/components/ThinkingPanel.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'
import { useTripsStore } from '@/stores/trips'

const route = useRoute()
const trips = useTripsStore()
const store = useCurrentTripStore()

const activeDay = ref(0)
const highlightId = ref<string | null>(null)

onMounted(() => {
  const trip = trips.get(route.params.id as string)
  if (trip) store.set(trip)
})

// 编辑自动持久化（共享引用，写回 localStorage）
watch(
  () => store.trip,
  (trip) => {
    if (trip) trips.upsert(trip)
  },
  { deep: true },
)

const mapPoints = computed<MapPoint[]>(() =>
  store
    .dayRoutePoints(activeDay.value)
    .filter((a) => a.location?.longitude != null && a.location?.latitude != null)
    .map((a) => ({
      id: a.id!,
      name: a.name,
      longitude: a.location!.longitude!,
      latitude: a.location!.latitude!,
      type: a.type,
    })),
)

function onMapSelect(id: string) {
  highlightId.value = id
}

function exportJson() {
  if (!store.trip) return
  const blob = new Blob([JSON.stringify(store.trip, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${store.trip.title || store.trip.destination}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function printPdf() {
  window.print()
}
</script>

<template>
  <div v-if="store.trip">
    <div class="no-print mb-4 flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="text-xl font-bold">{{ store.trip.title || store.trip.destination }}</h1>
        <p class="text-sm text-slate-500">
          {{ store.trip.destination }} · {{ store.trip.days.length }} 天 ·
          {{ store.trip.travelers?.adults ?? 1 }} 大人{{ store.trip.travelers?.children ? ` ${store.trip.travelers.children} 小孩` : '' }}
        </p>
      </div>
      <div class="flex gap-2 text-sm">
        <button class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 hover:bg-slate-50" @click="exportJson">
          导出 JSON
        </button>
        <button class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 hover:bg-slate-50" @click="printPdf">
          导出 PDF
        </button>
      </div>
    </div>

    <div v-if="store.trip.warnings?.length" class="no-print mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
      <span v-for="w in store.trip.warnings" :key="w" class="block">⚠️ {{ w }}</span>
    </div>

    <div class="no-print mb-4">
      <ReplanBox />
    </div>

    <!-- 历史思考过程：随行程持久化，折叠可展开 -->
    <div v-if="store.trip.thinking" class="no-print mb-4">
      <ThinkingPanel :text="store.trip.thinking" :running="false" :default-expanded="false" />
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <!-- 左：时间线 -->
      <div class="print-full">
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="(_, i) in store.trip.days"
            :key="i"
            class="rounded-lg px-3 py-1.5 text-sm font-medium transition"
            :class="activeDay === i ? 'bg-teal-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-100'"
            @click="activeDay = i; highlightId = null"
          >
            第 {{ i + 1 }} 天
          </button>
        </div>
        <DayTimeline :day-index="activeDay" :highlight-id="highlightId" @select="onMapSelect" />
      </div>

      <!-- 右：地图 + 预算 -->
      <div class="space-y-4">
        <div class="no-print h-96 lg:sticky lg:top-20">
          <AMapView :points="mapPoints" :highlight-id="highlightId" @select="onMapSelect" />
        </div>
        <BudgetPanel />
      </div>
    </div>
  </div>

  <div v-else class="py-20 text-center text-slate-400">
    行程不存在或已被删除。
    <RouterLink to="/trips" class="text-teal-600 hover:underline">返回我的行程</RouterLink>
  </div>
</template>
