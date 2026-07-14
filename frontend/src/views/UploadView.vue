<template>
  <div v-if="!pageLoaded" style="text-align:center;padding:60px;color:var(--text-muted)">加载中…</div>
  <div v-else class="upload-container">
    <!-- 顶部：数据状态横条 -->
    <div class="stats-bar">
      <div class="stat-card" :class="{ loading: stats.screenshots === '-' }">
        <div class="stat-icon icon-1">
          <el-icon><Picture /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.screenshots }}</div>
          <div class="stat-label">原始截图</div>
        </div>
      </div>
      <div class="stat-card" :class="{ loading: stats.messages === '-' }">
        <div class="stat-icon icon-2">
          <el-icon><ChatLineRound /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.messages }}</div>
          <div class="stat-label">提取消息</div>
        </div>
      </div>
      <div class="stat-card" :class="{ loading: stats.chunks === '-' }">
        <div class="stat-icon icon-3">
          <el-icon><DataAnalysis /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.chunks === '-' ? '未建' : stats.chunks }}</div>
          <div class="stat-label">记忆向量（条）</div>
        </div>
      </div>
      <div class="stat-card model-card">
        <div class="stat-icon icon-4">
          <el-icon><Cpu /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-value-sm">{{ stats.model === '-' ? '未配置' : stats.model }}</div>
          <div class="stat-label">当前 Embedding 模型</div>
        </div>
      </div>
    </div>

    <el-row :gutter="20">
      <!-- 左：聊天记录导入 -->
      <el-col :span="14">
        <el-card class="main-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon class="title-icon"><Folder /></el-icon>
                <span>聊天记录</span>
              </div>
              <el-tag type="success" size="small" effect="light" round>
                推荐用聊天截图 OCR
              </el-tag>
            </div>
          </template>

          <el-tabs v-model="importMode" class="upload-tabs">
            <!-- OCR 截图（主推） -->
            <el-tab-pane name="ocr">
              <template #label>
                <span class="tab-label">
                  <el-icon><Picture /></el-icon> 聊天截图 OCR
                </span>
              </template>

              <el-alert
                type="info"
                :closable="false"
                show-icon
                class="tab-notice"
              >
                <template #title>
                  <strong>主要导入方式</strong>：将聊天截图拖入下方区域，系统将自动提取文字并区分对话角色。
                </template>
              </el-alert>

              <el-upload
                ref="uploadRef"
                class="big-dragger"
                drag
                multiple
                accept="image/*"
                :auto-upload="false"
                v-model:file-list="fileList"
              >
                <div class="dragger-content">
                  <div class="dragger-icon">
                    <el-icon><Picture /></el-icon>
                  </div>
                  <div class="dragger-title">点击或拖拽聊天截图</div>
                  <div class="dragger-desc">支持 PNG / JPG 格式（可同时拖入多张）<br>将聊天截图拖入此处<br>系统将自动识别并提取对话内容</div>
                </div>
              </el-upload>

              <div class="bailian-switch" style="margin: 12px 0;">
                <el-switch
                  v-model="enableBailianOcr"
                  active-text="百炼 OCR 增强（需要配置百炼 API Key）"
                  inactive-text="仅用 PaddleOCR"
                />
                <div class="form-hint" style="margin-top: 6px;">
                  <el-icon><InfoFilled /></el-icon>
                  开启后会在 PaddleOCR 结果基础上，用阿里云百炼 Qwen-VL-OCR 模型二次识别，提升准确率
                </div>
              </div>

              <div class="actions">
                <el-button
                  type="primary"
                  size="large"
                  :loading="processing"
                  :disabled="fileList.length === 0"
                  @click="runOcr"
                  round
                >
                  <el-icon><DocumentCopy /></el-icon>
                  {{ processing ? '处理中…' : `开始 OCR（${fileList.length} 张）` }}
                </el-button>
              </div>
              <el-progress
                v-if="processing"
                :percentage="progress"
                :status="progressStatus"
                :stroke-width="6"
                class="upload-progress"
              />
            </el-tab-pane>

            <!-- 编辑后重新导入文本 -->
            <el-tab-pane name="text">
              <template #label>
                <span class="tab-label">
                  <el-icon><DocumentCopy /></el-icon> 编辑后重新导入
                </span>
              </template>

              <el-alert
                type="info"
                :closable="false"
                show-icon
                class="tab-notice"
              >
                <template #title>
OCR 识别结果将保存至本地 <code>chat_extracted.txt</code>。
              如需修正识别错误，可编辑该文件（每行格式为 <code>[对方] xxx</code> 或
              <code>[本人] xxx</code>），保存后拖入下方区域即可重新导入并重建索引。
                </template>
              </el-alert>

              <el-upload
                ref="textUploadRef"
                class="big-dragger"
                drag
                :auto-upload="false"
                :show-file-list="false"
                accept=".txt,.md,.markdown,.json,.csv"
                :on-change="onTextFileChange"
              >
                <div class="dragger-content">
                  <div class="dragger-icon">
                    <el-icon><UploadFilled /></el-icon>
                  </div>
                  <div class="dragger-title">点击或拖拽已修改的文本文件</div>
                  <div class="dragger-desc">支持 .txt / .md / .json / .csv<br>每行 <code>[对方]</code> 或 <code>[本人]</code> 开头</div>
                </div>
              </el-upload>

              <transition name="el-fade-in">
                <div v-if="pendingTextFile" class="pending-file">
                  <el-icon class="file-icon"><Document /></el-icon>
                  <div class="file-info">
                    <div class="file-name">{{ pendingTextFile.name }}</div>
                    <div class="file-meta">{{ (pendingTextFile.size / 1024).toFixed(1) }} KB</div>
                  </div>
                  <el-button text @click="pendingTextFile = null">
                    <el-icon><Close /></el-icon>
                  </el-button>
                </div>
              </transition>

              <div class="actions">
                <el-button
                  type="primary"
                  size="large"
                  :loading="importingText"
                  :disabled="!pendingTextFile"
                  @click="runImportText"
                  round
                >
                  <el-icon><Promotion /></el-icon>
                  {{ importingText ? '导入中…' : '重新导入并重建记忆' }}
                </el-button>
              </div>

              <el-progress
                v-if="importingText"
                :percentage="progress"
                :status="progressStatus"
                :stroke-width="6"
                class="upload-progress"
              />
            </el-tab-pane>

            <!-- 音频转文字 -->
            <el-tab-pane name="audio">
              <template #label>
                <span class="tab-label">
                  <el-icon><Microphone /></el-icon> 音频转文字
                </span>
              </template>

              <el-alert
                type="info"
                :closable="false"
                show-icon
                class="tab-notice"
              >
                <template #title>
                  <strong>电话录音转文字</strong>：上传音频文件，自动识别为文字后导入聊天记录。
                </template>
              </el-alert>

              <el-upload
                ref="audioUploadRef"
                class="big-dragger"
                drag
                :auto-upload="false"
                :show-file-list="false"
                accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"
                :on-change="onAudioFileChange"
              >
                <div class="dragger-content">
                  <div class="dragger-icon">
                    <el-icon><Microphone /></el-icon>
                  </div>
                  <div class="dragger-title">点击或拖拽音频文件</div>
                  <div class="dragger-desc">支持 wav / mp3 / m4a / aac / flac / ogg / opus<br>自动转写为文字，导入聊天记录</div>
                </div>
              </el-upload>

              <transition name="el-fade-in">
                <div v-if="pendingAudioFile" class="pending-file">
                  <el-icon class="file-icon"><Headset /></el-icon>
                  <div class="file-info">
                    <div class="file-name">{{ pendingAudioFile.name }}</div>
                    <div class="file-meta">{{ (pendingAudioFile.size / 1024).toFixed(1) }} KB</div>
                  </div>
                  <el-button text @click="pendingAudioFile = null">
                    <el-icon><Close /></el-icon>
                  </el-button>
                </div>
              </transition>

              <div class="actions">
                <el-button
                  type="primary"
                  size="large"
                  :loading="transcribingAudio"
                  :disabled="!pendingAudioFile"
                  @click="runAudioToText"
                  round
                >
                  <el-icon><DocumentCopy /></el-icon>
                  {{ transcribingAudio ? '转写中…' : '开始转写' }}
                </el-button>
              </div>

              <el-progress
                v-if="transcribingAudio"
                :percentage="audioProgress"
                :status="audioProgressStatus"
                :stroke-width="6"
                class="upload-progress"
              />

              <transition name="el-fade-in">
                <div v-if="audioTranscript" style="margin-top: 16px;">
                  <div style="font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--text);">
                    转写结果（可编辑，按格式标注 [对方] 或 [本人]）
                  </div>
                  <el-input
                    v-model="audioTranscript"
                    type="textarea"
                    :rows="8"
                    placeholder="转写结果会显示在这里..."
                    class="preview-textarea"
                  />
                  <div class="actions" style="margin-top: 12px;">
                    <el-button
                      type="success"
                      size="large"
                      :loading="importingAudio"
                      :disabled="!audioTranscript.trim()"
                      @click="runImportAudioText"
                      round
                    >
                      <el-icon><Promotion /></el-icon>
                      {{ importingAudio ? '导入中…' : '导入为聊天记录' }}
                    </el-button>
                  </div>
                </div>
              </transition>
            </el-tab-pane>
          </el-tabs>
        </el-card>

        <!-- 声音样本 -->
        <el-card class="main-card" shadow="never" style="margin-top: 20px;">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon class="title-icon"><Microphone /></el-icon>
                <span>声音样本</span>
              </div>
              <el-tag size="small" effect="light" round>用于还原逝者的语音特征</el-tag>
            </div>
          </template>

          <el-upload
            ref="voiceUploadRef"
            class="big-dragger"
            drag
            :auto-upload="false"
            :show-file-list="false"
            accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.opus"
            :on-change="onVoiceFileChange"
          >
            <div class="dragger-content">
              <div class="dragger-icon">
                <el-icon><Microphone /></el-icon>
              </div>
              <div class="dragger-title">上传逝者录音（建议 10s+）</div>
              <div class="dragger-desc">wav / mp3 / m4a / aac / flac / ogg / opus 全部支持<br>
                <span style="color:#67c23a;font-weight:600">所有格式自动转 wav 16kHz + 自动 ASR 识别</span>，不用自己转格式</div>
            </div>
          </el-upload>

          <transition name="el-fade-in">
            <div v-if="pendingVoiceFile" class="pending-file">
              <el-icon class="file-icon"><Headset /></el-icon>
              <div class="file-info">
                <div class="file-name">{{ pendingVoiceFile.name }}</div>
                <div class="file-meta">{{ (pendingVoiceFile.size / 1024).toFixed(1) }} KB</div>
              </div>
              <el-button text @click="pendingVoiceFile = null">
                <el-icon><Close /></el-icon>
              </el-button>
            </div>
          </transition>

          <div class="actions">
            <el-input
              v-model="voiceIdInput"
              placeholder="voice_id（留空用文件名）"
              size="default"
              class="voice-id-input"
            />
            <el-button
              type="primary"
              size="large"
              :loading="uploadingVoice"
              :disabled="!pendingVoiceFile"
              @click="runUploadVoice"
              round
            >
              <el-icon><Upload /></el-icon>
              {{ uploadingVoice ? '上传中…' : '上传并分析' }}
            </el-button>
          </div>

          <el-progress
            v-if="uploadingVoice"
            :percentage="voiceProgress"
            :status="voiceProgressStatus"
            :stroke-width="6"
            class="upload-progress"
          />

          <transition name="el-fade-in">
            <div v-if="voiceSamples.length" class="voice-list">
              <div class="voice-list-title">已上传（{{ voiceSamples.length }}）</div>
              <div
                v-for="s in voiceSamples"
                :key="s.voice_id"
                class="voice-card"
              >
                <div class="voice-card-icon">
                  <el-icon><Headset /></el-icon>
                </div>
                <div class="voice-card-info">
                  <div class="voice-card-name">{{ s.voice_id }}</div>
                  <div class="voice-card-meta">
                    <span><el-icon><Clock /></el-icon> {{ s.features?.duration?.toFixed(1) || '?' }}s</span>
                    <span><el-icon><Headset /></el-icon> {{ s.features?.f0_mean?.toFixed(0) || '?' }} Hz</span>
                    <span><el-icon><Microphone /></el-icon> {{ s.features?.speech_rate?.toFixed(1) || '?' }}/s</span>
                  </div>
                  <div v-if="s.features?.warning" class="voice-card-warning">
                    <el-icon><WarningFilled /></el-icon>
                    {{ s.features.warning }}
                  </div>
                </div>
                <el-button type="danger" size="small" text @click="runDeleteVoice(s.voice_id)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
          </transition>
        </el-card>
      </el-col>

      <!-- 右：操作 / 提示 -->
      <el-col :span="10">
        <el-card class="side-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon class="title-icon"><Refresh /></el-icon>
                <span>操作</span>
              </div>
            </div>
          </template>

          <!-- 主要操作（统一 plain 描边、等距对齐） -->
          <el-space direction="vertical" :size="12" fill class="ops-stack">
            <el-button
              type="success"
              plain
              size="large"
              :loading="rebuilding"
              :disabled="!ocrDone && stats.chunks === '-'"
              @click="rebuildIndex"
              round
              class="full-btn"
            >
              <el-icon><Refresh /></el-icon>
              {{ rebuilding ? '重建中…' : '手动重建索引（OCR 已自动建）' }}
            </el-button>
            <div class="ops-hint">
              上传截图后会自动建索引；这个按钮仅在自动失败时手动重试
            </div>

            <el-button
              type="primary"
              plain
              size="large"
              @click="openPersonaDialog"
              round
              class="full-btn"
            >
              <el-icon><User /></el-icon>
逝者人格画像
            </el-button>
          </el-space>
          <div class="reset-hint">
            <strong>重建索引</strong> 上传聊天截图后用，让 AI 找得到历史对话；<strong>编辑人格</strong> 改 AI 怎么扮演（基本信息 + 补充模板）。
          </div>

          <div class="danger-divider">
            <span class="danger-divider-text">危险操作</span>
          </div>

          <el-button
            type="danger"
            size="large"
            :loading="resetting"
            plain
            @click="confirmResetData"
            round
            class="full-btn"
          >
            <el-icon><Delete /></el-icon>
            {{ resetting ? '清空中…' : '清空聊天记录和索引' }}
          </el-button>
          <div class="reset-hint">
            将删除所有上传的聊天文本、截图和 RAG 索引。<br>
            保留 <strong>人格画像</strong>、<strong>设置</strong> 和 <strong>声音样本</strong>。
          </div>

          <transition name="el-fade-in">
            <el-alert
              v-if="lastResult"
              :title="lastResult.title"
              :type="lastResult.type"
              :description="lastResult.message"
              show-icon
              :closable="false"
              class="result-alert"
            />
          </transition>
        </el-card>

        <el-card class="side-card" shadow="never" style="margin-top: 20px;">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon class="title-icon"><View /></el-icon>
                <span>聊天记录预览</span>
              </div>
            </div>
          </template>
          <el-input
            v-model="previewText"
            type="textarea"
            :rows="14"
            readonly
            placeholder="导入或 OCR 后的对话会显示在这里..."
            class="preview-textarea"
          />
        </el-card>

        <el-card class="side-card hint-card" shadow="never" style="margin-top: 20px;">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon class="title-icon"><Promotion /></el-icon>
                <span>使用流程</span>
              </div>
            </div>
          </template>
          <ol class="hint-list">
            <li>在微信中截取聊天记录</li>
            <li>将截图拖入左侧「聊天截图 OCR」区域</li>
            <li>上传一段逝者的录音样本（建议 10 秒以上）</li>
            <li>切换至「对话」页开始交流</li>
            <li>在「设置」页配置 API key</li>
          </ol>
        </el-card>
      </el-col>
    </el-row>

    <!-- 人格编辑弹窗 -->
    <el-dialog
      v-model="personaDialogVisible"
      title="AI 怎么扮演这个逝者"
      width="720px"
      :close-on-click-modal="false"
      @open="onPersonaDialogOpen"
    >
      <el-form :model="personaForm" label-width="80px" label-position="right">
        <el-form-item label="称呼">
          <el-input v-model="personaForm.name" placeholder="如：妈妈 / 老李 / 张老师" clearable />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="性别">
              <el-select v-model="personaForm.gender" placeholder="选一个" clearable>
                <el-option label="男" value="男" />
                <el-option label="女" value="女" />
                <el-option label="其他" value="其他" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="年龄">
              <el-input v-model="personaForm.age" placeholder="如：60 / 30 多" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="你和逝者关系">
              <el-input v-model="personaForm.relationship" placeholder="如：母亲 / 朋友" clearable />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="AI 怎么自称">
              <el-input v-model="personaForm.self_reference" placeholder="妈 / 爸 / 我" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="AI 怎么叫你">
              <el-input v-model="personaForm.user_reference" placeholder="你 / 宝贝 / 小李" clearable />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="说话风格">
          <el-input
            v-model="personaForm.speaking_style"
            type="textarea"
            :rows="2"
            placeholder="一句话说话风格，如：爱开玩笑 / 文言文 / 简短"
          />
        </el-form-item>

        <el-form-item label="补充模板（可选）">
          <el-input
            v-model="personaForm.system_prompt"
            type="textarea"
            :rows="10"
            placeholder="这里写你的【个性化补充】（基础设置在后台永远生效，你看不到也改不了）"
            class="system-prompt-textarea"
          />
          <div class="form-hint">
            <strong>基础设置（后台）</strong>：永远在最终 prompt 最前，包括「以逝者身份输出、不回避死亡事实、不说约吃饭那种话、推动走出来、危机热线」等核心立场 — 你不能改、不能删、不能覆盖
            <br />
            <strong>你这里写的</strong>：是【个性化补充】，会拼到基础设置之后。比如：逝者的具体语言习惯、关系定义、特别要强调的点
            <br />
            <strong>留空</strong>：用纯基础设置（完全够用）
            <div style="margin-top:8px;">
              <el-button size="small" plain @click="fillDefaultPrompt">
                <el-icon><Document /></el-icon>
                使用补充模板
              </el-button>
              <el-button
                size="small"
                plain
                :disabled="!personaForm.system_prompt"
                @click="personaForm.system_prompt = ''"
              >
                清空（保留基础设置）
              </el-button>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="personaDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="savingPersona"
          @click="savePersona"
        >
          保存并应用到下次对话
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  UploadFilled, DocumentCopy, Refresh, Promotion, Microphone, Headset,
  Delete, Picture, ChatLineRound, DataAnalysis, Cpu,
  Folder, Clock, Document, Close, Upload, View, WarningFilled, User,
  InfoFilled
} from '@element-plus/icons-vue'
import {
  uploadScreenshots, getStats, getProfile, updateProfile,
  importText, listVoiceSamples, uploadVoiceSample, deleteVoiceSample,
  audioToText
} from '../api'

const fileList = ref([])
const processing = ref(false)
const rebuilding = ref(false)
const resetting = ref(false)
const progress = ref(0)
const progressStatus = ref('')
const ocrDone = ref(false)
const previewText = ref('')
const lastResult = ref(null)

// ---- 人格编辑弹窗 ----
const personaDialogVisible = ref(false)
const savingPersona = ref(false)
const personaForm = reactive({
  name: '',
  gender: '',
  age: '',
  relationship: '',
  self_reference: '',
  user_reference: '',
  speaking_style: '',
  system_prompt: '',
})

const importMode = ref('ocr')
const pendingTextFile = ref(null)
const importingText = ref(false)

const voiceSamples = ref([])
const pendingVoiceFile = ref(null)
const voiceIdInput = ref('')
const uploadingVoice = ref(false)
const voiceProgress = ref(0)
const voiceProgressStatus = ref('')
const enableBailianOcr = ref(false)

// ---- 音频转文字 ----
const pendingAudioFile = ref(null)
const transcribingAudio = ref(false)
const importingAudio = ref(false)
const audioProgress = ref(0)
const audioProgressStatus = ref('')
const audioTranscript = ref('')

const pageLoaded = ref(false)
const stats = ref({
  screenshots: '-',
  messages: '-',
  chunks: '-',
  model: '-',
})

async function refreshStats() {
  try {
    stats.value = await getStats()
  } catch (e) {
    console.warn('stats load failed:', e)
  }
}

async function refreshVoiceSamples() {
  try {
    voiceSamples.value = await listVoiceSamples()
  } catch (e) {
    console.warn('listVoiceSamples failed:', e)
  }
}

function onTextFileChange(file) {
  pendingTextFile.value = file
  ElMessage.info(`已选择 ${file.name}，点"导入"开始`)
}

async function runImportText() {
  if (!pendingTextFile.value) return
  importingText.value = true
  progress.value = 0
  progressStatus.value = ''
  previewText.value = ''
  lastResult.value = null
  try {
    const data = await importText(pendingTextFile.value.raw, (p) => {
      progress.value = p
      progressStatus.value = 'uploading'
    })
    progress.value = 90
    progressStatus.value = 'success'
    previewText.value = data.preview || ''
    ocrDone.value = true
    pendingTextFile.value = null
    lastResult.value = {
      title: '导入完成',
      type: 'success',
      message: `从 ${data.source} 导入 ${data.imported} 条消息，索引 ${data.index?.num_chunks || '?'} chunks`,
    }
    ElMessage.success(`导入 ${data.imported} 条消息，索引已重建`)
    await refreshStats()
  } catch (e) {
    progressStatus.value = 'exception'
    lastResult.value = {
      title: '导入失败',
      type: 'error',
      message: e?.response?.data?.detail || e?.message || String(e),
    }
    ElMessage.error('导入失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    importingText.value = false
    progress.value = 100
  }
}

function onAudioFileChange(file) {
  pendingAudioFile.value = file
  audioTranscript.value = ''
  ElMessage.info(`已选择音频 ${file.name}，点击"开始转写"`)
}

async function runAudioToText() {
  if (!pendingAudioFile.value) return
  transcribingAudio.value = true
  audioProgress.value = 0
  audioProgressStatus.value = ''
  audioTranscript.value = ''
  try {
    const data = await audioToText(pendingAudioFile.value.raw, (p) => {
      audioProgress.value = p
      audioProgressStatus.value = 'uploading'
    })
    audioProgress.value = 100
    audioProgressStatus.value = 'success'
    audioTranscript.value = data.text || ''
    ElMessage.success(`转写完成，共 ${data.text?.length || 0} 字符`)
  } catch (e) {
    audioProgressStatus.value = 'exception'
    lastResult.value = {
      title: '转写失败',
      type: 'error',
      message: e?.message || String(e),
    }
    ElMessage.error('转写失败：' + (e?.message || e))
  } finally {
    transcribingAudio.value = false
  }
}

async function runImportAudioText() {
  if (!audioTranscript.value.trim()) return
  importingAudio.value = true
  try {
    const blob = new Blob([audioTranscript.value], { type: 'text/plain' })
    const file = new File([blob], 'audio_transcript.txt')
    const data = await importText(file, (p) => {
      audioProgress.value = p
    })
    previewText.value = data.preview || ''
    ocrDone.value = true
    pendingAudioFile.value = null
    audioTranscript.value = ''
    lastResult.value = {
      title: '导入完成',
      type: 'success',
      message: `从音频转写导入 ${data.imported} 条消息，索引 ${data.index?.num_chunks || '?'} chunks`,
    }
    ElMessage.success(`导入 ${data.imported} 条消息，索引已重建`)
    await refreshStats()
  } catch (e) {
    lastResult.value = {
      title: '导入失败',
      type: 'error',
      message: e?.message || String(e),
    }
    ElMessage.error('导入失败：' + (e?.message || e))
  } finally {
    importingAudio.value = false
  }
}

async function runOcr() {
  if (fileList.value.length === 0) return
  processing.value = true
  progress.value = 0
  progressStatus.value = ''
  previewText.value = ''
  lastResult.value = null
  try {
    const fd = new FormData()
    for (const f of fileList.value) {
      fd.append('files', f.raw)
    }
    fd.append('enable_bailian_ocr', enableBailianOcr.value ? 'true' : 'false')
    progress.value = 30
    progressStatus.value = 'uploading'

    const resp = await fetch('/api/upload-screenshots', {
      method: 'POST',
      body: fd,
    })
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
    }
    progress.value = 80
    progressStatus.value = 'success'

    const data = await resp.json()
    previewText.value = data.preview || '(无预览)'
    ocrDone.value = true

    // 拼装结果消息：OCR 结果 + 索引自动重建结果
    let resultMsg = `成功提取 ${data.message_count} 条消息，新增 ${data.new_count} 条`
    if (data.rebuilt && data.rebuild_meta) {
      resultMsg += `\n✅ 索引已自动重建（${data.rebuild_meta.num_chunks} 个 chunks，模型 ${data.rebuild_meta.model}）`
    } else if (data.new_count > 0 && !data.rebuilt) {
      resultMsg += `\n⚠️ 索引自动重建失败：${data.rebuild_error || '未知'} — 请点下方"重建索引"按钮重试`
    } else if (data.new_count === 0) {
      resultMsg += `\n（对话已存在，无需重建索引）`
    }

    lastResult.value = {
      title: 'OCR 完成',
      type: data.rebuild_error ? 'warning' : 'success',
      message: resultMsg,
    }

    if (data.rebuilt) {
      ElMessage.success(`OCR 完成：${data.message_count} 条消息，索引已自动建好（${data.rebuild_meta.num_chunks} chunks）`)
    } else {
      ElMessage.success(`OCR 完成：${data.message_count} 条消息`)
    }
    fileList.value = []
    await refreshStats()
  } catch (e) {
    progressStatus.value = 'exception'
    lastResult.value = {
      title: 'OCR 失败',
      type: 'error',
      message: e.message || String(e),
    }
    ElMessage.error('OCR 失败：' + (e.message || e))
  } finally {
    processing.value = false
    progress.value = 100
  }
}

async function rebuildIndex() {
  rebuilding.value = true
  try {
    const resp = await fetch('/api/rebuild-index', { method: 'POST' })
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
    }
    const data = await resp.json()
    lastResult.value = {
      title: '索引重建完成',
      type: 'success',
      message: `共 ${data.num_chunks} 个 chunks，维度 ${data.vector_dim}`,
    }
    ElMessage.success('索引重建完成')
    await refreshStats()
  } catch (e) {
    lastResult.value = {
      title: '重建失败',
      type: 'error',
      message: e.message || String(e),
    }
    ElMessage.error('重建失败：' + (e.message || e))
  } finally {
    rebuilding.value = false
  }
}

async function confirmResetData() {
  // 二次确认：第一次 confirm，第二次还得输入 "RESET" 才允许
  try {
    await ElMessageBox.confirm(
      '此操作会删除所有聊天文本、OCR 截图和 RAG 向量索引。\n\n人格画像、API key 和声音样本会保留。\n\n操作不可逆，确定继续？',
      '清空聊天数据',
      {
        type: 'warning',
        confirmButtonText: '我知道了，继续',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return  // 用户取消
  }

  // 第二次强确认：弹 prompt 必须输入 RESET
  let typed
  try {
    const { value } = await ElMessageBox.prompt(
      '为防止误操作，请输入 RESET（大写）以确认清空：',
      '最终确认',
      {
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        inputPattern: /^RESET$/,
        inputErrorMessage: '请输入大写 RESET',
      }
    )
    typed = value
  } catch {
    return
  }
  if (typed !== 'RESET') return

  resetting.value = true
  try {
    const resp = await fetch('/api/reset-data', { method: 'POST' })
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
    }
    const data = await resp.json()
    const d = data.deleted || {}
    lastResult.value = {
      title: '已清空',
      type: 'success',
      message:
        `删除 ${d.chat_txt ? '1 个文本 + ' : ''}${d.screenshots} 张截图 + ${d.index_files} 个索引文件。` +
        `保留：${(data.kept || []).join('、')}`,
    }
    ElMessage.success('已清空聊天记录和 RAG 索引')
    previewText.value = ''
    ocrDone.value = false
    pendingTextFile.value = null
    fileList.value = []
    await refreshStats()
  } catch (e) {
    lastResult.value = {
      title: '清空失败',
      type: 'error',
      message: e.message || String(e),
    }
    ElMessage.error('清空失败：' + (e.message || e))
  } finally {
    resetting.value = false
  }
}

function onVoiceFileChange(file) {
  pendingVoiceFile.value = file
  if (!voiceIdInput.value) {
    voiceIdInput.value = (file.name || '').replace(/\.[^.]+$/, '').replace(/[^\w\-]/g, '_')
  }
  ElMessage.info(`已选择 ${file.name}`)
}

async function runUploadVoice() {
  if (!pendingVoiceFile.value) return
  uploadingVoice.value = true
  voiceProgress.value = 0
  voiceProgressStatus.value = ''
  try {
    const data = await uploadVoiceSample(pendingVoiceFile.value.raw, {
      voice_id: voiceIdInput.value || undefined,
      onProgress: (p) => {
        voiceProgress.value = p
        voiceProgressStatus.value = 'uploading'
      },
    })
    voiceProgress.value = 100
    voiceProgressStatus.value = 'success'
    ElMessage.success(`上传成功: ${data.voice_id}`)
    pendingVoiceFile.value = null
    voiceIdInput.value = ''
    await refreshVoiceSamples()
  } catch (e) {
    voiceProgressStatus.value = 'exception'
    ElMessage.error('上传失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    uploadingVoice.value = false
  }
}

async function runDeleteVoice(voiceId) {
  try {
    await ElMessageBox.confirm(`确定删除声音样本 "${voiceId}"？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await deleteVoiceSample(voiceId)
    ElMessage.success(`已删除 ${voiceId}`)
    await refreshVoiceSamples()
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

async function openPersonaDialog() {
  personaDialogVisible.value = true
}

async function onPersonaDialogOpen() {
  // 拉最新 profile 填到表单
  try {
    const p = await getProfile()
    personaForm.name = p.name || ''
    personaForm.gender = p.gender || ''
    personaForm.age = p.age || ''
    personaForm.relationship = p.relationship || ''
    personaForm.self_reference = p.self_reference || ''
    personaForm.user_reference = p.user_reference || ''
    personaForm.speaking_style = p.speaking_style || ''
    personaForm.system_prompt = p.system_prompt || ''
  } catch (e) {
    console.warn('load profile failed:', e)
  }
}

async function savePersona() {
  savingPersona.value = true
  try {
    // 后端：空字符串会清除字段，None 会跳过；
    // 这里只送非空字段，节省带宽 + 避免把空字符串误存
    const payload = {}
    for (const [k, v] of Object.entries(personaForm)) {
      if (v && String(v).trim()) payload[k] = String(v).trim()
    }
    const r = await updateProfile(payload)
    ElMessage.success(
      `人格已更新（${Object.keys(payload).length} 个字段）。下次对话生效。`,
    )
    personaDialogVisible.value = false
    console.log('[persona] saved:', r?.profile?.name, r?.profile?.gender, r?.profile?.age)
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    savingPersona.value = false
  }
}

// 用户补充模板（拼到基础设置后，base 在后台永远生效）
// 注意：基础设置（以逝者身份、不回避死亡、不约吃饭等）由 core/memorial_profile.py 的
// FALLBACK_SYSTEM 强制注入，前端不能改也不能删。
const DEFAULT_PERSONA_PROMPT = `# 个性化补充（基础设置会自动拼在前面，你写的是补充部分）

## 语言风格
- 用短句（1-2 句），带口头禅
- 偶尔用 catchphrase（按逝者实际习惯，比如"废物"、"fwdx"、"行了行了"等）
- 不写长篇大论，聊天气泡风格

## 关系定义
- 我（AI 扮演）：逝者本人
- 你（用户）：缅怀者
- 我自称：___（按逝者实际怎么自称，比如"爹"、"妈"、"我"）
- 我称呼你：___（按逝者实际怎么叫你，比如"儿子"、"闺女"、"老李"）

## 特别要强调的
- ___

## 想要避免的（逝者生前不会说的话）
- ___
`

function fillDefaultPrompt() {
  personaForm.system_prompt = DEFAULT_PERSONA_PROMPT
  ElMessage.info('已填入默认模板（可继续修改后保存）', { duration: 2000 })
}

onMounted(async () => {
  await Promise.all([refreshStats(), refreshVoiceSamples()])
  pageLoaded.value = true
})
</script>

<style scoped>
.upload-container {
  max-width: 1200px;
  margin: 0 auto;
}

/* Stats bar */
.stats-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-soft);
  border-radius: var(--rounded-lg);
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  box-shadow: var(--shadow-sm);
  transition: all 0.2s ease;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.stat-card.loading { opacity: 0.6; }

.stat-icon {
  width: 42px;
  height: 42px;
  border-radius: var(--rounded);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: white;
}
.stat-icon.icon-1 { background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%); }
.stat-icon.icon-2 { background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%); }
.stat-icon.icon-3 { background: linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%); }
.stat-icon.icon-4 { background: linear-gradient(135deg, #ec4899 0%, #f472b6 100%); }

.stat-content { display: flex; flex-direction: column; min-width: 0; }
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}
.stat-value-sm {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Cards */
.main-card, .side-card {
  border: none !important;
  background: var(--bg-card) !important;
  border-radius: var(--rounded-xl) !important;
  box-shadow: var(--shadow-md) !important;
}

.main-card :deep(.el-card__header),
.side-card :deep(.el-card__header) {
  border-bottom: 1px solid var(--border-soft) !important;
  padding: 16px 20px !important;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 15px;
  color: var(--text);
}

.title-icon {
  color: var(--primary);
  font-size: 18px;
}

/* Tabs */
.upload-tabs :deep(.el-tabs__nav-wrap::after) { background-color: transparent; }

/* Tab 内顶部说明条 */
.tab-notice {
  margin-bottom: 14px;
  border-radius: var(--rounded);
}
.tab-notice :deep(.el-alert__title) {
  font-size: 13px;
  line-height: 1.6;
}
.tab-notice code {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Cascadia Code', Consolas, monospace;
}
.upload-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  padding: 0 16px !important;
}
.upload-tabs :deep(.el-tabs__item.is-active) {
  color: var(--primary) !important;
}
.upload-tabs :deep(.el-tabs__active-bar) {
  background: var(--primary) !important;
  height: 3px !important;
  border-radius: 3px !important;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

/* Big dragger */
.big-dragger :deep(.el-upload-dragger) {
  border: 2px dashed var(--border) !important;
  border-radius: var(--rounded-lg) !important;
  background: linear-gradient(135deg, var(--bg-soft) 0%, #f5f3ff 100%) !important;
  padding: 32px 20px !important;
  transition: all 0.2s ease;
  cursor: pointer;
}
.big-dragger :deep(.el-upload-dragger:hover) {
  border-color: var(--primary) !important;
  background: linear-gradient(135deg, var(--primary-soft) 0%, #f5f3ff 100%) !important;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -4px rgba(99, 102, 241, 0.2);
}

.dragger-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.dragger-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--rounded-lg);
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.dragger-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.dragger-desc {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
  line-height: 1.6;
}
.dragger-desc code {
  background: white;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  border: 1px solid var(--border);
}

/* Pending file */
.pending-file {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 10px 14px;
  background: var(--primary-soft);
  border: 1px solid #c7d2fe;
  border-radius: var(--rounded);
}

.file-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--rounded-sm);
  background: white;
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}

.voice-id-input {
  flex: 1;
  max-width: 280px;
}

.full-btn {
  width: 100%;
  margin-top: 0;
  justify-content: center;
}
.ops-stack {
  width: 100%;
}
.ops-stack > * {
  width: 100%;
}
.ops-hint {
  font-size: 12px;
  color: #909399;
  text-align: center;
  line-height: 1.5;
  padding: 0 8px;
}

.upload-progress {
  margin-top: 12px;
  border-radius: 100px;
}

.result-alert {
  margin-top: 14px;
  border-radius: var(--rounded);
}

/* Danger zone: 重置按钮 */
.danger-divider {
  margin: 18px 0 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  font-weight: 700;
  color: #ef4444;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.danger-divider::before,
.danger-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #fecaca, transparent);
}
.danger-divider-text {
  white-space: nowrap;
}

.reset-hint {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.6;
  text-align: center;
}
.reset-hint strong {
  color: var(--text-secondary);
  font-weight: 600;
}

/* Persona dialog */
.system-prompt-textarea :deep(.el-textarea__inner) {
  font-family: 'Cascadia Code', Consolas, 'Courier New', monospace !important;
  font-size: 12.5px !important;
  line-height: 1.65 !important;
  background: var(--bg-soft) !important;
}
.form-hint {
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.7;
  margin-top: 6px;
}
.form-hint strong {
  color: var(--text);
  font-weight: 600;
}

/* Preview textarea */
.preview-textarea :deep(.el-textarea__inner) {
  font-family: 'Cascadia Code', Consolas, 'Courier New', monospace !important;
  font-size: 12px !important;
  background: #fafbfc !important;
  border: 1px solid var(--border-soft) !important;
  line-height: 1.6 !important;
}

/* Voice list */
.voice-list {
  margin-top: 16px;
}

.voice-list-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.voice-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  border-radius: var(--rounded);
  margin-bottom: 6px;
  transition: all 0.2s ease;
}
.voice-card:hover {
  border-color: var(--primary-light);
  background: var(--primary-soft);
}

.voice-card-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--rounded-sm);
  background: linear-gradient(135deg, #ec4899 0%, #f472b6 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.voice-card-info {
  flex: 1;
  min-width: 0;
}

.voice-card-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.voice-card-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 3px;
}
.voice-card-meta span {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.voice-card-warning {
  margin-top: 6px;
  padding: 6px 8px;
  background: #fef3c7;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  font-size: 11.5px;
  color: #92400e;
  line-height: 1.5;
  display: flex;
  align-items: flex-start;
  gap: 4px;
}
.voice-card-warning .el-icon {
  margin-top: 1px;
  flex-shrink: 0;
}

/* Hint card */
.hint-card .hint-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-secondary);
  line-height: 1.9;
  font-size: 13px;
}
.hint-card .hint-list strong {
  color: var(--primary);
}

/* Transitions */
.el-fade-in-enter-active,
.el-fade-in-leave-active {
  transition: all 0.25s ease;
}
.el-fade-in-enter-from,
.el-fade-in-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>