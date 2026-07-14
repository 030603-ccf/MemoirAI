/**
 * api/index.js - 前端 API 客户端
 *
 * 所有请求直接打到 Python 后端（端口由 dev 走 vite proxy，
 * exe 模式下是 :8088 同源）：
 *   /api/* → http://localhost:8088  (Python 后端)
 */
import axios from 'axios'

const http = axios.create({
  baseURL: '',
  timeout: 60000,
})

// ---------- 总状态（替代老 vLLM /v1/models） ----------

export async function getStatus() {
  const resp = await http.get('/api/status')
  return resp.data
}

// 向后兼容：一些旧代码可能还在 import listModels；返回空数组即可
export async function listModels() {
  try {
    const status = await getStatus()
    return status?.ready ? ['default'] : []
  } catch {
    return []
  }
}

export async function sendChat({ messages, use_rag = true, temperature = 0.7 }) {
  // 注意：DeepSeek reasoning mode 会消耗 max_tokens；80 太小会被吃光。
  // 不传 max_tokens，用后端默认 300；后端会再 clamp 到 [1, 4000]。
  const resp = await http.post('/api/chat', {
    messages,
    use_rag,
    temperature,
  })
  return resp.data  // 返回完整对象（含 reply, guard_info, rag_references 等）
}

// ---------- Python 后端 ----------

export async function getProfile() {
  const resp = await http.get('/api/profile')
  return resp.data
}

export async function updateProfile(payload) {
  const resp = await http.put('/api/profile', payload)
  return resp.data.profile
}

export async function regenerateProfile() {
  const resp = await http.post('/api/regenerate-profile')
  return resp.data.profile
}

// ---------- 文本导入（OCR 之后用户编辑再上传）----------

export async function importText(file, onProgress) {
  // 走 fetch + FormData，方便拿上传进度
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/import-text')
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round(e.loaded / e.total * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) } catch (e) { reject(e) }
      } else {
        reject(new Error(`HTTP ${xhr.status}: ${xhr.responseText}`))
      }
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.send(fd)
  })
}

// ---------- TTS ----------

export async function listVoices() {
  const resp = await http.get('/api/tts/voices')
  return resp.data
}

export async function synthesizeSpeech({ text, voice = null, rate = '+0%', pitch = '+0Hz', voice_id, volume = '+0%', engine }) {
  // voice=null 时后端按 f0 自动选男/女声（避免硬编码女声覆盖用户上传的男声样本）
  const body = { text, rate, pitch, volume }
  if (voice) body.voice = voice
  if (voice_id) body.voice_id = voice_id
  if (engine) body.engine = engine  // 'fish' | 'edge' — 留空让后端用 settings
  const resp = await http.post('/api/tts', body, {
    responseType: 'blob',
    timeout: 30000,
  })
  return resp.data  // Blob (audio/mpeg)
}

// 声音样本管理
export async function listVoiceSamples() {
  const resp = await http.get('/api/tts/samples')
  return resp.data.samples
}

export async function uploadVoiceSample(file, { voice_id, display_name, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('file', file)
    if (voice_id) fd.append('voice_id', voice_id)
    if (display_name) fd.append('display_name', display_name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/tts/samples')
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round(e.loaded / e.total * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) } catch (e) { reject(e) }
      } else {
        reject(new Error(`HTTP ${xhr.status}: ${xhr.responseText}`))
      }
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.send(fd)
  })
}

export async function deleteVoiceSample(voiceId) {
  const resp = await http.delete(`/api/tts/samples/${encodeURIComponent(voiceId)}`)
  return resp.data
}

// ---------- 用户设置 ----------

export async function getSettings() {
  const resp = await http.get('/api/settings')
  return resp.data
}

export async function updateSettings(payload) {
  const resp = await http.put('/api/settings', payload)
  return resp.data
}

export async function testProviderKey(provider = '') {
  const resp = await http.post('/api/settings/test-provider', { provider }, { timeout: 30000 })
  return resp.data
}

// 保留旧接口兼容
export async function testDeepSeekKey() {
  const resp = await http.post('/api/settings/test-deepseek', {}, { timeout: 30000 })
  return resp.data
}


export async function getStats() {
  const resp = await http.get('/api/stats')
  return resp.data
}

export async function testCosyvoiceKey(settings) {
  const resp = await http.post('/api/settings/test-cosyvoice', settings, { timeout: 30000 })
  return resp.data
}

export async function uploadScreenshots(files, enableBailian = false) {
  const fd = new FormData()
  for (const f of files) {
    fd.append('files', f)
  }
  fd.append('enable_bailian_ocr', enableBailian ? 'true' : 'false')
  const resp = await http.post('/api/upload-screenshots', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return resp.data
}

export async function audioToText(file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/audio-to-text')
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round(e.loaded / e.total * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) } catch (e) { reject(e) }
      } else {
        reject(new Error(`HTTP ${xhr.status}: ${xhr.responseText}`))
      }
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.send(fd)
  })
}

// ---------- Session Management（Agent Memory）----------

export async function createSession(title = '') {
  const resp = await http.post('/api/sessions', { title })
  return resp.data
}

export async function listSessions() {
  const resp = await http.get('/api/sessions')
  return resp.data.sessions
}

export async function getSession(sessionId) {
  const resp = await http.get(`/api/sessions/${encodeURIComponent(sessionId)}`)
  return resp.data
}

export async function renameSession(sessionId, title) {
  const resp = await http.post(`/api/sessions/${encodeURIComponent(sessionId)}/rename`, { title })
  return resp.data
}

export async function deleteSession(sessionId) {
  const resp = await http.delete(`/api/sessions/${encodeURIComponent(sessionId)}`)
  return resp.data
}
