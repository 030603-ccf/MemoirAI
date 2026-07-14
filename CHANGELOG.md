# MemoirAI Changelog

## Unreleased

### Added
- **HIGHLIGHTS.md** — 项目亮点速览（90 秒版）
- **ARCHITECTURE.md** — 架构详解（数据流、模块依赖、扩展点）
- **SKILLS.md** — Skill 系统设计文档
- **`skills/` 目录** — 仓库根的 4 个默认 skill 模板（001/002/003/004）
- **CONTRIBUTING.md** — 贡献指南（PR 流程 / commit 规范 / 风格）
- **SECURITY.md** — 隐私与安全声明（数据流向 / 已知风险 / 伦理说明）
- **GitHub Actions CI** — backend lint + frontend build + docs sanity
- **Issue / PR 模板** — bug / feature / question + PR checklist
- **`.gitattributes`** — 行尾规范化 + 二进制文件标记
- **`data/user_settings.example.json`** — 配置示例（避免误提交 API key）

### Changed
- **`backend/core/skill_engine.py`** — 首次启动从仓库根 `skills/` bootstrap 到 `data/skills/`（不覆盖用户已编辑的副本）
- **`.gitignore`** 增强 — 排除 `.opencode/`、IDE/编辑器临时文件、更多音视频格式 + 显式保护 `data/skills/000_profile.skill` 和 `005_insights.skill`
- **`README.md` / `README_CN.md`** 重写 — 增加 demo 对话、架构图、徽章、API 速查、Skill 系统说明、隐私声明

---

## v0.2.0 (2026-07-14)

### Added
- **Agent Memory 三层架构升级**: 记忆评分（confidence×访问系数×时效衰减）、混合检索（embedding 0.6 + 关键词 0.4）、跨会话置信度增强
- **Proactive Memory Trigger**: AI 在对话中自然提起相关回忆，不等用户主动提问
- **Memory Consolidation**: 定时合并重复事实、清理低置信度记忆（每 6 小时）
- **StyleProfile**: 追踪用户交互模式（对话长度、常见话题），自适应调整回复风格
- **EmotionDetector**: 用户情绪检测（9 种情绪类型），将语气指导注入 system prompt
- **CosyVoice TTS**: 百炼 TTS 引擎支持，通过 WebSocket 协议合成，支持声音克隆（VC）
- **双引擎 TTS 切换**: Edge-tts（免费）+ CosyVoice（付费），用户可在设置页切换
- **TTS 预合成**: 收到 AI 回复后自动后台合成语音，点播放时缓存命中 ~100ms 响应
- **SPA fallback**: 后端直接 serve 前端 dist，访问任意 SPA 路由返回 index.html
- **会话命名 + 时间显示**: 创建/最后对话时间，按时间倒序排列
- **OCR 编码兼容**: 自动检测 UTF-8/GBK/GB18030 编码
- **前端错误处理**: 全局 Vue errorHandler + unhandled rejection 捕获 + 页面直接显示错误
- **页面 loaded 守卫**: UploadView/SettingsView 在异步初始化完成前显示"加载中…"
- **MIT License**

### Changed
- **项目重命名**: "数字纪念" → MemoirAI
- **目录重组**: `qwen-chat-test/` → `backend/`, `project-frontend/` → `frontend/`
- **API 模块整合**: api.py 从 backend/ 移动到 routers/，run.py 支持两种启动方式
- **默认 TTS 模型**: cosyvoice-v3-flash + longanyang
- **Agent Memory 重命名**: `memory_manager.py` → `agent_memory.py`
- **UI 文案优化**: 去口语化（"跑 OCR"→"完成 OCR 识别"，"省钱模式"→"经济模式"）
- **主题调整**: 暖色调背景 + 玻璃效果 header + 悬浮阴影 + 渐变品牌图标

### Fixed
- **Hallucination Guard 误报修复**: 
  - 收紧 brand_pat（不再匹配纯数字+中文）
  - 专有名词类型未验证实体降级为 warning 而非 block
  - 扩展 SAFE_WORDS（+30 个常见情感词/地名/动作词）
  - 新增日志系统（按天存储到 data/logs/guard_YYYY-MM-DD.txt）
- **TTS 缓存密钥**: 加入 instruction 参数避免同一文本不同语气共享缓存
- **shm.dll 冲突**: 服务器启动时预热 torch，用 subprocess 隔离 OCR 与 PyTorch
- **bge 模型搜索路径**: 扩展为项目根 models/ → 上层目录 models/ → HF cache
- **Vite 版本兼容**: 降级至 5.4 兼容 Node.js 20.18
- **start_all.bat 修复**: Python 路径优先检测 conda env
- **count_lines 编码**: 自动尝试 UTF-8/GBK 解码
- **bailian ASR 参数**: Transcription.call() file → file_urls
- **会话消息丢失**: 后续对话中用户新输入被忽略（工作记忆未追加最新消息）
- **turn_count 过期**: save_turn 后重新加载 session 获取最新计数

---

## v0.1.0 (2026-06)

### Added
- 初始版本，从"数字纪念"项目 fork
- FastAPI 后端 + Vue 3 前端
- OCR (PaddleOCR + 百炼增强)
- RAG (bge-large-zh-v1.5)
- edge-tts 语音合成
- faster-whisper ASR
- 声音样本管理
- 会话管理
