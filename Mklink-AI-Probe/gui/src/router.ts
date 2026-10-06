import { createRouter, createWebHashHistory } from 'vue-router'
import { IS_REMOTE } from './lib/runtimeEndpoint'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/:pathMatch(.*)*', redirect: '/config' },
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
      path: '/remote-service',
      name: 'remote-service',
      component: () => import('./views/SiteAgentView.vue'),
    },
  ],
})

router.beforeEach(to => IS_REMOTE && to.name !== 'dashboard' ? { name: 'dashboard' } : true)

export default router
