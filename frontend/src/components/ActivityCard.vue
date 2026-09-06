<script setup lang="ts">
import { computed } from 'vue'

import type { Activity } from '@/types/trip'

const props = defineProps<{
  activity: Activity
  index: number
  highlight?: boolean
}>()

const emit = defineEmits<{
  update: [patch: Partial<Activity>]
  remove: []
  select: []
  dragstart: [index: number]
  drop: [index: number]
}>()

const editing = defineModel<boolean>('editing', { default: false })

const TYPE_META: Record<Activity['type'], { label: string; dot: string }> = {
  attraction: { label: '景点', dot: 'bg-teal-500' },
  meal: { label: '餐饮', dot: 'bg-orange-500' },
  transport: { label: '交通', dot: 'bg-slate-400' },
  hotel: { label: '住宿', dot: 'bg-violet-500' },
  shopping: { label: '购物', dot: 'bg-pink-500' },
}

const meta = computed(() => TYPE_META[props.activity.type])
const unresolved = computed(() => props.activity.location != null && !props.activity.location.resolved)

function onDrop() {
  emit('drop', props.index)
}
</script>

<template>
  <div
    class="group relative rounded-lg border bg-white p-3 transition"
    :class="highlight ? 'border-teal-500 ring-2 ring-teal-200' : 'border-slate-200'"
    draggable="true"
    @dragstart="emit('dragstart', index)"
    @dragover.prevent
    @drop="onDrop"
    @click="emit('select')"
  >
    <span class="absolute top-4 left-1.5 h-2.5 w-2.5 rounded-full" :class="meta.dot"></span>

    <div v-if="!editing" class="flex items-start justify-between gap-2 pl-4">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <span class="font-mono text-xs text-slate-400">
            {{ activity.startTime ?? '--:--' }}-{{ activity.endTime ?? '--:--' }}
          </span>
          <span class="rounded bg-slate-100 px-1.5 text-xs text-slate-500">{{ meta.label }}</span>
          <span v-if="unresolved" class="rounded bg-amber-100 px-1.5 text-xs text-amber-600">未定位</span>
        </div>
        <div class="mt-0.5 truncate font-medium">{{ activity.name }}</div>
        <div v-if="activity.notes" class="mt-0.5 text-xs leading-relaxed text-slate-400">{{ activity.notes }}</div>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <span class="text-sm text-slate-600">¥{{ activity.cost ?? 0 }}</span>
        <button
          class="no-print text-xs text-slate-400 opacity-0 transition group-hover:opacity-100 hover:text-teal-600"
          @click.stop="editing = true"
        >
          编辑
        </button>
        <button
          class="no-print text-xs text-slate-400 opacity-0 transition group-hover:opacity-100 hover:text-red-600"
          @click.stop="emit('remove')"
        >
          删除
        </button>
      </div>
    </div>

    <!-- 行内编辑 -->
    <div v-else class="no-print space-y-2 pl-4" @click.stop>
      <div class="grid grid-cols-4 gap-2">
        <input
          :value="activity.startTime"
          type="time"
          class="rounded border border-slate-300 px-2 py-1 text-sm"
          @input="emit('update', { startTime: ($event.target as HTMLInputElement).value || null })"
        />
        <input
          :value="activity.endTime"
          type="time"
          class="rounded border border-slate-300 px-2 py-1 text-sm"
          @input="emit('update', { endTime: ($event.target as HTMLInputElement).value || null })"
        />
        <select
          :value="activity.type"
          class="col-span-2 rounded border border-slate-300 px-2 py-1 text-sm"
          @change="emit('update', { type: ($event.target as HTMLSelectElement).value as Activity['type'] })"
        >
          <option v-for="(m, t) in TYPE_META" :key="t" :value="t">{{ m.label }}</option>
        </select>
      </div>
      <input
        :value="activity.name"
        class="w-full rounded border border-slate-300 px-2 py-1 text-sm"
        placeholder="名称"
        @input="emit('update', { name: ($event.target as HTMLInputElement).value })"
      />
      <textarea
        :value="activity.notes"
        rows="2"
        class="w-full resize-y rounded border border-slate-300 px-2 py-1 text-sm leading-relaxed"
        placeholder="备注（建议、预约提示、路线要点等）"
        @input="emit('update', { notes: ($event.target as HTMLTextAreaElement).value })"
      />
      <div class="flex items-center gap-2">
        <input
          :value="activity.cost"
          type="number"
          min="0"
          class="w-24 rounded border border-slate-300 px-2 py-1 text-sm"
          placeholder="人均¥"
          @input="emit('update', { cost: Number(($event.target as HTMLInputElement).value) || 0 })"
        />
        <button class="ml-auto rounded bg-teal-600 px-3 py-1 text-sm text-white" @click="editing = false">完成</button>
      </div>
    </div>
  </div>
</template>
