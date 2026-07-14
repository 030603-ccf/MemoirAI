import { createRouter, createWebHistory } from 'vue-router'

import ChatView from '../views/ChatView.vue'
import UploadView from '../views/UploadView.vue'
import SettingsView from '../views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView, meta: { title: '聊天' } },
    { path: '/upload', name: 'upload', component: UploadView, meta: { title: '上传聊天记录' } },
    { path: '/settings', name: 'settings', component: SettingsView, meta: { title: '设置' } },
  ],
})

export default router