<script setup lang="ts">
import AMapLoader from '@amap/amap-jsapi-loader'
import { onMounted, onUnmounted, ref, watch } from 'vue'

export interface MapPoint {
  id: string
  name: string
  longitude: number
  latitude: number
  type: string
}

const props = defineProps<{
  points: MapPoint[]
  highlightId?: string | null
}>()

const emit = defineEmits<{ select: [id: string] }>()

const TYPE_COLOR: Record<string, string> = {
  attraction: '#14b8a6',
  meal: '#f97316',
  transport: '#94a3b8',
  hotel: '#8b5cf6',
  shopping: '#ec4899',
}

const container = ref<HTMLElement | null>(null)
const degraded = ref<string | null>(null)

let AMap: any = null
let map: any = null
let overlays: any[] = []

onMounted(async () => {
  const key = import.meta.env.VITE_AMAP_JS_KEY
  if (!key) {
    degraded.value = '未配置 VITE_AMAP_JS_KEY（参考 frontend/.env.example），地图不可用，时间线功能不受影响。'
    return
  }
  if (import.meta.env.VITE_AMAP_SECURITY_CODE) {
    ;(window as any)._AMapSecurityConfig = { securityJsCode: import.meta.env.VITE_AMAP_SECURITY_CODE }
  }
  try {
    AMap = await AMapLoader.load({ key, version: '2.0' })
    map = new AMap.Map(container.value, { viewMode: '2D', zoom: 12 })
    redraw()
  } catch (e) {
    degraded.value = `高德地图加载失败（${e instanceof Error ? e.message : '未知错误'}），已降级为纯时间线视图。`
  }
})

onUnmounted(() => {
  map?.destroy()
})

function redraw() {
  if (!map || !AMap) return
  map.remove(overlays)
  overlays = []

  for (const p of props.points) {
    const marker = new AMap.Marker({
      position: [p.longitude, p.latitude],
      title: p.name,
      content: `<div style="width:14px;height:14px;border-radius:50%;background:${
        TYPE_COLOR[p.type] ?? '#14b8a6'
      };border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);cursor:pointer"></div>`,
    })
    marker.on('click', () => emit('select', p.id))
    overlays.push(marker)

    if (p.id === props.highlightId) {
      marker.setzIndex(120)
      map.setCenter([p.longitude, p.latitude])
    }
  }

  const coords = props.points.map((p) => [p.longitude, p.latitude])
  if (coords.length >= 2) {
    overlays.push(
      new AMap.Polyline({
        path: coords,
        strokeColor: '#14b8a6',
        strokeWeight: 3,
        strokeOpacity: 0.7,
        showDir: true,
      }),
    )
  }
  map.add(overlays)
  if (coords.length >= 2) map.setFitView(overlays, false, [60, 60, 60, 60])
}

watch(() => props.points, redraw, { deep: true })
watch(
  () => props.highlightId,
  (id) => {
    const p = props.points.find((pt) => pt.id === id)
    if (p && map) map.setCenter([p.longitude, p.latitude])
  },
)
</script>

<template>
  <div class="relative h-full w-full overflow-hidden rounded-xl border border-slate-200">
    <div v-show="!degraded" ref="container" class="h-full w-full"></div>
    <div v-if="degraded" class="flex h-full items-center justify-center bg-slate-100 p-6 text-center text-sm text-slate-500">
      {{ degraded }}
    </div>
  </div>
</template>
