<template>
  <div v-if="!loaded" style="text-align:center;padding:60px;color:var(--text-muted)">加载中…</div>
  <div v-else class="settings-container">
    <!-- LLM 配置 -->
    <el-card class="settings-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <div class="title-icon-wrap llm">
              <el-icon><ChatLineRound /></el-icon>
            </div>
            <div>
              <div class="title-main">对话模型</div>
              <div class="title-sub">{{ currentProvider?.description || '选择 OpenAI 兼容格式的 API' }}</div>
            </div>
          </div>
          <el-tag
            :type="isProviderKeySet(llmForm.provider) ? 'success' : 'warning'"
            size="small"
            effect="light"
            round
          >
            <el-icon v-if="isProviderKeySet(llmForm.provider)"><Lock /></el-icon>
            <el-icon v-else><Warning /></el-icon>
            {{ isProviderKeySet(llmForm.provider) ? '已配置' : '未配置' }}
          </el-tag>
        </div>
      </template>

      <el-form :model="llmForm" label-position="top" class="settings-form">
        <!-- Provider 选择 -->
        <el-form-item label="选择模型提供商">
          <el-select
            v-model="llmForm.provider"
            placeholder="选择 API 提供商"
            size="large"
            class="provider-select"
            @change="providerTestResult = null"
          >
            <el-option
              v-for="p in providers"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            >
              <div style="display:flex;align-items:center;gap:8px;">
                <span>{{ p.name }}</span>
                <span style="font-size:11px;color:var(--text-muted);">{{ p.description }}</span>
              </div>
            </el-option>
          </el-select>
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            仅支持 OpenAI 兼容格式的 API，非兼容格式会被拒绝
          </div>
        </el-form-item>

        <!-- API Key -->
        <el-form-item :label="`${currentProvider?.name || 'API'} Key`">
          <el-input
            v-model="llmForm.api_key"
            type="password"
            show-password
            :placeholder="`sk-...（${currentProvider?.description || '在对应平台注册获取'}）`"
            clearable
            size="large"
          >
            <template #append>
              <el-button
                :loading="testingProvider"
                @click="testProvider"
                size="default"
                type="primary"
                plain
              >
                测试
              </el-button>
            </template>
          </el-input>
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            <span v-if="isProviderKeySet(llmForm.provider)">
              当前 key：<code>{{ getProviderKeyMasked(llmForm.provider) }}</code>
            </span>
            <span v-else>未设置 — 后端将使用环境变量默认 key</span>
            <transition name="el-fade-in">
              <span v-if="providerTestResult" class="test-result" :class="providerTestResult.ok ? 'ok' : 'err'">
                {{ providerTestResult.ok ? `✓ ${providerTestResult.reply || '连通'}（${providerTestResult.model}）` : `✗ ${providerTestResult.error}` }}
              </span>
            </transition>

          </div>
        </el-form-item>

        <!-- 自定义 provider 才显示 base_url -->
        <el-form-item v-if="needsCustomBaseUrl" label="Base URL">
          <el-input
            v-model="llmForm.base_url"
            placeholder="https://api.example.com/v1"
            size="large"
          />
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            OpenAI 兼容格式的 API 地址，通常以 /v1 结尾
          </div>
        </el-form-item>

        <el-form-item label="模型">
          <el-input
            v-model="llmForm.model"
            :placeholder="currentProvider?.default_model || 'gpt-3.5-turbo'"
            size="large"
            class="model-input"
          />
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            <span v-if="currentProvider?.default_model">
              默认：<code>{{ currentProvider.default_model }}</code>（留空则使用默认）
            </span>
            <span v-else>请输入模型名</span>
          </div>
        </el-form-item>

        <el-button
          type="primary"
          size="large"
          :loading="savingLlm"
          @click="saveLlm"
          round
          class="save-btn"
        >
          <el-icon><Check /></el-icon>
          保存对话模型设置
        </el-button>
      </el-form>
    </el-card>

    <!-- 声音设置 -->
    <el-card class="settings-card" shadow="never" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <div class="title-icon-wrap tts">
              <el-icon><Microphone /></el-icon>
            </div>
            <div>
              <div class="title-main">声音设置</div>
              <div class="title-sub">选择语音合成引擎</div>
            </div>
          </div>
          <el-tag type="success" size="small" effect="light" round>
            edge · 免费
          </el-tag>
        </div>
      </template>

      <el-form :model="ttsForm" label-position="top" class="settings-form">
        <el-form-item label="声音引擎">
          <div class="engine-grid">
            <div
              class="engine-card"
              :class="{ active: ttsForm.tts_engine === 'edge' }"
              @click="ttsForm.tts_engine = 'edge'"
            >
              <div class="engine-icon">
                <el-icon><Connection /></el-icon>
              </div>
              <div class="engine-info">
                <div class="engine-name">edge（微软）</div>
                <div class="engine-desc">免费 · 模拟逝者说话风格</div>
                <div class="engine-tags">
                  <el-tag size="small" type="success" effect="plain" round>免费</el-tag>
                  <el-tag size="small" effect="plain" round>无需 Key</el-tag>
                </div>
              </div>
              <el-icon v-if="ttsForm.tts_engine === 'edge'" class="engine-check"><Check /></el-icon>
            </div>
            <div
              class="engine-card"
              :class="{ active: ttsForm.tts_engine === 'cosyvoice' }"
              @click="ttsForm.tts_engine = 'cosyvoice'"
            >
              <div class="engine-icon cosyvoice">
                <el-icon><Headset /></el-icon>
              </div>
              <div class="engine-info">
                <div class="engine-name">CosyVoice（百炼）</div>
                <div class="engine-desc">阿里云 TTS + 声音克隆，需 API Key</div>
                <div class="engine-tags">
                  <el-tag size="small" type="warning" effect="plain" round>需 Key</el-tag>
                  <el-tag size="small" effect="plain" round>音质优秀</el-tag>
                </div>
              </div>
              <el-icon v-if="ttsForm.tts_engine === 'cosyvoice'" class="engine-check"><Check /></el-icon>
            </div>
          </div>
          <div v-if="ttsForm.tts_engine === 'edge'" class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            用上传的样本调整微软声音的音高/语速/能量，模拟逝者说话风格（完全免费）
          </div>
          <div v-else class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            使用阿里云 CosyVoice 进行语音合成，支持声音克隆（上传样本后自动用作参考音频）
          </div>
        </el-form-item>

        <!-- CosyVoice 配置（仅选中时显示） -->
        <template v-if="ttsForm.tts_engine === 'cosyvoice'">
          <el-form-item label="CosyVoice Base URL">
            <el-input v-model="ttsForm.cosyvoice_base_url" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" size="large" />
          </el-form-item>
          <el-form-item label="CosyVoice API Key">
            <el-input
              v-model="ttsForm.cosyvoice_api_key"
              type="password"
              show-password
              placeholder="sk-...（在阿里云百炼平台获取）"
              size="large"
            >
              <template #append>
                <el-button
                  :loading="testingCosyvoice"
                  @click="testCosyVoice"
                  size="default"
                  type="primary"
                  plain
                >
                  测试
                </el-button>
              </template>
            </el-input>
            <div class="form-hint">
              <span v-if="settings.cosyvoice_api_key_set">
                当前 key：<code>{{ settings.cosyvoice_api_key_masked }}</code>
              </span>
              <span v-else>未设置 — 可在阿里云百炼平台获取</span>
              <transition name="el-fade-in">
                <span v-if="cosyvoiceTestResult" class="test-result" :class="cosyvoiceTestResult.ok ? 'ok' : 'err'">
                  {{ cosyvoiceTestResult.ok ? '✓ 连通' : '✗ ' + cosyvoiceTestResult.error }}
                </span>
              </transition>
            </div>
          </el-form-item>
          <el-form-item label="TTS 模型">
            <el-input v-model="ttsForm.cosyvoice_model" placeholder="cosyvoice-v2" size="large" />
            <div class="form-hint">一般用户保持默认即可</div>
          </el-form-item>
          <el-form-item label="VC 模型（声音克隆）">
            <el-input v-model="ttsForm.cosyvoice_vc_model" placeholder="qwen3-tts-vc-2026-01-22" size="large" />
            <div class="form-hint">有声音样本时使用此模型进行声音克隆</div>
          </el-form-item>
          <el-form-item label="预设音色">
            <el-input v-model="ttsForm.cosyvoice_voice" placeholder="longxiaochun" size="large" />
            <div class="form-hint">
              当未上传声音样本时使用的默认音色。
              <el-link type="primary" href="https://help.aliyun.com/zh/model-studio/cosyvoice" target="_blank" style="font-size:12px;">查看音色列表</el-link>
            </div>
          </el-form-item>
        </template>

        <el-form-item label="用哪个声音样本">
          <el-select
            v-model="ttsForm.tts_voice_id"
            placeholder="选择已上传的样本（空 = 通用音色）"
            clearable
            filterable
            size="large"
            class="voice-select"
          >
            <el-option
              v-for="s in voiceSamples"
              :key="s.voice_id"
              :label="`${s.voice_id}`"
              :value="s.voice_id"
            >
              <div class="voice-option">
                <span>{{ s.voice_id }}</span>
                <span class="voice-meta">
                  {{ s.features?.duration?.toFixed(1) || '?' }}s ·
                  {{ s.features?.f0_mean?.toFixed(0) || '?' }}Hz
                </span>
              </div>
            </el-option>
          </el-select>
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            在 <router-link to="/upload" class="link">/upload</router-link> 页上传样本
          </div>
        </el-form-item>



        <el-button
          type="primary"
          size="large"
          :loading="savingTts"
          @click="saveTts"
          round
          class="save-btn"
        >
          <el-icon><Check /></el-icon>
          保存声音设置
        </el-button>
      </el-form>
    </el-card>

    <!-- 多模态识别 -->
    <el-card class="settings-card" shadow="never" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <div class="title-icon-wrap mm">
              <el-icon><View /></el-icon>
            </div>
            <div>
              <div class="title-main">多模态识别</div>
              <div class="title-sub">OCR 增强 + 语音转文字（ASR）</div>
            </div>
          </div>
          <el-tag type="info" size="small" effect="light" round>
            可选增强
          </el-tag>
        </div>
      </template>

      <el-form :model="mmForm" label-position="top" class="settings-form">
        <el-form-item label="阿里云百炼 API Key">
          <el-input
            v-model="mmForm.bailian_api_key"
            type="password"
            show-password
            placeholder="sk-...（在阿里云百炼平台注册获取）"
            clearable
            size="large"
          />
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            <span v-if="settings.bailian_api_key_set">
              当前 key：<code>{{ settings.bailian_api_key_masked }}</code>
            </span>
            <span v-else>未设置 — 百炼 OCR / ASR 功能不可用</span>
          </div>
        </el-form-item>

        <el-form-item label="OCR 增强">
          <el-switch
            v-model="mmForm.enable_bailian_ocr"
            active-text="开启百炼 OCR 增强"
            inactive-text="仅用 PaddleOCR"
          />
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            默认使用 PaddleOCR（本地免费），开启后将额外调用百炼多模态模型进行二次识别以提升准确率
          </div>
        </el-form-item>

        <el-form-item label="语音转文字（ASR）引擎">
          <el-select v-model="mmForm.asr_engine" size="large" class="provider-select">
            <el-option label="faster-whisper（本地，免费）" value="faster-whisper" />
            <el-option label="阿里云百炼（云端，需 Key）" value="bailian" />
          </el-select>
          <div class="form-hint">
            <el-icon><InfoFilled /></el-icon>
            faster-whisper 本地运行，无需联网；百炼 ASR 识别准确率更高，但需要消耗 Token
          </div>
        </el-form-item>

        <el-button
          type="primary"
          size="large"
          :loading="savingMm"
          @click="saveMm"
          round
          class="save-btn"
        >
          <el-icon><Check /></el-icon>
          保存多模态设置
        </el-button>
      </el-form>
    </el-card>

    <!-- About -->
    <el-card class="settings-card about-card" shadow="never" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            <div class="title-icon-wrap info">
              <el-icon><InfoFilled /></el-icon>
            </div>
            <div>
              <div class="title-main">关于</div>
              <div class="title-sub">隐私与数据存储</div>
            </div>
          </div>
        </div>
      </template>
      <div class="about-grid">
        <div class="about-item">
          <el-icon class="about-icon"><Lock /></el-icon>
          <div class="about-text">
            <div class="about-title">本地存储</div>
            <div class="about-desc">所有数据（聊天记录、人格画像、声音样本、API key）均保存在本机 <code>data/</code> 目录，不上传服务器</div>
          </div>
        </div>
        <div class="about-item">
          <el-icon class="about-icon"><Link /></el-icon>
          <div class="about-text">
            <div class="about-title">DeepSeek（对话模型）</div>
            <div class="about-desc">
              <a href="https://platform.deepseek.com" target="_blank" class="link">platform.deepseek.com</a> 注册获取 API key，性价比较高
            </div>
          </div>
        </div>
        <div class="about-item">
          <el-icon class="about-icon"><Headset /></el-icon>
          <div class="about-text">
            <div class="about-title">阿里云百炼（CosyVoice TTS）</div>
            <div class="about-desc">
              <a href="https://bailian.console.aliyun.com/" target="_blank" class="link">bailian.console.aliyun.com</a> 开通 CosyVoice 服务后获取 API key
            </div>
          </div>
        </div>
        <div class="about-item">
          <el-icon class="about-icon"><Microphone /></el-icon>
          <div class="about-text">
            <div class="about-title">edge-tts（免费语音合成）</div>
            <div class="about-desc">无需注册，直接可用。配合声音样本可模拟逝者说话风格</div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  InfoFilled, Lock, Check, Microphone, Headset,
  Connection, Link, Warning, ChatLineRound, View
} from '@element-plus/icons-vue'
import {
  getSettings, updateSettings,
  testProviderKey,
  listVoiceSamples, testCosyvoiceKey,
} from '../api'

const settings = ref({})
const providers = ref([])  // 内置 provider 列表（从后端取）
const loaded = ref(false)
const voiceSamples = ref([])

const llmForm = reactive({
  provider: 'deepseek',
  api_key: '',
  model: '',
  base_url: '',
})

const ttsForm = reactive({
  tts_engine: 'edge',
  tts_voice_id: '',
  cosyvoice_api_key: '',
  cosyvoice_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  cosyvoice_model: 'cosyvoice-v2',
  cosyvoice_voice: 'longxiaochun',
  cosyvoice_vc_model: 'qwen3-tts-vc-2026-01-22',
})

const testingCosyvoice = ref(false)
const cosyvoiceTestResult = ref(null)

const mmForm = reactive({
  bailian_api_key: '',
  enable_bailian_ocr: false,
  asr_engine: 'faster-whisper',
})

const savingLlm = ref(false)
const savingTts = ref(false)
const savingMm = ref(false)
const testingProvider = ref(false)
const providerTestResult = ref(null)

// 当前 provider 的 key 字段名
function providerKeyField(pid) {
  return pid.replace(/-/g, '_') + '_api_key'
}

// 当前 provider 是否已配置 key
function isProviderKeySet(pid) {
  const field = providerKeyField(pid)
  return settings.value?.[field + '_set'] || false
}

// 当前 provider 的 masked key
function getProviderKeyMasked(pid) {
  const field = providerKeyField(pid)
  return settings.value?.[field + '_masked'] || ''
}

async function loadAll() {
  try {
    settings.value = await getSettings()
    providers.value = settings.value.providers || []
  } catch (e) {
    ElMessage.error('加载设置失败：' + (e?.message || e))
  }
  try {
    voiceSamples.value = await listVoiceSamples()
  } catch (e) {
    console.warn('[settings] listVoiceSamples failed:', e)
  }

  // 初始化 llmForm
  llmForm.provider = settings.value.llm_provider || 'deepseek'
  llmForm.model = settings.value.llm_model || ''
  llmForm.base_url = settings.value.llm_base_url || ''
  llmForm.api_key = ''

  // 初始化 ttsForm
  ttsForm.tts_engine = settings.value.tts_engine || 'edge'
  ttsForm.tts_voice_id = settings.value.tts_voice_id || ''
  ttsForm.cosyvoice_api_key = ''
  ttsForm.cosyvoice_base_url = settings.value.cosyvoice_base_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1'
  ttsForm.cosyvoice_model = settings.value.cosyvoice_model || 'cosyvoice-v2'
  ttsForm.cosyvoice_voice = settings.value.cosyvoice_voice || 'longxiaochun'
  ttsForm.cosyvoice_vc_model = settings.value.cosyvoice_vc_model || 'qwen3-tts-vc-2026-01-22'

  // 初始化 mmForm
  mmForm.bailian_api_key = ''
  mmForm.enable_bailian_ocr = settings.value.enable_bailian_ocr || false
  mmForm.asr_engine = settings.value.asr_engine || 'faster-whisper'
  loaded.value = true
}

// 获取当前 provider 信息
const currentProvider = computed(() => {
  return providers.value.find(p => p.id === llmForm.provider) || null
})

// 当前 provider 是否需要手动填 base_url（custom 才需要）
const needsCustomBaseUrl = computed(() => llmForm.provider === 'custom')

async function saveLlm() {
  savingLlm.value = true
  try {
    const payload = {
      llm_provider: llmForm.provider,
      llm_model: llmForm.model,
    }
    if (llmForm.provider === 'custom') {
      payload.llm_base_url = llmForm.base_url
      if (llmForm.api_key) {
        payload.llm_api_key = llmForm.api_key
      }
    } else {
      // 内置 provider：key 存在 provider 命名字段
      const keyField = providerKeyField(llmForm.provider)
      if (llmForm.api_key) {
        payload[keyField] = llmForm.api_key
      }
    }
    const r = await updateSettings(payload)
    settings.value = r.settings
    llmForm.api_key = ''
    ElMessage.success('已保存，下次对话生效')
    providerTestResult.value = null
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    savingLlm.value = false
  }
}

async function saveTts() {
  savingTts.value = true
  try {
    const payload = {
      tts_engine: ttsForm.tts_engine,
      tts_voice_id: ttsForm.tts_voice_id,
    }
    if (ttsForm.tts_engine === 'cosyvoice') {
      if (ttsForm.cosyvoice_api_key) payload.cosyvoice_api_key = ttsForm.cosyvoice_api_key
      if (ttsForm.cosyvoice_base_url) payload.cosyvoice_base_url = ttsForm.cosyvoice_base_url
      if (ttsForm.cosyvoice_model) payload.cosyvoice_model = ttsForm.cosyvoice_model
      if (ttsForm.cosyvoice_voice) payload.cosyvoice_voice = ttsForm.cosyvoice_voice
      if (ttsForm.cosyvoice_vc_model) payload.cosyvoice_vc_model = ttsForm.cosyvoice_vc_model
    }
    const r = await updateSettings(payload)
    settings.value = r.settings
    ttsForm.cosyvoice_api_key = ''
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    savingTts.value = false
  }
}

async function saveMm() {
  savingMm.value = true
  try {
    const payload = {
      enable_bailian_ocr: mmForm.enable_bailian_ocr,
      asr_engine: mmForm.asr_engine,
    }
    if (mmForm.bailian_api_key) {
      payload.bailian_api_key = mmForm.bailian_api_key
    }
    const r = await updateSettings(payload)
    settings.value = r.settings
    mmForm.bailian_api_key = ''
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    savingMm.value = false
  }
}

async function testProvider() {
  testingProvider.value = true
  providerTestResult.value = null
  try {
    // 如果用户填了 key，先保存再测试
    if (llmForm.api_key) {
      const payload = {}
      if (llmForm.provider === 'custom') {
        payload.llm_api_key = llmForm.api_key
      } else {
        const keyField = providerKeyField(llmForm.provider)
        payload[keyField] = llmForm.api_key
      }
      await updateSettings(payload)
      llmForm.api_key = ''
      await loadAll()
    }
    providerTestResult.value = await testProviderKey(llmForm.provider)
    // 如果报错看起来不是 OpenAI 兼容格式，弹框提示
    if (!providerTestResult.value.ok && providerTestResult.value.error?.includes('不是 OpenAI 兼容格式')) {
      ElMessage.error('该 API 不是 OpenAI 兼容格式，请更换或选择其他提供商')
    }
  } catch (e) {
    providerTestResult.value = { ok: false, error: e?.message || String(e) }
  } finally {
    testingProvider.value = false
  }
}

async function testCosyVoice() {
  testingCosyvoice.value = true
  cosyvoiceTestResult.value = null
  try {
    if (ttsForm.cosyvoice_api_key) {
      await updateSettings({
        cosyvoice_api_key: ttsForm.cosyvoice_api_key,
        cosyvoice_base_url: ttsForm.cosyvoice_base_url,
        cosyvoice_model: ttsForm.cosyvoice_model,
        cosyvoice_voice: ttsForm.cosyvoice_voice,
      })
      ttsForm.cosyvoice_api_key = ''
      settings.value = await getSettings()
    }
    const result = await testCosyvoiceKey({
      base_url: ttsForm.cosyvoice_base_url,
      model: ttsForm.cosyvoice_model,
      voice: ttsForm.cosyvoice_voice,
    })
    cosyvoiceTestResult.value = result
  } catch (e) {
    cosyvoiceTestResult.value = { ok: false, error: e?.message || String(e) }
  } finally {
    testingCosyvoice.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.settings-container {
  max-width: 760px;
  margin: 0 auto;
}

.settings-card {
  border: none !important;
  background: var(--bg-card) !important;
  border-radius: var(--rounded-xl) !important;
  box-shadow: var(--shadow-md) !important;
}

.settings-card :deep(.el-card__header) {
  border-bottom: 1px solid var(--border-soft) !important;
  padding: 18px 24px !important;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 14px;
}

.title-icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: var(--rounded);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: white;
}
.title-icon-wrap.llm { background: linear-gradient(135deg, #6366f1 0%, #818cf8 100%); }
.title-icon-wrap.tts { background: linear-gradient(135deg, #ec4899 0%, #f472b6 100%); }
.title-icon-wrap.mm { background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%); }
.title-icon-wrap.info { background: linear-gradient(135deg, #6366f1 0%, #a78bfa 100%); box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2); }

.title-main {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}

.title-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 3px;
}

.settings-form :deep(.el-form-item__label) {
  font-weight: 600;
  color: var(--text);
  padding-bottom: 6px;
  font-size: 13px;
}

.form-hint {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 6px;
  line-height: 1.6;
}

.form-hint code {
  background: var(--primary-soft);
  color: var(--primary-dark);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 11px;
  font-weight: 600;
}

.test-result {
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.test-result.ok {
  background: #ecfdf5;
  color: #047857;
}
.test-result.err {
  background: #fef2f2;
  color: #b91c1c;
}

.save-btn {
  margin-top: 8px;
  padding: 12px 32px !important;
  font-weight: 600;
}

/* Engine cards */
.engine-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 6px;
}

.engine-card {
  position: relative;
  padding: 18px;
  border: 2px solid var(--border);
  border-radius: var(--rounded-lg);
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--bg-card);
  display: flex;
  align-items: center;
  gap: 12px;
}
.engine-card:hover {
  border-color: var(--primary-light);
  background: var(--primary-soft);
  transform: translateY(-2px);
}
.engine-card.active {
  border-color: var(--primary);
  background: linear-gradient(135deg, var(--primary-soft) 0%, #faf5ff 100%);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
}

.engine-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--rounded);
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}
.engine-icon.cosyvoice {
  background: linear-gradient(135deg, #ec4899 0%, #f472b6 100%);
}
.engine-info { flex: 1; }

.engine-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 3px;
}

.engine-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.engine-tags {
  display: flex;
  gap: 4px;
}

.engine-check {
  position: absolute;
  top: 12px;
  right: 12px;
  color: var(--primary);
  font-size: 18px;
  background: white;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.25);
}

.voice-select {
  width: 100%;
}

.voice-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.voice-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.divider-text {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
  letter-spacing: 0.5px;
}

.model-input {
  max-width: 320px;
}

.provider-select {
  width: 100%;
}

/* About */
.about-card {
  background: linear-gradient(135deg, var(--bg-card) 0%, #f5f3ff 100%) !important;
  border: 1px solid rgba(99, 102, 241, 0.08) !important;
}

.about-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.about-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 16px;
  background: var(--bg-card);
  border-radius: var(--rounded-lg);
  border: 1px solid var(--border-soft);
  transition: all 0.2s ease;
}
.about-item:hover {
  border-color: var(--primary-light);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.about-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--rounded-sm);
  background: var(--primary-soft);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.about-text {
  flex: 1;
  min-width: 0;
}

.about-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}

.about-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.about-desc code {
  background: var(--bg-soft);
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
  font-size: 11px;
}

.link {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
  border-bottom: 1px dashed var(--primary-light);
}
.link:hover {
  color: var(--primary-dark);
  border-bottom-style: solid;
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