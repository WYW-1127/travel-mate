<script setup lang="ts">
import { computed, ref } from 'vue'

import ActivityCard from '@/components/ActivityCard.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'

const store = useCurrentTripStore()

const props = defineProps<{
  dayIndex: number
  highlightId?: string | null
}>()

const emit = defineEmits<{ select: [activityId: string] }>()

const dragFrom = ref<number | null>(null)

const day = computed(() => store.trip?.days[props.dayIndex])

function onDrop(onto: number) {
  if (dragFrom.value == null) return
  store.moveActivity(props.dayIndex, dragFrom.value, onto)
  dragFrom.value = null
}
</script>

<template>
  <div v-if="day">
    <div class="mb-3 flex items-center justify-between">
      <h3 class="font-bold">
        {{ day.title || `第 ${dayIndex + 1} 天` }}
        <span class="ml-1 text-xs font-normal text-slate-400">拖拽卡片可排序</span>
      </h3>
      <button
        class="no-print rounded-lg border border-slate-200 px-3 py-1 text-sm hover:bg-slate-50"
        @click="store.addActivity(dayIndex)"
      >
        + 加活动
      </button>
    </div>

    <div class="relative space-y-2 before:absolute before:top-2 before:bottom-2 before:left-[7px] before:w-px before:bg-slate-200">
      <ActivityCard
        v-for="(activity, i) in day.activities"
        :key="activity.id ?? i"
        :activity="activity"
        :index="i"
        :highlight="highlightId === activity.id"
        @update="store.updateActivity(dayIndex, i, $event)"
        @remove="store.removeActivity(dayIndex, i)"
        @select="activity.id && emit('select', activity.id)"
        @dragstart="(from) => (dragFrom = from)"
        @drop="onDrop"
      />
      <p v-if="day.activities.length === 0" class="py-8 text-center text-sm text-slate-400">
        这一天还没有活动，点「加活动」或用下方「调整行程」让 AI 重新规划
      </p>
    </div>
  </div>
</template>
