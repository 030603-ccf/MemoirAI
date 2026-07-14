<template>
  <el-container class="app-layout">
    <el-header class="app-header">
      <div class="header-inner">
        <div class="brand">
          <div class="brand-logo">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
              <defs>
                <linearGradient id="logoGrad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#a5b4fc"/>
                  <stop offset="1" stop-color="#6366f1"/>
                </linearGradient>
              </defs>
              <path d="M16 3l11 5v8c0 7.5-5.5 12.5-11 13-5.5-.5-11-5.5-11-13V8l11-5z"
                    fill="url(#logoGrad)"/>
              <path d="M11 16l3.5 3.5L22 12" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            </svg>
          </div>
          <div class="brand-text">
            <div class="brand-title">数字纪念</div>
            <div class="brand-subtitle">Memorial Chat · 数据本地存储</div>
          </div>
        </div>

        <el-menu
          mode="horizontal"
          :default-active="$route.path"
          router
          class="nav-menu"
        >
          <el-menu-item index="/" :route="{ name: 'chat' }">
            <el-icon><ChatLineRound /></el-icon>
            <span>对话</span>
          </el-menu-item>
          <el-menu-item index="/upload" :route="{ name: 'upload' }">
            <el-icon><Folder /></el-icon>
            <span>记忆</span>
          </el-menu-item>
          <el-menu-item index="/settings" :route="{ name: 'settings' }">
            <el-icon><Setting /></el-icon>
            <span>设置</span>
          </el-menu-item>
        </el-menu>

        <div class="header-right">
          <el-tooltip content="数据全部本地存储，不上传服务器" placement="bottom">
            <div class="badge-local">
              <el-icon><Lock /></el-icon>
              <span>本地</span>
            </div>
          </el-tooltip>
        </div>
      </div>
    </el-header>

    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { ChatLineRound, Setting, Folder, Lock } from '@element-plus/icons-vue'
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.app-header {
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border-soft);
  padding: 0;
  height: 68px !important;
  position: sticky;
  top: 0;
  z-index: 100;
}

.app-header::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--primary-light), transparent);
  opacity: 0.3;
}

.header-inner {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 28px;
  max-width: 1200px;
  margin: 0 auto;
  gap: 32px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--primary-soft) 0%, #ede9fe 100%);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
  transition: box-shadow 0.2s;
}
.brand:hover .brand-logo {
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.25);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.5px;
}

.brand-subtitle {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
  margin-top: 1px;
}

.nav-menu {
  flex: 1;
  background: transparent !important;
  border-bottom: none !important;
}

.nav-menu :deep(.el-menu-item) {
  height: 68px !important;
  line-height: 68px !important;
  color: var(--text-secondary) !important;
  font-weight: 500;
  padding: 0 16px !important;
  margin: 0 4px;
  border-radius: 10px !important;
  transition: all 0.2s ease;
  position: relative;
}

.nav-menu :deep(.el-menu-item:hover) {
  background: var(--primary-soft) !important;
  color: var(--primary) !important;
}

.nav-menu :deep(.el-menu-item.is-active) {
  background: var(--primary-soft) !important;
  color: var(--primary) !important;
  font-weight: 600;
}

.nav-menu :deep(.el-menu-item.is-active::after) {
  content: '';
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  width: 16px;
  height: 3px;
  background: var(--primary);
  border-radius: 2px;
}

.nav-menu :deep(.el-menu-item .el-icon) {
  margin-right: 6px;
  font-size: 16px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.badge-local {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  background: linear-gradient(135deg, #ecfdf5 0%, #f0fdf4 100%);
  color: #047857;
  border: 1px solid #d1fae5;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: help;
}

.badge-local .el-icon {
  font-size: 13px;
}

.app-main {
  padding: 28px;
  background:
    radial-gradient(ellipse 80% 60% at 50% -20%, rgba(99, 102, 241, 0.03) 0%, transparent 60%),
    var(--bg);
  min-height: calc(100vh - 68px);
}

@media (max-width: 640px) {
  .app-main { padding: 16px; }
  .header-inner { padding: 0 16px; gap: 16px; }
}

/* 页面切换动画 */
.fade-enter-active,
.fade-leave-active {
  transition: all 0.25s ease;
}
.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>