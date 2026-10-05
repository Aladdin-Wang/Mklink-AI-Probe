import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/remote-dashboard/:windowId', name: 'remote-dashboard', component: () => import('./views/RemoteDashboardView.vue') },
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
      path: '/vofa',
      name: 'vofa',
      component: () => import('./views/VofaView.vue'),
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
      path: '/remote-service',
      name: 'remote-service',
      component: () => import('./views/SiteAgentView.vue'),
    },
  ],
})

export default router
