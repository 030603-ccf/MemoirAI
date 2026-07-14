# MemoirAI 后端架构讲解

> 写给想学习 Agent 开发的开发者。本文从架构全貌到核心模块逐层讲解。

## 一、整体架构

```
浏览器 (Vue 3 SPA)
    │  HTTP /api/*
    ▼
FastAPI (routers/api.py, 2750+ lines)
    │
    ├─ GET/PUT /api/profile    人格画像管理
    ├─ POST /api/chat          ★核心★ 聊天：拼 System Prompt + RAG + Agent Memory + Guard
    ├─ POST /api/upload-*      截图 OCR + 自动重建索引
    ├─ POST /api/rebuild-index RAG 向量索引重建
    ├─ POST /api/tts           TTS 语音合成（edge-tts / CosyVoice）
    ├─ CRUD /api/sessions      会话管理
    └─ GET/PUT /api/settings   用户设置
    │
    ├─ core/agent_memory.py    Agent Memory 三层记忆（工作/情景/语义）
    ├─ core/rag_search.py      RAG 混合检索（dense + sparse + rerank）
    ├─ core/rag_index.py       向量索引构建（bge-large-zh-v1.5）
    ├─ core/hallucination_guard.py  防编造（NER + 交叉验证）
    ├─ core/memorial_profile.py     人格画像 + FALLBACK_SYSTEM
    ├─ core/audio_features.py       音频特征提取（f0/语速/RMS）
    └─ core/ocr_service.py          PaddleOCR 服务
    │
    ▼
外部 API
    ├─ DeepSeek API      对话模型
    ├─ 百炼 DashScope    CosyVoice TTS / ASR / OCR 增强
    └─ Edge TTS (微软)   免费 TTS
```

## 二、核心流程：一次聊天请求的完整链路

### 2.1 入口：`POST /api/chat`

```python
@app.post("/api/chat")
async def chat(req: ChatRequest):
    # 1. 获取 Memory Manager（单例）
    mm = get_memory_manager()

    # 2. 加载会话 + 构建记忆上下文
    session = mm.load_session(session_id)
    memory_context = mm.build_chat_context(session_id, last_user)
    #    ├─ working_memory: 最近 10 轮对话
    #    ├─ semantic_facts: 语义记忆（用户偏好/事实）
    #    ├─ session_summary: 长会话的摘要
    #    └─ triggers: 可主动提起的回忆

    # 3. 拼系统提示词
    messages = [{"role": "system", "content": 人格画像}]

    # 4. 注入语义记忆
    if semantic_facts:
        messages.append({"role": "system", "content": "你记得..."})

    # 5. 注入主动记忆触发
    if triggers:
        messages.append({"role": "system", "content": "可以提起..."})

    # 6. 注入风格提示（StyleProfile，基于历史交互）
    if style_hint:
        messages.append({"role": "system", "content": style_hint})

    # 7. 注入情感指导（EmotionDetector）
    if emotion_hint:
        messages.append({"role": "system", "content": emotion_hint})

    # 8. RAG 检索 → 注入风格参考
    rag_ctx = build_rag_context(user_input)
    if rag_ctx:
        messages.append({"role": "system", "content": rag_ctx})

    # 9. 追加工作记忆（最近对话）
    messages.extend(working_memory)

    # 10. 追加用户最新消息
    messages.append({"role": "user", "content": user_input})

    # 11. 调用 LLM
    resp = client.chat.completions.create(model, messages)

    # 12. 输出后校验：Hallucination Guard
    guard_result = guard_reply(raw_reply, rag_chunks)
    if guard_result["status"] == "blocked":
        reply = conservative_reply  # 替换为保守回复

    # 13. 保存到 session（改写影响后续对话）
    mm.save_turn(session_id, user_input, reply)

    return {"reply": reply, "guard_info": guard_result}
```

### 2.2 各个注入层的关系

每层都在 System Prompt 中追加一段纯文本指导，LLM 自己融合所有信息后生成回复：

```
┌─ System Prompt ─────────────────────────────────┐
│                                                  │
│  FALLBACK_SYSTEM（人格画像 base）                │
│  ├─ "你是已逝的用户亲人/朋友"                    │
│  ├─ 绝对禁止：约见面、虚假来世叙事               │
│  └─ 边界：不知道就说不知道                       │
│                                                  │
│  user_supplement（用户编写的补充模板）            │
│                                                  │
├─ Semantic Memory（你记得的事）                   │
│  ├─ 用户搬到了上海                               │
│  └─ 用户养了猫叫咪咪                             │
│                                                  │
├─ Memory Triggers（可以主动提起）                 │
│  ├─ 如果提到"累" → 记得用户喜欢散步              │
│  └─ 注意：不相关不提                             │
│                                                  │
├─ Style Hint（风格偏好）                          │
│  └─ 用 2-3 句中等长度的回复                      │
│                                                  │
├─ Emotion Hint（情感指导）                        │
│  └─ 用户情绪低落，用温柔共情的语气               │
│                                                  │
├─ RAG Context（风格参考）                         │
│  └─ TA 说过："废物"、"行了行了"                 │
└───────────────────────────────────────────────────┘
```

**设计原则**：每层独立注入，LLM 融合。不改彼此的代码，不改输出格式。

## 三、Agent Memory 详解

文件：`core/agent_memory.py`

### 3.1 三层记忆架构

```
┌─────────────────────────────────────────┐
│           Agent Memory                   │
│                                          │
│  L1: Working Memory（工作记忆）          │
│  ├─ 最近 10 轮对话原文                  │
│  ├─ 直接塞入 LLM prompt（token 可见）   │
│  └─ Session 对象管理，内存中             │
│                                          │
│  L2: Episodic Memory（情景记忆）         │
│  ├─ 对话摘要（超过 20 轮自动触发）       │
│  ├─ 永久存储：data/memory/sessions/*.json│
│  └─ LLM 生成摘要文本                     │
│                                          │
│  L3: Semantic Memory（语义记忆）          │
│  ├─ 长期事实（偏好/状态/关系）           │
│  ├─ 永久存储：semantic_memory.json       │
│  ├─ 混合检索（embedding + 关键词）       │
│  └─ 评分衰减机制                          │
└─────────────────────────────────────────┘
```

### 3.2 记忆评分公式

```python
# 每条事实的最终得分
importance = confidence × (0.5 + 0.5 × sigmoid(access_count / 5))
recency = exp(-days_since_last_access / 30)   # 30 天半衰期
final_score = importance × 0.7 + recency × 0.3

# 低于 0.15 的不注入 prompt
# 跨会话同事实出现 → confidence 自动 × 1.05
```

### 3.3 Memory Trigger 原理

```python
def build_triggers(query, top_k=2):
    """检测当前话题与已记忆事实的相关性。"""
    facts = search_facts(query, top_k=top_k*2)
    triggers = []
    for fact in facts:
        if fact.access_count >= 15:  # 提太多不要了
            continue
        score = _score_fact(fact)
        if score >= 0.15:
            triggers.append(fact)
    return triggers[:2]

# 结果注入 system prompt:
# "当你发现当前话题和以下事实相关时，可以自然地提起：
#  - 你记得：用户喜欢去公园散步"
```

### 3.4 StyleProfile 原理

```python
class StyleProfile:
    def record_session_end(turn_count, topics):
        """每 6 轮更新一次，纯本地计算，不调用 LLM。"""
        self.total_sessions += 1
        self.total_turns += turn_count
        avg = self.total_turns / self.total_sessions
        
        # 根据平均轮数推断偏好长度
        if avg <= 3:   preferred = "short"   # 1-2 句
        elif avg <= 8: preferred = "medium"  # 2-3 句
        else:          preferred = "long"    # 适当多说

    def get_style_hint():
        """生成风格提示文本（≥2 sessions 后才生效）。"""
        return f"用 2-3 句中等长度的回复。用户常聊到散步、工作。"
```

### 3.5 EmotionDetector 原理

```python
class EmotionDetector:
    # 纯关键词匹配，零 LLM 调用
    _NEGATIVE = {
        "emo_sad": ["难过", "伤心", "哭了", ...],
        "emo_tired": ["累了", "疲惫", ...],
        "emo_angry": ["生气", "烦", ...],
    }
    _POSITIVE = {
        "emo_happy": ["开心", "高兴", ...],
        "emo_nostalgic": ["记得", "以前", ...],
    }
    
    @classmethod
    def detect(text):
        """扫描文本 → 返回情绪类型 + 语气指导。"""
        for emotion, keywords in all:
            if any(kw in text for kw in keywords):
                hint = {
                    "sad": "用温柔、共情的语气，先接住情绪",
                    "tired": "用平静、温暖的语气，像老朋友关心",
                }[emotion]
                return {"emotion": emotion, "hint": hint}
        return {"emotion": None, "hint": ""}
```

## 四、RAG 检索详解

文件：`core/rag_search.py`

### 4.1 检索流程

```
用户输入: "我想你了"
    │
    ▼
Query 扩展（融入对话上下文）
    │  "用户问：今天累吗？；AI答：是啊…；当前：我想你了"
    ▼
Dense（bge-large-zh embedding）
    ├─ query embedding × 向量矩阵 → 余弦相似度
    │  weight: 0.7
    │
    + Sparse（BM25 关键词）
    ├─ 分词 → TF-IDF → BM25 打分
    │  weight: 0.3
    ▼
Hybrid Score = 0.7 × dense + 0.3 × sparse
    │
    ▼
粗排取 top-2k → 重排序（pair embedding）
    │  rerank_score = 0.6 × base + 0.4 × pair
    │  + 对话连贯性加分（相邻行号同行 +0.05/行）
    ▼
取 top_k → 返回 [{role, text, line_no, score}]
```

### 4.2 索引构建

```python
# core/rag_index.py
def build_index(chat_txt, out_dir):
    # 1. 解析 chat_extracted.txt
    messages = parse_chat(chat_txt)
    #    [对方] xxx → {"role": "对方", "text": "xxx", "line_no": 1}
    
    # 2. 合并相邻消息（可配置窗口）
    chunks = merge_chunks(messages, window=1)
    
    # 3. 生成 embedding 向量
    vectors = bge_model.encode(texts, normalize=True)
    #    shape: (N, 1024)
    
    # 4. 保存到磁盘
    chunks.json + vectors.npy + meta.json
```

## 五、Huccination Guard 详解

文件：`core/hallucination_guard.py`

### 5.1 设计原则

> **宁可保守不答，绝不编造。**

### 5.2 流水线

```
LLM 回复: "我记得你以前在上海的时候，经常去那家奶茶店"
    │
    ▼ 1) NER 实体提取
    ["上海", "奶茶店"]
    │   ├─ 姓名模式：常见姓氏 + 1-3 字中文
    │   ├─ 品牌模式：含英文字母 + 可选中文
    │   ├─ 地点模式：省/市/县/区/街/镇/乡/村/山/河 结尾
    │   └─ 碎片过滤：过滤常见对话碎片
    │
    ▼ 2) 交叉验证
    "上海" → SAFE_WORDS 直接放行 ✅
    "奶茶店" → RAG chunks 中搜索 → 没找到
               → chat_index 全文索引中搜索 → 没找到
               → 子串匹配（前 2-3 字）→ 没找到
               → 未验证 ❌
    │
    ▼ 3) 判断
    1 个未验证（"奶茶店"）+ 1 个验证（"上海"）= 1/2
    ├─ 未验证 ≤ 1 && 总实体 ≥ 3 → warning
    ├─ 全为"专有名词"类型 → warning（降级，不阻断）
    └─ 否则 → blocked（替换保守回复）
```

### 5.3 阻断 vs Warning

| 状态 | 条件 | 行为 |
|------|------|------|
| **ok** | 无未验证实体 | 原样返回 LLM 回复 |
| **warning** | 1 个未验证 + 3+ 总实体；或全专有名词 | 前端标记"部分验证"但**不替换**回复 |
| **blocked** | 多个未验证 | **替换**为随机保守回复 + 前端显示"保守回复"标签 |

## 六、TTS 缓存机制

### 6.1 缓存密钥

```python
cache_key = SHA1(
    engine | voice_id | text | voice | rate | pitch | volume | instruction
)
```

所有影响合成的因素都参与 hash。不同引擎/音色/文本产生不同缓存。

### 6.2 预合成

```
AI 回复返回 → 前台收到文字
    │
    ├─ 如果"预合成"开关打开
    │  └─ 后台 fire-and-forget 调用 POST /api/tts
    │      → 后端合成 + 写入缓存（不返回给前端）
    │
    └─ 用户点击播放
       └─ POST /api/tts（同参数）
           → 缓存命中 → ~100ms 返回 ✅
```

## 七、关键数据流

### 7.1 数据存储位置

| 数据 | 位置 | 格式 |
|------|------|------|
| 人格画像 | data/memorial_profile.json | JSON |
| 用户设置 | data/user_settings.json | JSON |
| 聊天记录 | data/chat_extracted.txt | 纯文本 |
| RAG 索引 | data/rag_index/chunks.json + vectors.npy + meta.json | JSON + NumPy |
| 会话 | data/memory/sessions/*.json | JSON |
| 语义记忆 | data/memory/semantic_memory.json | JSON |
| TTS 缓存 | data/tts_cache/*.mp3 + *.json | MP3 + meta |
| 声音样本 | data/voice_samples/*.wav + samples.json | WAV + JSON |
| Guard 日志 | data/logs/guard_YYYY-MM-DD.txt | 纯文本 |

### 7.2 LLM Token 预算

```
每轮请求 Token 构成：
┌──────────────────────────────────┐
│ System Prompt (人格画像)    1.5K │
│ Semantic Facts             0.1K  │
│ Trigger Hints              0.05K │
│ Style / Emotion Hints      0.05K │
│ RAG Context (~4 chunks)   0.3K  │
│ Working Memory (10 turns)  1-2K  │
│ User Input                 0.05K │
│ LLM Output                 0.3K  │
├──────────────────────────────────┤
│ 合计 ~3.5-4.5K tokens/轮         │
│ DeepSeek v4: ~¥0.005-0.007/轮    │
│ 30 轮对话: ~¥0.15-0.2            │
└──────────────────────────────────┘
```

---

*文档版本: 2026-07-14  ·  对应 MemoirAI v0.2.0*
