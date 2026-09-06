import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
    {
      path: '/generating',
      name: 'generating',
      component: () => import('@/views/GeneratingView.vue'),
    },
    {
      path: '/trips',
      name: 'my-trips',
      component: () => import('@/views/MyTripsView.vue'),
    },
    {
      path: '/trips/:id',
      name: 'trip-detail',
      component: () => import('@/views/TripDetailView.vue'),
    },
  ],
})

export default router
