import { createRouter, createWebHashHistory } from 'vue-router'
import { IS_TAURI } from './lib/runtimeEndpoint'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      redirect: '/config',
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('./views/ConfigView.vue'),
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('./views/DashboardView.vue'),
    },
    {
      path: '/offline-flash',
      name: 'offline-flash',
      component: () => import('./views/OfflineFlashView.vue'),
    },
    {
      path: '/online-flash',
      name: 'online-flash',
      component: () => import('./views/OnlineFlashView.vue'),
    },
    {
      path: '/site-agent',
      name: 'site-agent',
      component: () => import('./views/SiteAgentView.vue'),
      beforeEnter: () => IS_TAURI || { name: 'config' },
    },
  ],
})

export default router
