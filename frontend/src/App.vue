<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-800">
    <header class="no-print sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
      <nav class="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <RouterLink to="/" class="text-lg font-bold text-teal-700">🧭 TravelMate</RouterLink>
        <div class="flex gap-4 text-sm">
          <RouterLink to="/" class="hover:text-teal-600">规划行程</RouterLink>
          <RouterLink to="/trips" class="hover:text-teal-600">我的行程</RouterLink>
        </div>
      </nav>
    </header>
    <main class="mx-auto max-w-6xl px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
