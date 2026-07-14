<template>
  <div class="chat-container">
    <div class="chat-layout">
      <!-- 主对话区 -->
      <el-card class="chat-card" shadow="never">
        <template #header>
          <div class="card-header">
            <div class="header-left">
              <div class="avatar-circle" :class="{ online: modelReady }">
                {{ displayName.charAt(0) }}
                <span v-if="modelReady" class="online-dot"></span>
              </div>
              <div class="header-info">
                <div class="display-name">{{ displayName }}</div>
                <div class="status-line">
                  <span class="status-dot" :class="{ online: modelReady }"></span>
                  <span>{{ modelReady ? '就绪 · 可以对话' : '正在准备…' }}</span>
                  <span v-if="modelId" class="model-tag">· {{ modelId }}</span>
                </div>
              </div>
            </div>
            <div class="header-right">
              <!-- 会话管理 -->
              <el-dropdown trigger="click" @command="handleSessionCommand" class="session-dropdown">
                <el-button text size="small">
                  <el-icon><ChatLineRound /></el-icon>
                  {{ currentSessionTitle }}
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="new">
                      <el-icon><Plus /></el-icon> 新建会话
                    </el-dropdown-item>
                    <el-dropdown-item divided v-if="sessions.length > 0">
                      <span style="color:#999;font-size:11px">历史会话</span>
                    </el-dropdown-item>
                    <el-dropdown-item
                      v-for="s in sessions"
                      :key="s.id"
                      :command="s.id"
                      :class="{ active: s.id === currentSessionId }"
                    >
                      <div class="session-item">
                        <div class="session-item-top">
                          <span class="session-item-title">{{ s.title || '未命名' }}</span>
                          <span class="session-item-count">{{ s.turn_count }}条</span>
                        </div>
                        <div class="session-item-bottom">
                          <span class="session-item-time" :title="s.created_at">
                            创建 {{ formatTime(s.created_at) }}
                          </span>
                          <span class="session-item-time" :title="s.updated_at" v-if="s.updated_at !== s.created_at">
                            最后 {{ formatTime(s.updated_at) }}
                          </span>
                          <el-button
                            text
                            size="small"
                            class="session-rename-btn"
                            @click.stop="openRename(s)"
                          >
                            <el-icon><Edit /></el-icon>
                          </el-button>
                        </div>
                      </div>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>

              <el-tag v-if="useRag" type="success" size="small" effect="light" round>
                <el-icon><MagicStick /></el-icon> 智能回复
              </el-tag>
              <el-tag v-else type="info" size="small" effect="plain" round>
                普通回复
              </el-tag>
              <el-button text circle @click="clearMessages" :disabled="!messages.length" title="清空对话（同时清本地记录）">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </template>

        <!-- 消息区 -->
        <div class="messages" ref="messagesEl">
          <!-- 空状态 -->
          <div v-if="messages.length === 0 && !loading" class="empty-state">
            <div class="empty-illustration">
              <svg width="120" height="120" viewBox="0 0 120 120" fill="none">
                <circle cx="60" cy="60" r="56" fill="#eef2ff"/>
                <path d="M30 50 Q60 30 90 50 Q90 70 60 80 Q30 70 30 50Z" fill="#c7d2fe"/>
                <circle cx="48" cy="58" r="3" fill="#6366f1"/>
                <circle cx="72" cy="58" r="3" fill="#6366f1"/>
                <path d="M48 70 Q60 76 72 70" stroke="#6366f1" stroke-width="2.5" fill="none" stroke-linecap="round"/>
              </svg>
            </div>
            <h2 class="empty-title">向 {{ displayName }} 发送第一条消息</h2>
            <p class="empty-subtitle">{{ emptyHint }}</p>
            <div class="empty-suggestions">
              <el-button
                v-for="(s, i) in suggestions"
                :key="i"
                size="small"
                round
                @click="useSuggestion(s)"
              >
                {{ s }}
              </el-button>
            </div>
          </div>

          <!-- 消息列表 -->
          <transition-group name="msg" tag="div">
            <div
              v-for="(m, i) in messages"
              :key="i"
              :class="['message', m.role]"
            >
              <div class="avatar-mini">
                {{ m.role === 'user' ? '我' : displayName.charAt(0) }}
              </div>
              <div class="bubble-wrap">
                <div class="bubble">{{ stripStyle(m.content) }}</div>
                <!-- Guard 状态标签 -->
                <div v-if="m.role === 'assistant' && m._guardInfo" class="guard-status">
                  <el-tag
                    v-if="m._guardInfo.status === 'blocked'"
                    type="warning"
                    size="small"
                    effect="light"
                    round
                    class="guard-tag"
                  >
                    <el-icon><Warning /></el-icon>
                    保守回复（检测到可能编造）
                  </el-tag>
                  <el-tag
                    v-else-if="m._guardInfo.status === 'warning'"
                    type="info"
                    size="small"
                    effect="light"
                    round
                    class="guard-tag"
                  >
                    <el-icon><InfoFilled /></el-icon>
                    部分验证
                  </el-tag>
                  <el-tag
                    v-else
                    type="success"
                    size="small"
                    effect="light"
                    round
                    class="guard-tag"
                  >
                    <el-icon><Check /></el-icon>
                    内容已验证
                  </el-tag>
                </div>
                <!-- RAG 引用展示 -->
                <div v-if="m.role === 'assistant' && m._ragRefs && m._ragRefs.length" class="rag-refs">
                  <el-collapse class="rag-collapse">
                    <el-collapse-item title="回答来源（真实聊天记录）" name="1">
                      <div
                        v-for="(ref, ri) in m._ragRefs"
                        :key="ri"
                        class="rag-ref-item"
                      >
                        <span class="rag-ref-role">[{{ ref.role }}]</span>
                        <span class="rag-ref-text">{{ ref.text_preview }}</span>
                        <span class="rag-ref-score">{{ (ref.score * 100).toFixed(0) }}% 匹配</span>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </div>
                <div v-if="m.role === 'assistant' && m.content && !m.content.startsWith('⚠️')" class="bubble-actions">
                  <button class="action-btn" :class="{ playing: playingIdx === i }" @click="togglePlay(i, m.content)" :title="playingIdx === i ? '停止' : '播放'">
                    <span v-if="playingIdx === i">
                      <svg width="14" height="14" viewBox="0 0 14 14"><rect x="2" y="2" width="3" height="10" rx="1" fill="currentColor"/><rect x="9" y="2" width="3" height="10" rx="1" fill="currentColor"/></svg>
                    </span>
                    <span v-else>
                      <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3 2 L11 7 L3 12 Z" fill="currentColor"/></svg>
                    </span>
                  </button>
                </div>
              </div>
            </div>
          </transition-group>

          <!-- 加载指示 -->
          <div v-if="loading" class="message assistant typing-msg">
            <div class="avatar-mini">{{ displayName.charAt(0) }}</div>
            <div class="bubble-wrap">
              <div class="bubble typing">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="input-area">
          <el-input
            v-model="userInput"
            type="textarea"
            :rows="2"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="说点什么…（Enter 发送，Shift+Enter 换行）"
            @keydown.enter.exact.prevent="sendMessage"
            :disabled="loading"
            class="chat-input"
          />
          <div class="input-actions">
            <el-checkbox v-model="useRag" class="rag-toggle">
              <span class="rag-label">
                <el-icon><MagicStick /></el-icon> 记忆检索
              </span>
            </el-checkbox>

            <el-tooltip
              placement="top"
              raw-content
              content="收到 AI 回复后自动调用 TTS API 合成语音并缓存到后端，点击播放时瞬间响应（缓存命中 ~100ms）。<br><br>⚠ 每条 AI 回复都会消耗 1 次 TTS API 调用，Token 消耗量会有增加。"
            >
              <el-checkbox v-model="preSynthesize" class="rag-toggle">
                <span class="rag-label">
                  <el-icon><Headset /></el-icon> 预合成
                </span>
              </el-checkbox>
            </el-tooltip>

            <el-select
              v-if="voiceSamples.length"
              v-model="ttsVoiceId"
              @change="onVoiceIdChange"
              size="small"
              class="voice-select"
              placeholder="使用声音样本"
              clearable
            >
              <el-option
                v-for="s in voiceSamples"
                :key="s.voice_id"
                :label="s.voice_id"
                :value="s.voice_id"
              >
                <span style="float:left">{{ s.voice_id }}</span>
                <span style="float:right; color:#9ca3af; font-size:11px; margin-left:8px;">
                  {{ s.features?.duration?.toFixed(1) || '?' }}s
                </span>
              </el-option>
            </el-select>

            <el-button
              class="send-btn"
              type="primary"
              :loading="loading"
              :disabled="!userInput.trim()"
              @click="sendMessage"
              round
            >
              <el-icon v-if="!loading"><Promotion /></el-icon>
              <span>{{ loading ? '思考中…' : '发送' }}</span>
            </el-button>
          </div>
        </div>
      </el-card>
    </div>
  </div>

  <!-- 重命名对话框 -->
  <el-dialog v-model="renameDialogVisible" title="重命名会话" width="360px" :close-on-click-modal="false">
    <el-input v-model="renameSessionTitle" placeholder="输入新名称" maxlength="50" @keyup.enter="doRename" />
    <template #footer>
      <el-button @click="renameDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="doRename">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, onMounted, nextTick, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatLineRound, Loading, VideoPlay, VideoPause,
  Delete, MagicStick, Promotion, Folder, Lock, Headset,
  Warning, InfoFilled, Check, Plus, ArrowDown, Edit
} from '@element-plus/icons-vue'
import { sendChat, getStatus, getProfile, getSettings, synthesizeSpeech, listVoiceSamples, createSession, listSessions, getSession, deleteSession, renameSession } from '../api'

const messages = ref([])
const userInput = ref('')
const loading = ref(false)
const useRag = ref(true)
const preSynthesize = ref(false)  // 预合成：收到回复后自动调 TTS，让缓存提前就绪
const fallbackWarned = ref(false)
const modelReady = ref(false)
const messagesEl = ref(null)

// 当前已恢复的历史条数（用于 UI 提示）
const historyCount = ref(0)

// 重命名对话框
const renameDialogVisible = ref(false)
const renameSessionId = ref('')
const renameSessionTitle = ref('')

function formatTime(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now - d
  const mins = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return mins + '分钟前'
  if (hours < 24) return hours + '小时前'
  if (days < 7) return days + '天前'
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  if (y === now.getFullYear()) return m + '/' + day
  return y + '/' + m + '/' + day
}
const CHAT_HISTORY_KEY = 'memorial_chat_history_v1'
const CHAT_META_KEY = 'memorial_chat_meta_v1'
const MAX_HISTORY = 500  // 最多保留条数（防止 localStorage 撑爆）

function loadHistory() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    // 校验：只接受 user/assistant，过滤空 content
    return arr
      .filter(m => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
      .map(m => ({ role: m.role, content: m.content }))
  } catch (e) {
    console.warn('[history] load failed:', e)
    return []
  }
}

function saveHistory() {
  try {
    // 只保留 role+content（不存运行时字段如 __fallback），并截断到 MAX
    const list = messages.value
      .filter(m => m && (m.role === 'user' || m.role === 'assistant') && m.content)
      .map(m => ({ role: m.role, content: m.content }))
      .slice(-MAX_HISTORY)
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(list))
    localStorage.setItem(CHAT_META_KEY, JSON.stringify({
      count: list.length,
      updated_at: new Date().toISOString(),
    }))
  } catch (e) {
    // localStorage 可能满了（5MB 上限）。给用户一次提示，不阻塞使用
    if (e?.name === 'QuotaExceededError' || /quota/i.test(e?.message || '')) {
      ElMessage.warning('本地存储已满（5MB），最早的几条聊天记录不会被保存')
    } else {
      console.warn('[history] save failed:', e)
    }
  }
}

function clearHistoryStorage() {
  try {
    localStorage.removeItem(CHAT_HISTORY_KEY)
    localStorage.removeItem(CHAT_META_KEY)
  } catch (e) {}
}
const displayName = ref('TA')
const modelId = ref('')

// TTS
const playingIdx = ref(-1)
const currentAudio = ref(null)
const ttsVoiceId = ref(localStorage.getItem('ttsVoiceId') || '')
const voiceSamples = ref([])
const ttsEngine = ref('edge')

// 会话管理（Agent Memory 三层架构）
const sessions = ref([])
const currentSessionId = ref(localStorage.getItem('memorial_current_session') || '')
const sessionDrawerVisible = ref(false)
const SESSION_STORAGE_KEY = 'memorial_chat_sessions_v1'

const currentSessionTitle = computed(() => {
  if (!currentSessionId.value) return '新对话'
  const s = sessions.value.find(s => s.id === currentSessionId.value)
  return s ? (s.title || '未命名') : '对话中'
})

async function handleSessionCommand(cmd) {
  if (cmd === 'new') {
    await createNewSession()
  } else {
    await switchSession(cmd)
  }
}

// 提示语
const suggestions = [
  '今天怎么样？',
  '分享一段回忆吧',
  '我想你了',
]
const emptyHint = ref('基于逝者的聊天记录与记忆检索，还原其说话风格进行对话。')

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) {
    messagesEl.value.scrollTo({
      top: messagesEl.value.scrollHeight,
      behavior: 'smooth',
    })
  }
}

async function init() {
  // 1. 加载逝者画像
  try {
    const profile = await getProfile()
    displayName.value = profile.self_reference || profile.name || 'TA'
    emptyHint.value = `基于逝者「${displayName.value}」的聊天记录，还原其说话风格与你对话。`
  } catch (e) {
    displayName.value = 'TA'
    emptyHint.value = `请先前往「记忆」页面上传聊天截图，完成 OCR 识别后即可开始对话。`
  }

  // 2. 检查后端状态
  try {
    const status = await getStatus()
    if (status.ready) {
      modelReady.value = true
      modelId.value = status.model || ''
    } else {
      ElMessage.warning(status.message || '系统尚未就绪，请前往「记忆」页面完成 OCR，或在「设置」页面配置 API key。')
    }
  } catch (e) {
    ElMessage.warning('无法连接后端服务，请确认服务器已启动。')
  }

  // 3. 加载会话列表（Agent Memory）
  try {
    await refreshSessions()
  } catch (e) {
    console.warn('[session] load sessions failed:', e)
  }

  // 4. 如果有当前会话，加载其历史
  if (currentSessionId.value) {
    try {
      const sessionData = await getSession(currentSessionId.value)
      if (sessionData && sessionData.turns) {
        messages.value = sessionData.turns.map(t => ({
          role: t.role,
          content: t.content,
        }))
        historyCount.value = messages.value.length
      }
    } catch (e) {
      console.warn('[session] load current session failed:', e)
      // 如果会话加载失败，创建新会话
      currentSessionId.value = ''
      localStorage.removeItem('memorial_current_session')
    }
  }

  // 5. 如果没有会话，也没有本地缓存，显示空状态
  if (!messages.value.length && !currentSessionId.value) {
    // 保持空状态，等用户发送第一条消息时自动创建会话
  }

  // 6. 加载声音样本
  try {
    voiceSamples.value = await listVoiceSamples()
  } catch (e) {}

  // 7. 加载 TTS 引擎设置
  try {
    const s = await getSettings()
    ttsEngine.value = s.tts_engine || 'edge'
  } catch (e) {}
}

async function refreshSessions() {
  try {
    sessions.value = await listSessions()
  } catch (e) {
    console.warn('[session] refresh failed:', e)
  }
}

async function createNewSession() {
  try {
    const session = await createSession('')
    currentSessionId.value = session.id
    localStorage.setItem('memorial_current_session', session.id)
    messages.value = []
    clearHistoryStorage()
    await refreshSessions()
    ElMessage.success('新对话已开始')
  } catch (e) {
    ElMessage.error('创建会话失败：' + (e?.message || e))
  }
}

async function switchSession(sessionId) {
  if (sessionId === currentSessionId.value) return
  try {
    const sessionData = await getSession(sessionId)
    if (sessionData && sessionData.turns) {
      currentSessionId.value = sessionId
      localStorage.setItem('memorial_current_session', sessionId)
      messages.value = sessionData.turns.map(t => ({
        role: t.role,
        content: t.content,
      }))
      historyCount.value = messages.value.length
      await scrollToBottom()
    }
  } catch (e) {
    ElMessage.error('切换会话失败：' + (e?.message || e))
  }
}

function openRename(s) {
  renameSessionId.value = s.id
  renameSessionTitle.value = s.title || ''
  renameDialogVisible.value = true
}

async function doRename() {
  const title = renameSessionTitle.value.trim()
  if (!title || !renameSessionId.value) return
  try {
    await renameSession(renameSessionId.value, title)
    renameDialogVisible.value = false
    await refreshSessions()
    ElMessage.success('已重命名')
  } catch (e) {
    ElMessage.error('重命名失败：' + (e?.message || e))
  }
}

async function deleteCurrentSession(sessionId) {
  try {
    await ElMessageBox.confirm('确定删除这个对话？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await deleteSession(sessionId)
    if (sessionId === currentSessionId.value) {
      currentSessionId.value = ''
      localStorage.removeItem('memorial_current_session')
      messages.value = []
      clearHistoryStorage()
    }
    await refreshSessions()
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

async function sendMessage() {
  const text = userInput.value.trim()
  if (!text || loading.value) return

  // 如果没有会话，自动创建
  if (!currentSessionId.value) {
    await createNewSession()
  }

  messages.value.push({ role: 'user', content: text })
  userInput.value = ''
  loading.value = true
  await scrollToBottom()

  const t0 = Date.now()
  try {
    const data = await sendChat({
      messages: messages.value.map(m => ({ role: m.role, content: m.content })),
      use_rag: useRag.value,
      session_id: currentSessionId.value,
    })
    // data 现在包含: reply, model, rag_chunks, guard_info, rag_references
    const replyText = data.reply || '(空回复)'
    if (data.model) {
      modelId.value = data.model
    }
    messages.value.push({
      role: 'assistant',
      content: replyText,
      _guardInfo: data.guard_info || null,
      _ragRefs: data.rag_references || [],
    })

    // 预合成：后台静默调用 TTS，让后端缓存预热
    if (preSynthesize.value && replyText && replyText !== '(空回复)') {
      synthesizeSpeech({
        text: stripStyle(replyText),
        voice_id: ttsVoiceId.value || undefined,
        engine: ttsEngine.value,
      }).catch(() => {}) // 静默失败，不影响聊天
    }
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || String(e)
    messages.value.push({
      role: 'assistant',
      content: `⚠️ 请求失败 (${Date.now() - t0}ms)：${msg}`,
    })
    ElMessage.error('请求失败：' + msg)
  } finally {
    loading.value = false
    await scrollToBottom()
    saveHistory()  // 每次正常发言后持久化
  }
}

function useSuggestion(s) {
  userInput.value = s
  sendMessage()
}

function clearMessages() {
  messages.value = []
  stopPlay()
  clearHistoryStorage()
  historyCount.value = 0
  // 如果有当前会话，后端记录也清空（前端只清显示，不删session文件）
  if (currentSessionId.value) {
    // 可选：是否要删除session？不删，让用户可以继续
    // 如果要重新开始，可以引导用户点"新建对话"
  }
  ElMessage.success('对话已清空（本地记录也一并清除）')
}

/**
 * 去掉文本里的语气/动作描写括号（仅展示用，不影响 TTS）。
 * 例：
 *   "（停顿片刻，语气温和而熟悉）嗯，我也知道你想我了。"
 *   → "嗯，我也知道你想我了。"
 *
 * TTS 仍传原文本，让括号里的描述影响声音节奏（Fish 会自然处理停顿，edge-tts 配合
 * 标点也能产生类似效果）。后端 /api/tts 也保留对括号的处理（替换为逗号+静音）。
 */
function stripStyle(s) {
  if (!s) return s
  return s
    .replace(/[（(][^()（）\n]{0,40}[)）]/g, '')   // 去掉 (xxx) / （xxx） 块
    .replace(/[\u{1F300}-\u{1F9FF}\u2600-\u27BF}]/gu, '') // 去掉 emoji
    .replace(/[ \t]{2,}/g, ' ')                    // 多余空格
    .replace(/^[ \t]+|[ \t]+$/g, '')               // 头尾空格（保留标点）
    .trim()
}

async function togglePlay(idx, text) {
  if (playingIdx.value === idx) {
    stopPlay()
    return
  }
  stopPlay()
  playingIdx.value = idx
  try {
    const blob = await synthesizeSpeech({
      text: text.replace(/⚠️.*$/gm, '').trim() || text,
      voice_id: ttsVoiceId.value || undefined,
      engine: ttsEngine.value,
    })
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    currentAudio.value = audio
    audio.onended = () => {
      if (playingIdx.value === idx) {
        playingIdx.value = -1
        URL.revokeObjectURL(url)
      }
    }
    audio.onerror = () => {
      ElMessage.error('音频播放失败')
      playingIdx.value = -1
    }
    await audio.play()
  } catch (e) {
    console.error('[tts] failed:', e)
    ElMessage.error('TTS 失败：' + (e?.response?.data?.detail || e?.message || e))
    playingIdx.value = -1
  }
}

function stopPlay() {
  if (currentAudio.value) {
    try { currentAudio.value.pause() } catch {}
    try {
      if (currentAudio.value.src) URL.revokeObjectURL(currentAudio.value.src)
    } catch {}
    currentAudio.value = null
  }
  playingIdx.value = -1
}

function onVoiceIdChange(v) {
  ttsVoiceId.value = v || ''
  localStorage.setItem('ttsVoiceId', ttsVoiceId.value)
}

onMounted(init)
</script>

<style scoped>
/* ===== 容器 ===== */
.chat-container {
  max-width: 860px;
  margin: 0 auto;
  padding: 0 4px;
}

.chat-layout {
  display: flex;
  flex-direction: column;
}

/* ===== 对话卡片 ===== */
.chat-card {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 124px);
  border: none !important;
  background: var(--bg-card) !important;
  border-radius: var(--rounded-xl) !important;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04) !important;
}

.chat-card :deep(.el-card__header) {
  border-bottom: 1px solid var(--border-soft) !important;
  padding: 14px 24px !important;
}

/* ===== 头部 ===== */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar-circle {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary-light), var(--primary));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.online-dot {
  position: absolute;
  bottom: 1px;
  right: 1px;
  width: 11px;
  height: 11px;
  background: var(--success);
  border: 2px solid white;
  border-radius: 50%;
}

.header-info {
  display: flex;
  flex-direction: column;
}

.display-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.3;
}

.status-line {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
}
.status-dot.online {
  background: var(--success);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2); }
  50% { box-shadow: 0 0 0 6px rgba(16, 185, 129, 0.1); }
}

.model-tag {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ===== 消息区 ===== */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px 12px;
  background:
    radial-gradient(circle at 20% 30%, rgba(99, 102, 241, 0.02) 0%, transparent 40%),
    radial-gradient(circle at 80% 70%, rgba(236, 72, 153, 0.02) 0%, transparent 40%),
    var(--bg-soft);
  scroll-behavior: smooth;
}

/* ===== 单条消息 ===== */
.message {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
  align-items: flex-start;
  animation: msg-fade-in 0.3s ease;
}

@keyframes msg-fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.message.user {
  flex-direction: row-reverse;
}

.avatar-mini {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border-soft);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.message.assistant .avatar-mini {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark, #4f46e5));
  color: white;
  border: none;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.25);
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 75%;
  position: relative;
}

@media (max-width: 640px) {
  .bubble-wrap { max-width: 85%; }
}

.bubble {
  padding: 12px 18px;
  border-radius: 18px;
  word-wrap: break-word;
  line-height: 1.55;
  font-size: 14.5px;
  white-space: pre-wrap;
}

.message.user .bubble {
  background: linear-gradient(135deg, #95ec69 0%, #87d959 100%);
  color: #1a1a1a;
  border-bottom-right-radius: 6px;
  box-shadow: 0 2px 6px rgba(149, 236, 105, 0.2);
}

.message.assistant .bubble {
  background: var(--bg-card);
  color: var(--text);
  border-bottom-left-radius: 6px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  border: 1px solid var(--border-soft);
}

/* ===== 气泡操作按钮 ===== */
.bubble-actions {
  display: flex;
  gap: 4px;
  margin-top: 2px;
  padding-left: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}
.bubble-wrap:hover .bubble-actions {
  opacity: 1;
}
@media (max-width: 640px) {
  .bubble-actions { opacity: 1; }
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s;
}
.action-btn:hover {
  background: var(--primary-soft);
  color: var(--primary);
}
.action-btn.playing {
  background: var(--primary-soft);
  color: var(--primary);
}

/* ===== 打字指示器 ===== */
.bubble.typing {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px 18px;
}
.bubble.typing .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary-light);
  animation: typing-bounce 1.4s ease-in-out infinite;
}
.bubble.typing .dot:nth-child(2) { animation-delay: 0.2s; }
.bubble.typing .dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

/* ===== 空状态 ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  min-height: 380px;
}

.empty-illustration {
  margin-bottom: 18px;
  opacity: 0.7;
}

.empty-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 8px;
}

.empty-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 24px;
  max-width: 380px;
  line-height: 1.6;
}

.empty-suggestions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.empty-suggestions :deep(.el-button) {
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 13px;
  padding: 6px 16px;
  border-radius: 20px;
}
.empty-suggestions :deep(.el-button:hover) {
  border-color: var(--primary-light);
  color: var(--primary);
  background: var(--primary-soft);
}

/* ===== 输入区 ===== */
.input-area {
  border-top: 1px solid var(--border-soft);
  padding: 16px 20px 18px;
  background: var(--bg-card);
}

.chat-input :deep(.el-textarea__inner) {
  border: 1px solid var(--border) !important;
  background: var(--bg-soft) !important;
  resize: none;
  font-size: 14.5px;
  line-height: 1.5;
  padding: 10px 14px;
  border-radius: 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.chat-input :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-light) !important;
  background: var(--bg-card) !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12) !important;
}

.input-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.rag-toggle :deep(.el-checkbox__label) {
  color: var(--text-secondary);
  font-size: 13px;
}
.rag-toggle :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--primary);
  border-color: var(--primary);
}
.rag-toggle .rag-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.rag-toggle .el-icon {
  font-size: 14px;
}

.voice-select {
  width: 140px;
}

.send-btn {
  margin-left: auto;
  padding: 9px 24px !important;
  font-weight: 600;
  border-radius: 20px !important;
}

/* ===== Guard 状态标签 ===== */
.guard-status {
  margin-top: 4px;
  padding-left: 4px;
}
.guard-tag {
  font-size: 11px;
}
.guard-tag .el-icon {
  margin-right: 2px;
  font-size: 11px;
}

/* ===== RAG 引用 ===== */
.rag-refs {
  margin-top: 6px;
  padding-left: 4px;
}
.rag-collapse {
  border: none !important;
  background: transparent !important;
}
.rag-collapse :deep(.el-collapse-item__header) {
  font-size: 11px;
  color: var(--text-muted);
  background: transparent !important;
  border-bottom: none !important;
  height: 24px;
  line-height: 24px;
  padding-left: 0;
}
.rag-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 4px;
  background: transparent !important;
}
.rag-collapse :deep(.el-collapse-item__wrap) {
  background: transparent !important;
  border-bottom: none !important;
}
.rag-ref-item {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  font-size: 11px;
  color: var(--text-secondary);
  padding: 3px 0;
  line-height: 1.4;
}
.rag-ref-role {
  color: var(--primary);
  font-weight: 600;
  flex-shrink: 0;
  min-width: 36px;
}
.rag-ref-text {
  flex: 1;
  word-break: break-all;
}
.rag-ref-score {
  color: var(--text-muted);
  flex-shrink: 0;
  font-size: 10px;
}

/* ===== 会话下拉 ===== */
.session-dropdown {
  margin-right: 4px;
}
.session-dropdown :deep(.el-button) {
  font-size: 13px;
  color: var(--text-secondary);
  padding: 4px 8px;
  border-radius: 8px;
}
.session-dropdown :deep(.el-button:hover) {
  color: var(--primary);
  background: var(--primary-soft);
}
.session-item {
  padding: 2px 0;
  max-width: 260px;
}
.session-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.session-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  font-size: 13px;
  font-weight: 500;
}
.session-item-count {
  color: var(--text-muted);
  font-size: 11px;
  flex-shrink: 0;
}
.session-item-bottom {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.session-item-time {
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.7;
}
.session-rename-btn {
  margin-left: auto;
  opacity: 0;
  transition: opacity 0.15s;
}
.session-item:hover .session-rename-btn {
  opacity: 1;
}

/* ===== 消息进出动画 ===== */
.msg-enter-active {
  transition: all 0.3s ease;
}
.msg-leave-active {
  transition: all 0.2s ease;
}
.msg-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.msg-leave-to {
  opacity: 0;
  transform: scale(0.95);
}

/* ===== 滚动条美化 ===== */
.messages::-webkit-scrollbar {
  width: 6px;
}
.messages::-webkit-scrollbar-track {
  background: transparent;
}
.messages::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}
.messages::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}
</style>