# MemoirAI · 项目亮点

> 给快速浏览者看的 90 秒版本；想深入了解的看 [BACKEND_GUIDE.md](./BACKEND_GUIDE.md) 和 [ARCHITECTURE.md](./ARCHITECTURE.md)。

MemoirAI 是一个**本地优先**的数字纪念应用：把逝者的聊天截图、声音样本丢进去，AI 就能模仿 TA 的语气和你再聊几句。它不是一个消费品——它是一个**可以拆开学习**的 Agent 工程样板。

---

## 一句话定位

> **「把 Agent 工程里能踩的坑（记忆、检索、防编造、风格、声音、隐私）都在一个真实场景里走了一遍。」**

---

## 工程亮点

### 1. 三层 Agent Memory，带评分与衰减

参考论文 *How Memory Management Impacts LLM Agents* 和 *Memory for LLM Agents*：

| 层级 | 类比 | 存储 | 用途 |
|------|------|------|------|
| L1 Working | 短期记忆 | 内存 | 最近 10 轮对话原文，直接喂给 LLM |
| L2 Episodic | 情景记忆 | JSON 文件 | 单次会话摘要，>20 轮自动压缩 |
| L3 Semantic | 长期记忆 | JSON 文件 | 跨会话事实，混合检索 + 评分衰减 |

**评分公式**（防止「记忆污染」和「陈年旧事霸屏」）：

```python
importance = confidence × (0.5 + 0.5 × sigmoid(access_count / 5))
recency   = exp(-days_since_last_access / 30)   # 30 天半衰期
score     = importance × 0.7 + recency × 0.3
```

跨会话同事实出现 → `confidence × 1.05` 自动增强；定时合并去重（每 6 小时）。

### 2. 混合 RAG 检索 + 重排序

不是单一向量检索，是**三段式**：

```
Query → Dense (bge-large-zh, 1024-d) ─┐
        Sparse (BM25 关键词)         ─┼→ 0.7·dense + 0.3·sparse
                                     ┘
                  ↓ 粗排 top-2k
        Rerank (pair embedding) → 0.6·base + 0.4·pair
                  ↓ 加分
        + 对话连贯性（相邻行号 +0.05/行）
                  ↓
        top-k → [{role, text, line_no, score}]
```

`bge-large-zh` 解决中文语义匹配，`BM25` 兜底专有名词/人名，`pair rerank` 校准语义距离。

### 3. Hallucination Guard · 宁可保守不答

数字纪念场景**最怕 LLM 编造**：「你小时候住过 XX 吧？」——用户真的会信。

```
LLM 回复
   ↓
NER 实体提取（人名/地名/品牌/专有名词）
   ↓
RAG chunks + 聊天全文索引 交叉验证
   ├─ 命中 → SAFE
   └─ 未命中 → 计数
              ├─ ≤1 个未验证 → warning（前端标记，不阻断）
              └─ 多个未验证 → blocked（替换为「这事我有点模糊了」+ 前端标签）
```

分级处理：风格化表达不拦、专有名词降级警告、明确编造直接替换。`data/logs/guard_YYYY-MM-DD.txt` 按天留痕。

### 4. Proactive Memory Trigger

不只是「用户问什么答什么」——AI 会在合适时机**主动提起**相关回忆：

```python
# 注入到 system prompt：
# "当你发现当前话题和以下事实相关时，可以自然地提起：
#  - 你记得用户喜欢去公园散步
#  - 你记得用户最近工作很忙"
```

实现：每轮用 `build_triggers(query, top_k=2)` 查相关事实 + 分数阈值（≥0.15）过滤。

### 5. StyleProfile + EmotionDetector · 自我进化

两个**零 LLM 调用**的轻量模块，纯本地统计：

- **StyleProfile**：根据历史对话长度推断用户偏好短/中/长回复
- **EmotionDetector**：9 种情绪关键词匹配，注入语气指导

```python
# EmotionDetector 输出
{"emotion": "sad", "hint": "用温柔、共情的语气，先接住情绪"}
```

### 6. 双引擎 TTS + 预合成缓存

| 引擎 | 费用 | 音质 | 声音克隆 |
|------|------|------|----------|
| edge-tts | 免费 | 一般 | SSML 风格 |
| CosyVoice | 按量付费 | 优秀 | 参考音频 VC 克隆 |

**预合成机制**：

```
AI 回复返回 → 前端收到文字
   ├─ "预合成" 开关开
   │   └─ 后台 fire-and-forget 调 POST /api/tts → 写缓存
   └─ 用户点播放
       └─ 同参数再调 → 缓存命中 ~100ms ✅
```

缓存键包含 8 个维度（engine / voice_id / text / voice / rate / pitch / volume / instruction），避免同一文本不同语气共享缓存。

### 7. Skill 系统 · 可读、可审、可进化的 AI 行为

传统做法把人格调教硬编码进 system prompt——要改一句口头禅得动代码，AI 在哪些规则下工作也看不见。MemoirAI 把这些**外置成可读文本文件**（`.skill`，YAML frontmatter）：

```yaml
# 001_style.skill
name: "说话风格优化"
description: "引导 LLM 模仿逝者的用词、句式、语气和口头禅"
version: 1
updated_at: "2026-07-14"
prompt: |
  # 说话风格与语气
  - 使用短句（1-3句），避免长篇大论。
  - 严格模仿逝者聊天记录中的口头禅。
  - 绝对不说"作为AI"、"根据分析"。
  ...
```

**6 个 skill** 分工：

| 文件 | 注入 prompt? | 锁定? | 作用 |
|------|-------------|-------|------|
| `000_profile.skill` | ✅ | - | 逝者人格（自动生成） |
| `001_style.skill` | ✅ | 🔒 | 说话风格 |
| `002_memory.skill` | ✅ | 🔒 | 何时/怎么提起回忆 |
| `003_boundary.skill` | ✅ | 🔒 | 对话边界 + 安全 |
| `004_evolver.skill` | ❌（meta） | - | 进化规则本身 |
| `005_insights.skill` | ✅ | - | 对话分析（自动生成） |

**关键设计**：
- **双层目录**：`skills/`（仓库模板）vs `data/skills/`（用户私有实例）——首次启动 bootstrap，**不覆盖用户编辑**
- **锁机制**：001/002/003 不可被自动修改——保护"行为契约"
- **Meta-skill 隔离**：`004_evolver` 不注入 prompt——避免 prompt injection
- **Evolver 自动进化**：每 100 轮对话，LLM 扫描新模式，**只提议不写入**

详细：[SKILLS.md](./SKILLS.md)

### 8. PyInstaller 打包成单文件 EXE

`MemoirAI.spec` 处理了一堆 PyInstaller + PaddleOCR + torch 的连环坑：

- paddleocr 整个包目录打包（不能只靠 hiddenimports）
- `paddle/libs/*.dll` 显式列入 binaries
- numpy `.pyd` 合并到 binaries
- `skimage` 全部子模块列 hiddenimports
- `pyi_rth_no_shm.py` runtime hook 解决 Win10/11 `shm.dll [WinError 127]`
- 启动时预热 torch + sentence-transformers，避免 paddle DLL 抢占

最终：双击 `MemoirAI.exe` → 浏览器自动开 → 直接用。

### 8. 隐私优先

| 数据类型 | 存储位置 | 是否出本机 |
|----------|----------|------------|
| 聊天记录 | `data/chat_extracted.txt` | ❌ 本地 |
| 人格画像 | `data/memorial_profile.json` | ❌ 本地 |
| 会话历史 | `data/memory/sessions/*.json` | ❌ 本地 |
| 语义记忆 | `data/memory/semantic_memory.json` | ❌ 本地 |
| RAG 索引 | `data/rag_index/` | ❌ 本地 |
| 声音样本 | `data/voice_samples/*.wav` | ❌ 本地 |
| TTS 缓存 | `data/tts_cache/*.mp3` | ❌ 本地 |
| LLM 调用 | DeepSeek API | ⚠️ 出本机（仅对话文本） |
| TTS 调用 | edge-tts / CosyVoice | ⚠️ 出本机（仅合成文本 + CosyVoice 音频片段） |

**没有任何用户数据**被上传——LLM 和 TTS API 只看到**当前轮对话文本**。

---

## 技术栈一览

| 层 | 选型 | 理由 |
|----|------|------|
| 前端 | Vue 3 + Vite + Element Plus | 轻量、组件库全、HMR 快 |
| 后端 | FastAPI | 异步、类型提示、Swagger 自动生成 |
| LLM | OpenAI 兼容协议 | 任意切换（DeepSeek / 通义 / 智谱 / Ollama） |
| Embedding | BAAI/bge-large-zh-v1.5 | 中文 SOTA，1024 维 |
| OCR | PaddleOCR + 百炼增强 | 本地 + 云端双引擎 |
| TTS | edge-tts + CosyVoice | 免费 + 声音克隆 |
| ASR | faster-whisper | 本地 CTranslate2，CPU 也能跑 |
| 打包 | PyInstaller 6.x | 唯一可行方案（处理 Paddle 链路） |

---

## API 速览

30+ RESTful 端点，分组如下（详见 `routers/api.py`）：

| 分组 | 端点 | 作用 |
|------|------|------|
| 聊天 | `POST /api/chat` | ★ 核心：拼 prompt + 调 LLM + Guard |
| 人格画像 | `GET/PUT /api/profile` | 逝者人格设定 |
| 资料 | `POST /api/upload-screenshots` | 截图批量 OCR + 自动重建索引 |
| 资料 | `POST /api/import-text` | 导入纯文本聊天 |
| 资料 | `POST /api/rebuild-index` | 手动重建 RAG 索引 |
| 声音 | `POST /api/tts` | TTS 合成（带缓存） |
| 声音 | `CRUD /api/tts/samples` | 声音样本管理 |
| 会话 | `CRUD /api/sessions` | 会话 CRUD + 命名 + 导出 |
| 设置 | `GET/PUT /api/settings` | LLM/TTS provider 配置 |

---

## 性能与成本

**单轮对话 token 构成**：

```
System Prompt (人格画像)        1.5K
Semantic Facts                 0.1K
Trigger Hints                  0.05K
Style / Emotion Hints          0.05K
RAG Context (~4 chunks)        0.3K
Working Memory (10 turns)      1-2K
User Input                     0.05K
LLM Output                     0.3K
─────────────────────────────  ~3.5-4.5K tokens/轮
```

按 DeepSeek-V3 定价：**~¥0.005-0.007/轮**，30 轮长对话约 **¥0.15-0.2**。

---

## 这个项目适合谁看

| 身份 | 价值 |
|------|------|
| **AI Agent 学习者** | 真实场景的 Memory / RAG / Guard 全栈实现 |
| **RAG 工程师** | 混合检索 + rerank + 评分衰减的可运行样板 |
| **前端 / 后端** | Vue 3 + FastAPI 的中小型项目脚手架 |
| **产品 / 设计** | 一个值得讨论的「AI + 情感」应用边界案例 |
| **独立开发者** | PyInstaller 打包 PaddleOCR 的全套踩坑记录 |

---

## 不适合谁

- ❌ 想找一个**开箱即用**的商业情感陪伴 App（这只是一个学习/技术原型）
- ❌ 需要**多用户/云端/SaaS**部署（项目假设单用户本地使用）
- ❌ 对「让 AI 模拟逝者」这件事有**伦理顾虑**——这是合理顾虑，请不要勉强使用

---

## 路线图

- [x] v0.1.0 — 基础 FastAPI + Vue 3 框架
- [x] v0.2.0 — 三层 Agent Memory + Hallucination Guard
- [x] v0.3.0 — StyleProfile + EmotionDetector
- [ ] v0.4.0 — 多角色支持、群聊模拟、Web 端共享
- [ ] v0.5.0 — 模型微调（LoRA 微调逝者语料）
- [ ] v1.0.0 — 完整移动端 PWA

---

*最后更新：2026-07-14 · v0.3.0*
