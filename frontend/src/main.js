import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import './style.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)

// 注册 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 全局错误处理
app.config.errorHandler = (err, vm, info) => {
  console.error('[Vue Error]', err, info)
  const appEl = document.getElementById('app')
  if (appEl) {
    const errDiv = document.createElement('div')
    errDiv.style.cssText = 'padding:20px;margin:20px;border:2px solid #ef4444;border-radius:12px;background:#fef2f2;color:#dc2626;font-family:monospace;font-size:13px;line-height:1.6;white-space:pre-wrap;word-break:break-all'
    errDiv.innerHTML = `<div style="font-weight:700;margin-bottom:8px">应用错误</div><div>${err?.message || String(err)}</div>`
    appEl.prepend(errDiv)
  }
}

window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason)
  document.body.innerHTML += '<div style="background:#fef2f2;border:2px solid red;padding:16px;margin:16px;border-radius:8px">Unhandled: ' + (event.reason?.message || String(event.reason)) + '</div>'
})
window.onerror = function(msg, url, line, col, err) {
  console.error('[Window Error]', msg, url, line, col, err)
  document.body.innerHTML += '<div style="background:#fef2f2;border:2px solid red;padding:16px;margin:16px;border-radius:8px">Error: ' + msg + '</div>'
}

app.use(ElementPlus)
app.use(router)
app.mount('#app')