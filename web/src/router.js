import { createRouter, createWebHashHistory } from 'vue-router'
import HomePage from './pages/HomePage.vue'
import UploadPage from './pages/UploadPage.vue'
import DiffPage from './pages/DiffPage.vue'
import ReportPage from './pages/ReportPage.vue'
import EvalPage from './pages/EvalPage.vue'
import { task } from './state/session.js'

/**
 * hash 模式：静态托管（Cloudflare Pages）没有 history rewrite 能力，
 * 直接刷新 /diff 会 404，hash 模式 URL 不经过服务端，最稳。
 *
 * meta.order 只承载纸张层叠的前进/后退方向（页签排列与文案在 App.vue 的 PAGES）；
 * meta.label 目前无人读取，改导航请改 App.vue 的 PAGES。
 * 评测页不在导航里，保留 order 3 只为了让「首页 → 评测」算前进、「评测 → 首页」算后退。
 */
const routes = [
  { path: '/', name: 'home', component: HomePage, meta: { order: -1, label: '首页' } },
  {
    path: '/upload',
    name: 'upload',
    component: UploadPage,
    meta: { order: 0, label: '上传' },
  },
  {
    path: '/diff',
    name: 'diff',
    component: DiffPage,
    meta: { order: 1, label: '差异' },
  },
  {
    path: '/report',
    name: 'report',
    component: ReportPage,
    meta: { order: 2, label: '报告' },
  },
  {
    path: '/eval',
    name: 'eval',
    component: EvalPage,
    meta: { order: 3, label: '评测' },
  },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

/**
 * 第二道防线：tab 禁用只是 UI 层拦截，直接改 hash 仍能进来。
 * 没有任务时差异页和报告页没有内容可显示，守卫统一重定向回上传页。
 */
router.beforeEach((to) => {
  if ((to.name === 'diff' || to.name === 'report') && !task.value) {
    return { name: 'upload' }
  }
})
