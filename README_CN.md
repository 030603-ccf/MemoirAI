# MemoirAI（数字纪念）

> **保存记忆，延续对话。**
> 一个开源、隐私优先、本地部署的 AI 情感陪伴应用——它能学习逝者的聊天风格和声音，并作为一个**可拆解学习的 Agent 工程样板**存在。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3-brightgreen.svg)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.139-009688.svg)](https://fastapi.tiangolo.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

[English](./README.md) · [架构详解](./ARCHITECTURE.md) · [项目亮点](./HIGHLIGHTS.md) · [Skill 系统](./SKILLS.md) · [后端讲解](./BACKEND_GUIDE.md) · [更新日志](./CHANGELOG.md) · [路线图](./ROADMAP.md)

---

## 这是什么？

MemoirAI 是一个**基于 Agent 架构的数字纪念应用**：把逝者的聊天截图、声音样本丢进去，AI 就能模仿 TA 的语气、词汇、风格和你再聊几句。

但它**不只是一个产品**——它是一个 **Agent 工程参考实现**。构建 LLM agent 涉及的所有难点（记忆、检索、防编造、声音、隐私）都在这一个可运行的代码库里解决了，你可以拆开看、fork、改。

### 一段示例

```
你：   我想你了
TA：   嗯……我也想你的。最近工作还顺利吗？
       （我记得你之前说过喜欢周末去公园走走，最近还有去吗？）
```

括号里那一行是 **Proactive Memory Trigger**——AI 主动调用了过去对话里用户提过的事实，自然地接上。

---

## 为什么要做 MemoirAI？

| 痛点 | 解决方案 |
|------|----------|
| LLM 编造逝者的事迹 | **Hallucination Guard**——NER + 交叉验证，只放过有据可查的实体 |
| 每次重开就失忆 | **三层 Agent Memory**——带评分衰减 |
| 回复太通用品味不像 | **RAG 检索真实聊天记录** + 风格迁移 |
| 听不到 TA 的声音 | **CosyVoice 声音克隆**（30s 参考音频起步） |
| 担心隐私 | **数据全本地**——只把当前轮对话文本交给 LLM/TTS |
| 部署太复杂 | **PyInstaller 打包成单文件 EXE**——双击就能跑 |

---

## ✨ 亮点速览

- **三层 Agent Memory**——Working（prompt 内）/ Episodic（单会话）/ Semantic（跨会话），带 `importance × recency` 评分与 30 天半衰期衰减
- **混合 RAG**——Dense（bge-large-zh-v1.5）+ Sparse（BM25）+ Rerank（pair embedding）+ 对话连贯性加分
- **Hallucination Guard**——NER 实体抽取 + 交叉验证，三级判决（ok / warning / blocked），优雅降级
- **Proactive Memory Trigger**——话题匹配时主动提起相关回忆，不只是被动回答
- **StyleProfile + EmotionDetector**——本地零 LLM 调用的交互追踪 + 情感感知语气调整
- **双引擎 TTS**——edge-tts（免费）+ CosyVoice（声音克隆），预合成缓存命中 ~100ms
- **隐私优先**——所有数据本地存储；只把当前轮对话文本出本机
- **可插拔 Skill 系统**——6 个 `.skill` 文件（YAML）定义 AI 行为契约；**可读、可审、可进化**；从 `skills/` bootstrap 到 `data/skills/`，锁定 skill 不可自动修改
- **PyInstaller EXE**——单文件 Windows 可执行，内嵌 PaddleOCR

📖 详细代码片段见 [HIGHLIGHTS.md](./HIGHLIGHTS.md)

---

## 🏗️ 架构一览

```
┌─────────────────┐    ┌──────────────────────────────────────────────────┐
│  Vue 3 前端     │───▶│  FastAPI 后端 (routers/api.py, 30+ 端点)         │
│  (Element Plus) │    │                                                    │
└─────────────────┘    │  ┌─────────────┐ ┌────────────┐ ┌──────────────┐ │
                       │  │  Agent      │ │   RAG      │ │  Hallucinate │ │
                       │  │  Memory     │◀┤   Search   │▶│  Guard       │ │
                       │  │  (3 层)     │ │ (混合检索) │ │ (NER+验证)   │ │
                       │  └──────┬──────┘ └─────┬──────┘ └──────┬───────┘ │
                       │         │              │               │         │
                       │         ▼              ▼               ▼         │
                       │  ┌─────────────────────────────────────────────┐ │
                       │  │  System Prompt 组装 (风格 + 情感 +           │ │
                       │  │  RAG 上下文 + 记忆事实 + 触发器)            │ │
                       │  └─────────────────────┬───────────────────────┘ │
                       │                        ▼                         │
                       │              LLM API (OpenAI 协议)               │
                       │                        │                         │
                       │                        ▼                         │
                       │         TTS (edge-tts / CosyVoice) + 缓存        │
                       └──────────────────────────────────────────────────┘
                                        │
                                        ▼
                              本地 data/ 目录
        (聊天记录、人格画像、会话、RAG 索引、声音样本、TTS 缓存)
```

📖 深入讲解：[ARCHITECTURE.md](./ARCHITECTURE.md) · [BACKEND_GUIDE.md](./BACKEND_GUIDE.md)

---

## 🚀 快速开始

### 方式 A：开发模式（推荐给想改代码的人）

**前置要求**：Python 3.10 · Node.js 18+ · 约 10 GB 磁盘（放模型）

```bash
# 1. 克隆
git clone https://github.com/yourname/MemoirAI.git
cd MemoirAI

# 2. 安装后端依赖
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 下载 bge 嵌入模型
cd utils
python dl_bge_large.py
cd ../..

# 4. 安装前端依赖
cd frontend
npm install
cd ..

# 5. 配置 API Key
# 编辑 data/user_settings.json（首次运行自动创建）：
# {
#   "llm_provider": "deepseek",
#   "llm_model": "deepseek-chat",
#   "deepseek_api_key": "sk-你的key",
#   "tts_engine": "edge"
# }

# 6. 启动
# Windows 一键：
start_all.bat

# macOS / Linux 手动：
# 终端 1: cd backend && python -m uvicorn routers.api:app --host 0.0.0.0 --port 8088 --reload
# 终端 2: cd frontend && npm run dev
```

浏览器打开 <http://localhost:5173>。在 **上传** 视图里导入聊天截图，然后到 **对话** 视图开聊。

### 方式 B：预编译 EXE（Windows，免 Python）

从 [Releases](../../releases) 下载最新的 `MemoirAI.exe` → 双击 → 浏览器自动打开 → 用。

> 首次启动会下载 PaddleOCR 模型（~200 MB）到 data 目录。

---

## 🧰 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | Vue 3 + Vite + Element Plus | SPA + HMR |
| 后端 | FastAPI（异步） | 自动生成 OpenAPI/Swagger |
| LLM | OpenAI 兼容协议 | DeepSeek / 通义千问 / Ollama / ... |
| Embedding | BAAI/bge-large-zh-v1.5 | 1024 维，中文 SOTA |
| OCR | PaddleOCR + 百炼（云端） | 本地 + 云端混合 |
| TTS | edge-tts（免费） / CosyVoice（克隆） | CosyVoice 用 WebSocket |
| ASR | faster-whisper | CTranslate2，CPU 也能跑 |
| 音频 | PyAV (ffmpeg) | 多格式解码 |
| 打包 | PyInstaller 6.x | 单文件 EXE |

---

## 📂 项目结构

```
MemoirAI/
├── backend/
│   ├── routers/api.py         # FastAPI 入口（30+ 端点）
│   ├── core/                  # 核心模块
│   │   ├── agent_memory.py    # 三层记忆
│   │   ├── rag_search.py      # 混合检索
│   │   ├── rag_index.py       # 索引构建
│   │   ├── hallucination_guard.py
│   │   ├── memorial_profile.py
│   │   ├── audio_features.py
│   │   ├── ocr_service.py     # 内嵌 PaddleOCR
│   │   ├── skill_engine.py
│   │   └── ...
│   ├── utils/                 # 模型下载脚本等
│   ├── models/                # PaddleOCR 权重（用户下载）
│   ├── requirements.txt
│   ├── run.py                 # EXE / dev 入口
│   └── MemoirAI.spec          # PyInstaller 配置
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── ChatView.vue
│   │   │   ├── UploadView.vue
│   │   │   ├── MemoryView.vue
│   │   │   └── SettingsView.vue
│   │   ├── api/index.js
│   │   ├── router/index.js
│   │   └── App.vue
│   ├── package.json
│   └── vite.config.js
├── data/                      # 运行时数据（gitignore）
│   ├── user_settings.json
│   ├── chat_extracted.txt
│   ├── memorial_profile.json
│   ├── rag_index/
│   ├── memory/
│   ├── voice_samples/
│   ├── tts_cache/
│   └── logs/
├── start_all.bat              # 一键启动（Windows）
├── skills/                    # 默认 skill 模板（4 个文件，开源）
├── data/                      # 运行时数据（gitignore）
│   └── skills/                # 用户私有 skill 实例（6 个文件）
├── README.md                  # 英文文档
├── README_CN.md               # 本文档
├── HIGHLIGHTS.md              # 项目亮点
├── ARCHITECTURE.md            # 架构详解
├── SKILLS.md                  # Skill 系统设计
├── BACKEND_GUIDE.md           # 后端讲解（中文）
├── CHANGELOG.md
├── ROADMAP.md
├── TODO.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE                    # MIT
└── .github/
    ├── workflows/ci.yml
    ├── ISSUE_TEMPLATE/
    └── PULL_REQUEST_TEMPLATE.md
```

---

## 🔌 API 速查

后端启动后，访问 <http://localhost:8088/docs> 看自动生成的 Swagger。

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/chat` | POST | ★ 核心：拼 prompt + RAG + 记忆 + Guard |
| `/api/profile` | GET / PUT | 人格画像管理 |
| `/api/upload-screenshots` | POST | 批量 OCR + 自动重建索引 |
| `/api/import-text` | POST | 导入纯文本聊天记录 |
| `/api/rebuild-index` | POST | 手动重建 RAG 索引 |
| `/api/tts` | POST | TTS 合成（带缓存） |
| `/api/tts/samples` | GET / POST / DELETE | 声音样本管理 |
| `/api/sessions` | CRUD | 会话管理 |
| `/api/settings` | GET / PUT | LLM / TTS provider 配置 |

---

## 🎭 Skill 系统

MemoirAI 的 AI 行为由 **6 个纯文本 skill 文件**（`.skill`，YAML frontmatter）定义，不是写死在 system prompt 里。这意味着：

- **可读**——打开任何 `.skill` 文件就能看到 AI 被告知做什么
- **可审**——diff 友好，方便 review 修改
- **可定制**——编辑 `data/skills/` 里的副本（不会动到上游模板）
- **可进化**——`004_evolver.skill` 定义每 100 轮扫描对话历史并提议新模式的规则

### 6 个 skill

| 文件 | 注入 prompt? | 锁定? | 自动生成? | 作用 |
|------|-------------|-------|----------|------|
| `000_profile.skill` | ✅ | — | ✅（从 profile） | 逝者人格 |
| `001_style.skill` | ✅ | 🔒 | — | 说话风格 |
| `002_memory.skill` | ✅ | 🔒 | — | 何时提起回忆 |
| `003_boundary.skill` | ✅ | 🔒 | — | 对话边界 + 安全 |
| `004_evolver.skill` | ❌（meta） | — | — | 进化规则 |
| `005_insights.skill` | ✅ | — | ✅（每 100 轮） | 对话模式分析 |

**锁定 skill**（001/002/003）不可被自动修改——它们是基础行为契约。

**双层目录结构**：

```
skills/                # 仓库根——开源模板（提交这些）
data/skills/           # 运行时——用户私有（gitignore）
```

首次启动时，`skill_engine.py` 从 `skills/` bootstrap 到 `data/skills/`，**永不会覆盖用户编辑**。

📖 深入了解：[SKILLS.md](./SKILLS.md)

---

## 🛡️ 隐私与伦理

**MemoirAI 是本地优先、单用户应用。**

- ✅ 聊天记录、人格画像、会话、RAG 索引、声音样本、TTS 缓存——全部存在你本机
- ✅ 无任何遥测 / 埋点 / 统计
- ⚠️ LLM API 调用：只把**当前轮对话文本**出本机（不含历史）
- ⚠️ TTS API 调用：edge-tts 只传合成文本；CosyVoice 还会传你提供的 ~30s 参考音频

**伦理说明**：这是技术原型，不是心理治疗服务。模拟逝者涉及严肃的伦理议题——请谨慎、尊重地使用。

📖 详见 [SECURITY.md](./SECURITY.md)。

---

## 🧪 开发

```bash
# 后端 lint
cd backend && ruff check .

# 前端 lint
cd frontend && npm run lint

# 测试
cd backend && pytest

# 重新打包 EXE
cd backend && pyinstaller MemoirAI.spec
```

CI 跑在 [GitHub Actions](../../actions)。

---

## 🤝 贡献

欢迎 PR！详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

新手友好 issue：[good first issue](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

---

## 📜 License

[MIT](./LICENSE) © 2026 MemoirAI contributors

---

## 🙏 致谢

- PaddleOCR / bge-large-zh / faster-whisper / CosyVoice——开源 AI 工具链
- 原始「数字纪念」项目——奠定了产品形态
- 开源 Agent 学术社区——记忆架构的灵感来源
