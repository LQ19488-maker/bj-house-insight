import { createRouter, createWebHashHistory } from 'vue-router'

// 使用 hash 路由：GitHub Pages 没有 try_files，history 模式刷新会 404。
// hash 模式下 URL 形如 /#/analytics，刷新与分享都不受影响。
const routes = [
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: 'overview',
    component: () => import('@/views/OverviewView.vue'),
    meta: { title: '市场概览', group: '分析' }
  },
  {
    path: '/analytics',
    name: 'analytics',
    component: () => import('@/views/AnalyticsView.vue'),
    meta: { title: '分析看板', group: '分析' }
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('@/views/SearchView.vue'),
    meta: { title: '房源检索', group: '找房' }
  },
  {
    path: '/houses/:id',
    name: 'detail',
    component: () => import('@/views/DetailView.vue'),
    meta: { title: '房源详情', group: '找房' }
  },
  {
    path: '/compare',
    name: 'compare',
    component: () => import('@/views/CompareView.vue'),
    meta: { title: '房源对比', group: '找房' }
  },
  {
    path: '/communities/:id',
    name: 'community',
    component: () => import('@/views/CommunityView.vue'),
    meta: { title: '小区画像', group: '辅助' }
  },
  {
    path: '/valuation',
    name: 'valuation',
    component: () => import('@/views/ValuationView.vue'),
    meta: { title: '估价参考', group: '辅助' }
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { title: '数据管理', group: '管理' }
  },
  { path: '/:pathMatch(.*)*', redirect: '/overview' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.afterEach((to) => {
  document.title = to.meta?.title
    ? `${to.meta.title} · LTQ 的北京二手房行情洞察系统`
    : 'LTQ 的北京二手房行情洞察系统'
})

export default router
