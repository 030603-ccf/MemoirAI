# MemoirAI 架构详解

> 给想深入理解或二次开发 MemoirAI 的读者。本文从顶层数据流一路下沉到模块实现。
> 配合 [BACKEND_GUIDE.md](./BACKEND_GUIDE.md)（中文后端讲解）和源码阅读效果最佳。

---

## 一、顶层数据流

一次完整的"用户说话 → AI 听到逝者的声音"涉及 6 个核心环节：

```
┌────────────────────────────────────────────────────────────────────┐
│  ① 用户在 Vue 3 前端输入「我想你了」                                │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │ HTTP POST /api/chat
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ② FastAPI 入口（routers/api.py @app.post("/api/chat")）          │
│     - 加载/创建 Session                                           │
│     - 调用 AgentMemory.build_chat_context() 组装上下文             │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ③ Memory 检索（core/agent_memory.py）                              │
│     - Working: 最近 10 轮原文                                       │
│     - Episodic: 会话摘要（>20 轮自动压缩）                           │
│     - Semantic: 跨会话事实 + 评分衰减 + 主动触发器                  │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ④ RAG 检索（core/rag_search.py）                                   │
│     - Query 扩展（融入对话上下文）                                  │
│     - Dense (bge-large-zh) + Sparse (BM25) 混合 → 0.7+0.3          │
│     - Rerank + 对话连贯性加分 → top-k                              │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ⑤ System Prompt 组装（api.py: chat handler）                       │
│     FALLBACK_SYSTEM (人格画像)                                     │
│     + 用户补充                                                     │
│     + Semantic Facts                                               │
│     + Memory Triggers                                              │
│     + Style Hint                                                   │
│     + Emotion Hint                                                 │
│     + RAG Context                                                  │
│     + Working Memory                                               │
│     + User Message                                                 │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ⑥ LLM 调用（OpenAI 兼容协议）                                     │
│     - DeepSeek / 通义千问 / Ollama / ...                            │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ⑦ Hallucination Guard（core/hallucination_guard.py）               │
│     - NER 实体提取                                                 │
│     - RAG chunks + 聊天全文索引交叉验证                              │
│     - 三级判决：ok / warning / blocked                             │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ⑧ 持久化（AgentMemory.save_turn）                                  │
│     - 写回 Session JSON                                            │
│     - 提取新事实追加到 Semantic Memory                              │
│     - 触发定时 Consolidation（每 6 小时）                            │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ⑨ TTS 合成（可选，POST /api/tts）                                  │
│     - 缓存键 = SHA1(engine|voice_id|text|voice|rate|pitch|volume|  │
│                    instruction)                                    │
│     - 缓存命中 ~100ms 返回                                         │
│     - 缓存未命中 → edge-tts / CosyVoice                            │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  ⑩ 前端展示（ChatView.vue）                                         │
│     - 文字气泡                                                     │
│     - 播放按钮（TTS 音频）                                         │
│     - Guard 标签（warning 时显示"部分验证"）                        │
└────────────────────────────────────────────────────────────────────┘
```

---

## 二、模块依赖图

```
                       ┌────────────────────┐
                       │  routers/api.py    │   ← FastAPI 路由（30+ 端点）
                       │  (请求入口)        │
                       └────────┬───────────┘
                                │
       ┌────────────┬───────────┼───────────┬──────────────┐
       ▼            ▼           ▼           ▼              ▼
  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
  │ agent_  │ │  rag_    │ │ hallu- │ │ memorial │ │  audio_  │
  │ memory  │ │  search  │ │ cination│ │ _profile │ │ features │
  │         │ │          │ │ _guard │ │          │ │          │
  └────┬────┘ └────┬─────┘ └────────┘ └────┬─────┘ └────┬─────┘
       │           │                       │            │
       │           │                       │            │
       ▼           ▼                       ▼            ▼
  ┌─────────┐ ┌──────────┐           ┌──────────┐  ┌──────────┐
  │  rag_   │ │  rag_    │           │  LLM     │  │ edge-tts │
  │  index  │ │  chunks  │           │  client  │  │ CosyVoice│
  │         │ │  (磁盘)  │           │ (OpenAI) │  │ faster-  │
  └─────────┘ └──────────┘           └──────────┘  │  whisper │
                                                  └──────────┘
       │
       ▼
  ┌────────────────┐
  │  ocr_service   │ ← PaddleOCR（executor 隔离）
  └────────────────┘
```

**关键设计原则**：
- `routers/api.py` 是唯一入口，业务逻辑全部下沉到 `core/`
- 各 `core` 模块之间**无横向依赖**（只依赖 `api.py` 注入的路径常量）
- 替换 LLM / TTS / Embedding provider 不需要改任何 `core/` 代码

---

## 三、Agent Memory 三层架构

### 3.1 数据模型

```python
# L1: Working Memory（不存盘，内存里）
session = {
    "session_id": "session_1719000000_abcd1234",
    "title": "今晚的想念",
    "created_at": "2026-07-14T19:30:00",
    "last_active": "2026-07-14T19:45:00",
    "turns": [
        {"role": "user",      "content": "我想你了", "ts": "..."},
        {"role": "assistant", "content": "嗯……我也想你", "ts": "..."},
        # 最近 10 轮
    ],
    "summary": "用户问 AI 一些关于过去的问题"  # > 20 轮时 LLM 压缩生成
}

# L2: Episodic Memory（按 session 存盘）
data/memory/sessions/<session_id>.json  # 完整 session 内容
data/memory/semantic_memory.json        # 跨 session 事实

# L3: Semantic Memory（全局存盘）
{
    "facts": [
        {
            "id": "f1",
            "content": "用户最近搬到了上海",
            "category": "生活",
            "created_at": "2026-07-01T...",
            "updated_at": "2026-07-14T...",
            "access_count": 5,           # 被检索命中次数
            "last_accessed": "2026-07-14T...",
            "source_sessions": ["s1", "s2"],
            "confidence": 0.9
        }
    ]
}
```

### 3.2 评分公式（防记忆霸屏）

```python
def _score_fact(fact, now=None):
    importance = fact["confidence"] * (0.5 + 0.5 * sigmoid(fact["access_count"] / 5))
    recency = exp(-days_since(fact["last_accessed"], now) / 30)  # 30 天半衰期
    return importance * 0.7 + recency * 0.3
```

**为什么是 sigmoid？** 防止 access_count 无限增长导致 importance 失控。
**为什么是 30 天？** 经验值：太短会丢上下文，太长会霸屏旧事。

### 3.3 主动记忆触发器

```python
def build_triggers(query, top_k=2):
    facts = search_facts(query, top_k=top_k*2)   # 混合检索
    triggers = []
    for fact in facts:
        if fact["access_count"] >= 15:           # 太频繁的事实不提了（避免机械）
            continue
        score = _score_fact(fact)
        if score >= 0.15:                        # 阈值过滤
            triggers.append(fact)
    return triggers[:top_k]
```

注入到 system prompt：
```
当你发现当前话题和以下事实相关时，可以自然地提起：
 - 你记得用户喜欢去公园散步
 - 你记得用户最近工作很忙
注意：不相关的话题不要硬提。
```

### 3.4 记忆合并（Consolidation）

每 6 小时跑一次（`scheduler` / 后台线程）：

```python
def consolidate_memory():
    facts = load_all_facts()

    # 1. 合并重复（编辑距离 ≤ 30%）
    facts = merge_similar_facts(facts)

    # 2. 清理低置信度（score < 0.1 且 30 天未访问）
    facts = [f for f in facts if _score_fact(f) >= 0.1 or f["access_count"] >= 3]

    # 3. 写入
    save(facts)
```

---

## 四、RAG 混合检索

### 4.1 索引构建

```
聊天截图 / 文本导入
    ↓ PaddleOCR / 直接解析
chat_extracted.txt
    ↓ parse_chat() → 提取 {role, text, line_no}
    ↓ merge_chunks(window=1) → 相邻消息合并
chunks.json  (N 条)
    ↓ bge.encode(texts, normalize=True)
vectors.npy  (N, 1024)
    ↓ 写 meta.json
data/rag_index/
```

### 4.2 查询流程

```
Query: "我想你了"
    │
    ├─ Query 扩展：拼接前几轮对话作为 context
    │
    ├─ Dense: bge.encode(query) → (1, 1024)
    │   └─ cosine(query_vec, chunk_vecs)  → top-2k
    │
    ├─ Sparse: BM25Tokenize(query) → TF-IDF → BM25
    │   └─ top-2k
    │
    ├─ Hybrid: score = 0.7 * dense + 0.3 * sparse
    │
    ├─ Rerank: bge.rerank(query, chunks)
    │   └─ final = 0.6 * base + 0.4 * pair
    │
    ├─ Coherence: 同 line_no 簇内相邻 +0.05/行
    │
    └─ top-k → [{role, text, line_no, score}]
```

### 4.3 为什么需要混合检索？

| 检索方式 | 强项 | 弱项 |
|----------|------|------|
| Dense (bge) | 语义相似：「高兴」↔「开心」 | 专有名词：「上海迪士尼」会被匹配到「上海」 |
| Sparse (BM25) | 专有名词 / 数字 / 英文 ID | 同义词：无法匹配「妈」↔「母亲」 |
| Rerank (pair) | 精排质量高 | 速度慢，必须先粗排降量 |
| Coherence | 同一段对话连贯 | 跨主题检索无关 |

---

## 五、Hallucination Guard

### 5.1 设计原则

> **宁可保守不答，绝不编造。**

数字纪念场景里，LLM 编造一个不存在的童年回忆，会给用户造成真实的情感伤害。

### 5.2 实体识别

| 类型 | 模式 | 例子 |
|------|------|------|
| 人名 | `[姓氏][1-3字]` | 张三、李老师 |
| 地名 | `[省市县区街镇乡村山河]` 结尾 | 浦东、解放路 |
| 品牌 | `[英文+中文]` | 苹果手机、淘宝店 |
| 时间 | `[\d+年/月/日/号]` | 2015 年、3 月 15 号 |
| 事件 | `[事件关键词]+[动名词]` | 第一次约会、毕业典礼 |

### 5.3 交叉验证

```python
def verify_entity(entity, rag_chunks, full_chat_text):
    # 1. SAFE_WORDS 直接通过
    if entity in SAFE_WORDS:
        return "safe"

    # 2. RAG chunks 命中
    if any(entity in chunk.text for chunk in rag_chunks):
        return "verified"

    # 3. 全文索引命中
    if entity in full_chat_text:
        return "verified"

    # 4. 子串匹配（前 2-3 字）
    if any(entity[:3] in chunk.text for chunk in rag_chunks):
        return "approximate"

    return "unverified"
```

### 5.4 三级判决

| 状态 | 条件 | 行为 |
|------|------|------|
| **ok** | 所有实体验证通过 | 原样返回 LLM 回复 |
| **warning** | 1 个未验证 + ≥3 总实体；或全部专有名词 | 前端标记"部分验证" + 不替换回复 |
| **blocked** | 多个未验证 | 替换为「这事我有点模糊了」+ 前端显示"保守回复"标签 |

所有判决写入 `data/logs/guard_YYYY-MM-DD.txt`，便于事后审计。

---

## 六、TTS 缓存机制

### 6.1 缓存键

```python
cache_key = SHA1(
    f"{engine}|{voice_id}|{text}|{voice}|{rate}|{pitch}|{volume}|{instruction}"
)
```

**8 个维度**都参与 hash——避免同一文本不同语气共享缓存（早期版本的 bug）。

### 6.2 预合成

```
AI 回复返回 → 前端收到文字
    │
    ├─ 如果"预合成"开关打开
    │   └─ 后台 fire-and-forget 调 POST /api/tts
    │       → 后端合成 + 写缓存（不返回给前端）
    │
    └─ 用户点播放
        └─ POST /api/tts（同参数）
            → 缓存命中 → ~100ms 返回 ✅
```

### 6.3 引擎对比

| 引擎 | 费用 | 音质 | 声音克隆 | 协议 |
|------|------|------|----------|------|
| edge-tts | 免费 | 一般 | SSML 风格模拟 | HTTP |
| CosyVoice | 按量 | 优秀 | 参考音频 VC | WebSocket |

---

## 七、PyInstaller 打包

`backend/MemoirAI.spec` + `backend/pyi_rth_no_shm.py` 解决了以下连环坑：

| 坑 | 现象 | 修法 |
|----|------|------|
| paddleocr 动态加载 | import 失败 | 整个 paddleocr 目录打包到 datas |
| paddle/libs/*.dll | 找不到 DLL | 显式列入 binaries |
| numpy C extension | import 慢/失败 | `.pyd` 文件合并到 binaries |
| skimage 子模块 | 运行时 import 失败 | 全部子模块列 hiddenimports |
| shm.dll WinError 127 | torch 加载失败 | runtime hook 从 System32\downlevel 复制 api-ms-win-crt-*.dll |
| paddle DLL 抢占 | OCR 后再 import torch 失败 | 启动时预热 torch + sentence-transformers |

---

## 八、数据流与存储

### 8.1 存储位置

| 数据 | 路径 | 格式 |
|------|------|------|
| 人格画像 | `data/memorial_profile.json` | JSON |
| 用户设置 | `data/user_settings.json` | JSON |
| 聊天记录 | `data/chat_extracted.txt` | 纯文本 |
| RAG 索引 | `data/rag_index/{chunks,vectors,meta}` | JSON + NPY |
| 会话 | `data/memory/sessions/*.json` | JSON |
| 语义记忆 | `data/memory/semantic_memory.json` | JSON |
| 声音样本 | `data/voice_samples/{*.wav,samples.json}` | WAV + JSON |
| TTS 缓存 | `data/tts_cache/{*.mp3,*.json}` | MP3 + meta |
| Guard 日志 | `data/logs/guard_YYYY-MM-DD.txt` | 纯文本 |

### 8.2 Token 预算

```
每轮请求 Token 构成：
┌──────────────────────────────────┐
│ System Prompt (人格画像)    1.5K │
│ Semantic Facts             0.1K  │
│ Trigger Hints              0.05K │
│ Style / Emotion Hints      0.05K │
│ RAG Context (~4 chunks)   0.3K  │
│ Working Memory (10 turns)  1-2K │
│ User Input                 0.05K │
│ LLM Output                 0.3K  │
├──────────────────────────────────┤
│ 合计 ~3.5-4.5K tokens/轮         │
│ DeepSeek-V3: ~¥0.005-0.007/轮    │
│ 30 轮对话: ~¥0.15-0.2            │
└──────────────────────────────────┘
```

---

## 九、扩展点

如果你想二次开发，以下是常见的扩展点：

| 想做的事 | 改哪里 |
|----------|--------|
| 换 LLM provider | `data/user_settings.json` 的 `llm_provider` + 加新 client |
| 换 Embedding 模型 | `core/rag_search.py` 的 `_load_embedder()` |
| 加新 TTS 引擎 | `core/audio_features.py` + `routers/api.py @app.post("/api/tts")` |
| 加新检索策略 | `core/rag_search.py` 的 `hybrid_search()` |
| 改 Guard 阈值 | `core/hallucination_guard.py` 的 `RISKY_ENTITY_TYPES` / `SAFE_WORDS` |
| 加新数据源（短信 / 邮件） | `core/extract_chat_universal.py` |
| 移动端 | 把 `frontend/` 改造成 PWA（已经有 `npm run build` → dist 目录） |
| 微调 LLM | 用 `data/chat_extracted.txt` + LoRA 微调 Qwen3-14B |

---

## 十、性能与限制

### 性能

- 单轮响应（不含 RAG 重建）：**1-3 秒**（视 LLM API 而定）
- RAG 索引构建（1000 条聊天）：**5-10 秒**（含 Embedding 计算）
- TTS 合成：edge-tts **< 1 秒**，CosyVoice **2-4 秒**（首次），缓存命中 **~100ms**

### 已知限制

- 假设单用户本地使用——无多用户/权限/加密
- LLM 上下文窗口限制在 4-8K tokens——长对话依赖摘要压缩
- 跨语种支持有限（当前 Embedding 模型针对中文）
- 无移动端原生 App（PWA 适配工作中）

---

*最后更新：2026-07-14 · v0.3.0*
