# MemoirAI

> **Preserve memories, continue conversations.**
> An open-source, privacy-first, locally-deployed AI companion that learns from a loved one's chat history and voice — built as a real-world Agent engineering template.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3-brightgreen.svg)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.139-009688.svg)](https://fastapi.tiangolo.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)
[![Stars](https://img.shields.io/github/stars/yourname/MemoirAI?style=social)](https://github.com/yourname/MemoirAI/stargazers)

[中文文档](./README_CN.md) · [Architecture](./ARCHITECTURE.md) · [Highlights](./HIGHLIGHTS.md) · [Skill System](./SKILLS.md) · [Changelog](./CHANGELOG.md) · [Roadmap](./ROADMAP.md)

---

## What is MemoirAI?

MemoirAI is an **Agent-powered digital memorial** that lets you have one more conversation with someone you've lost. Upload their chat screenshots and voice recordings, and the AI will respond in their tone, using their actual words, in their style.

But more than a product, **MemoirAI is an Agent engineering reference implementation** — every hard part of building an LLM agent (memory, retrieval, hallucination, voice, privacy) is solved in one runnable codebase you can study, fork, and extend.

### Quick demo

```
You:    我想你了
TA (AI): 嗯……我也想你的。最近工作还顺利吗？
         （我记得你之前说过喜欢周末去公园走走，最近还有去吗？）
```

The parenthetical line shows **proactive memory trigger** — the AI recalled something the user mentioned in past conversations and naturally brought it up.

---

## Why MemoirAI?

| Pain point | How MemoirAI solves it |
|------------|------------------------|
| LLM invents facts about the deceased | **Hallucination Guard** — NER + cross-validation against real chat history |
| Bot forgets everything between sessions | **3-layer Agent Memory** with scoring & decay |
| Responses feel generic, not personal | **RAG over real chat logs** + style transfer from history |
| No way to hear their voice | **CosyVoice voice cloning** from 30s+ reference audio |
| Privacy concerns about cloud uploads | **All data stays local**; only LLM/TTS API sees current-turn text |
| Complex to deploy | **One-click EXE** via PyInstaller — no Python needed |

---

## ✨ Highlights

- **3-layer Agent Memory** — Working (in-prompt) / Episodic (session) / Semantic (cross-session) with confidence × recency scoring and 30-day half-life decay.
- **Hybrid RAG** — Dense (bge-large-zh-v1.5) + Sparse (BM25) + Rerank (pair embedding) with conversation-coherence bonus.
- **Hallucination Guard** — NER entity extraction + cross-validation; 3-tier verdict (ok / warning / blocked) with graceful fallback.
- **Proactive Memory Trigger** — AI brings up relevant past memories when topics match, not just on direct question.
- **StyleProfile + EmotionDetector** — Local-only (no LLM call) interaction tracking & sentiment-aware tone adjustment.
- **Dual-engine TTS** — edge-tts (free) + CosyVoice (voice cloning) with pre-synthesis cache (~100ms hit).
- **Privacy-first** — All data on disk; only current-turn text leaves the machine.
- **Pluggable Skill System** — 6 `.skill` files (YAML) define the AI's behavior contract; **readable, auditable, evolvable**; bootstrap from `skills/` to `data/skills/`, locked skills immune to auto-modification.
- **PyInstaller EXE** — Single-file Windows executable with embedded PaddleOCR.

📖 See [HIGHLIGHTS.md](./HIGHLIGHTS.md) for the full breakdown with code snippets.

---

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────────────────────────────────────┐
│  Vue 3 Frontend │───▶│  FastAPI Backend (routers/api.py, 30+ endpoints) │
│  (Element Plus) │    │                                                    │
└─────────────────┘    │  ┌─────────────┐ ┌────────────┐ ┌──────────────┐ │
                       │  │  Agent      │ │   RAG      │ │  Hallucinate │ │
                       │  │  Memory     │◀┤   Search   │▶│  Guard       │ │
                       │  │  (3-layer)  │ │ (hybrid)   │ │ (NER+verify) │ │
                       │  └──────┬──────┘ └─────┬──────┘ └──────┬───────┘ │
                       │         │              │               │         │
                       │         ▼              ▼               ▼         │
                       │  ┌─────────────────────────────────────────────┐ │
                       │  │  System Prompt Assembly (style + emotion +  │ │
                       │  │  RAG context + memory facts + triggers)     │ │
                       │  └─────────────────────┬───────────────────────┘ │
                       │                        ▼                         │
                       │              LLM API (OpenAI protocol)           │
                       │                        │                         │
                       │                        ▼                         │
                       │         TTS (edge-tts / CosyVoice) + Cache       │
                       └──────────────────────────────────────────────────┘
                                        │
                                        ▼
                              Local data/ directory
        (chat logs, profiles, sessions, RAG index, voice samples, TTS cache)
```

📖 Deep dive: [ARCHITECTURE.md](./ARCHITECTURE.md) · [BACKEND_GUIDE.md](./BACKEND_GUIDE.md)

---

## 🚀 Quick Start

### Option A: Dev mode (recommended for hacking)

**Prerequisites**: Python 3.10 · Node.js 18+ · ~10 GB disk for models

```bash
# 1. Clone
git clone https://github.com/yourname/MemoirAI.git
cd MemoirAI

# 2. Install backend deps
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. Download embedding model
cd utils
python dl_bge_large.py
cd ../..

# 4. Install frontend deps
cd frontend
npm install
cd ..

# 5. Configure
# Edit data/user_settings.json (auto-created on first run):
# {
#   "llm_provider": "deepseek",
#   "llm_model": "deepseek-chat",
#   "deepseek_api_key": "sk-...",
#   "tts_engine": "edge"
# }

# 6. Launch
# Windows:
start_all.bat
# macOS / Linux:
# terminal 1: cd backend && python -m uvicorn routers.api:app --host 0.0.0.0 --port 8088 --reload
# terminal 2: cd frontend && npm run dev
```

Open <http://localhost:5173>. Upload chat screenshots in **Upload** view, then chat in **Chat** view.

### Option B: Pre-built EXE (Windows, no Python needed)

Download the latest `MemoirAI.exe` from [Releases](../../releases) → double-click → browser opens. Done.

> Note: First launch downloads PaddleOCR models (~200 MB) to the data directory.

---

## 🧰 Tech Stack

| Layer | Tech | Notes |
|-------|------|-------|
| Frontend | Vue 3 + Vite + Element Plus | SPA, HMR dev |
| Backend | FastAPI (async) | OpenAPI/Swagger auto |
| LLM | OpenAI-compatible API | DeepSeek / DashScope / Ollama / ... |
| Embedding | BAAI/bge-large-zh-v1.5 | 1024-d, Chinese SOTA |
| OCR | PaddleOCR + DashScope (cloud) | Local + cloud hybrid |
| TTS | edge-tts (free) / CosyVoice (clone) | WebSocket for CosyVoice |
| ASR | faster-whisper | CTranslate2, CPU-friendly |
| Audio | PyAV (ffmpeg) | Multi-format decode |
| Packaging | PyInstaller 6.x | Single-file EXE |

---

## 📂 Project Layout

```
MemoirAI/
├── backend/
│   ├── routers/api.py         # FastAPI entry (30+ endpoints)
│   ├── core/                  # Core modules
│   │   ├── agent_memory.py    # 3-layer memory
│   │   ├── rag_search.py      # Hybrid retrieval
│   │   ├── rag_index.py       # Index builder
│   │   ├── hallucination_guard.py
│   │   ├── memorial_profile.py
│   │   ├── audio_features.py
│   │   ├── ocr_service.py     # In-process PaddleOCR
│   │   ├── skill_engine.py
│   │   └── ...
│   ├── utils/                 # Model downloaders, etc.
│   ├── models/                # PaddleOCR weights (user-downloaded)
│   ├── requirements.txt
│   ├── run.py                 # EXE / dev entry
│   └── MemoirAI.spec          # PyInstaller spec
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
├── data/                      # Runtime data (gitignored)
│   ├── user_settings.json
│   ├── chat_extracted.txt
│   ├── memorial_profile.json
│   ├── rag_index/
│   ├── memory/
│   ├── voice_samples/
│   ├── tts_cache/
│   └── logs/
├── start_all.bat              # One-click dev launcher (Windows)
├── skills/                    # Default skill templates (4 files, open-source)
├── data/                      # Runtime data (gitignored)
│   └── skills/                # User-private skill instances (6 files)
├── README.md                  # You are here
├── README_CN.md               # 中文文档
├── HIGHLIGHTS.md              # Project highlights
├── ARCHITECTURE.md            # Deep architecture
├── SKILLS.md                  # Skill system design
├── BACKEND_GUIDE.md           # Backend walkthrough (CN)
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

## 🔌 API Reference

Once the backend is running, visit <http://localhost:8088/docs> for the auto-generated Swagger UI.

Most-used endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat` | POST | Core chat (assembles prompt + RAG + memory + guard) |
| `/api/profile` | GET / PUT | Memorial personality profile |
| `/api/upload-screenshots` | POST | Batch OCR + auto rebuild index |
| `/api/import-text` | POST | Import plain-text chat log |
| `/api/rebuild-index` | POST | Manual RAG index rebuild |
| `/api/tts` | POST | TTS synthesis (cached) |
| `/api/tts/samples` | GET / POST / DELETE | Voice sample management |
| `/api/sessions` | CRUD | Session management |
| `/api/settings` | GET / PUT | LLM / TTS provider config |

---

## 🎭 Skill System

MemoirAI's AI behavior is defined by **6 plain-text skill files** (`.skill`, YAML frontmatter), not hardcoded prompts. This means:

- **Readable** — open any `.skill` file to see what the AI is told to do
- **Auditable** — diff-friendly, easy to review changes
- **Customizable** — edit your own copies in `data/skills/` (never touches the upstream templates)
- **Evolvable** — `004_evolver.skill` defines rules to scan chat history every 100 turns and propose new patterns

### The 6 skills

| File | Injected into prompt? | Locked? | Auto-generated? | Purpose |
|------|------------------------|---------|-----------------|---------|
| `000_profile.skill` | ✅ | — | ✅ (from profile) | The deceased's persona |
| `001_style.skill` | ✅ | 🔒 | — | Speaking style |
| `002_memory.skill` | ✅ | 🔒 | — | When to bring up memories |
| `003_boundary.skill` | ✅ | 🔒 | — | Conversation boundaries, safety |
| `004_evolver.skill` | ❌ (meta) | — | — | Evolution rules |
| `005_insights.skill` | ✅ | — | ✅ (every 100 turns) | Conversation pattern analysis |

**Locked skills** (001/002/003) cannot be auto-modified — they're the foundational behavior contract.

**Two-tier directory structure**:

```
skills/                # repo root — open-source templates (commit these)
data/skills/           # runtime — user-private (gitignored)
```

On first launch, `skill_engine.py` bootstraps `data/skills/` from `skills/`, **never overwriting user edits**.

📖 Deep dive: [SKILLS.md](./SKILLS.md)

---

## 🛡️ Privacy & Ethics

**MemoirAI is a local-first, single-user application.**

- ✅ All chat logs, profiles, sessions, RAG indices, voice samples, TTS cache → stored on your disk
- ✅ No telemetry, no analytics, no tracking
- ⚠️ LLM API call: current-turn text only (not full history)
- ⚠️ TTS API call: current synthesis text only (CosyVoice also uploads the ~30s reference audio you provided)

**Ethical note**: This is a technical prototype, not a grief counseling service. The author(s) acknowledge that simulating the deceased raises serious questions — please use thoughtfully.

📖 See [SECURITY.md](./SECURITY.md).

---

## 🧪 Development

```bash
# Run linter
cd backend && ruff check .
cd frontend && npm run lint

# Run tests (if available)
cd backend && pytest

# Rebuild EXE
cd backend && pyinstaller MemoirAI.spec
```

CI runs on every push via [GitHub Actions](../../actions).

---

## 🤝 Contributing

PRs welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md).

Good first issues: [good first issue](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

---

## 📜 License

[MIT](./LICENSE) © 2026 MemoirAI contributors

---

## 🙏 Acknowledgements

- PaddleOCR / bge-large-zh / faster-whisper / CosyVoice — for the open-source AI stack
- The original 数字纪念 project — for the founding concept
- The open-source Agent research community — for the memory architecture ideas
