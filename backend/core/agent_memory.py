# -*- coding: utf-8 -*-
"""
agent_memory.py - Agent Memory 三层架构
================================================

参考论文：
  - How Memory Management Impacts LLM Agents (arXiv 2505.16067)
  - Memory for LLM Agents (arXiv 2510.23730)

三层记忆：
  1. Working Memory（工作记忆）= 当前对话上下文，直接塞进 LLM prompt
  2. Episodic Memory（情景记忆）= 具体对话事件，按 session 存文件
  3. Semantic Memory（语义记忆）= 抽象事实/偏好，持久化 JSON

v0.2.0 新增：
  - 记忆评分 + 衰减机制：confidence × 访问系数 × 时效系数
  - 混合检索：embedding 语义相似度 + 关键词 BM25
  - 主动记忆触发：检测到相关话题时，指导 LLM 自然提起回忆
  - 跨会话增强：同件事多次被提取 → 自动加分
"""
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------- 路径 ----------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
SESSIONS_DIR = MEMORY_DIR / "sessions"
SEMANTIC_JSON = MEMORY_DIR / "semantic_memory.json"

# 工作记忆（塞进 LLM prompt 的轮数）
WORKING_MEMORY_TURNS = 10

# 摘要阈值
SUMMARY_THRESHOLD = 20
SUMMARY_KEEP_RECENT = 5

# 记忆衰减参数
MEMORY_IMPORTANCE_WEIGHT = 0.7     # 重要性权重
MEMORY_RECENCY_WEIGHT = 0.3        # 时效性权重
MEMORY_HALF_LIFE_DAYS = 30         # 半衰期（天）
MEMORY_MIN_SCORE = 0.15            # 最低分，低于此的不注入 prompt
MEMORY_TRIGGER_MIN_CONFIDENCE = 0.5  # 触发的最低置信度


def _ensure_dirs():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- 工具 ----------
def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _make_session_id() -> str:
    return f"session_{int(time.time())}_{os.urandom(4).hex()}"


def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokenize(text: str) -> list[str]:
    """简单分词。"""
    stopwords = {"的", "了", "在", "是", "我", "你", "他", "有", "和", "就", "不", "都", "个", "上", "也", "很", "到", "说", "要", "去", "会", "着", "没有", "看", "好", "自己", "这", "那", "啊", "吧", "呢", "吗", "嘛", "嗯", "哦", "哈", "啦"}
    tokens = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" and ch not in stopwords:
            tokens.append(ch)
    for word in re.findall(r"[a-zA-Z0-9]+", text):
        if len(word) >= 2:
            tokens.append(word.lower())
    return tokens


def _sigmoid(x: float) -> float:
    """sigmoid 函数，将值映射到 (0, 1)。"""
    return 1.0 / (1.0 + math.exp(-x))


# ---------- Semantic Memory（语义记忆）----------
class SemanticMemory:
    """持久化的语义记忆：用户偏好、事实、关系。

    存储格式：
    {
        "facts": [
            {
                "id": "f1",
                "content": "用户最近搬到了上海",
                "category": "生活",
                "created_at": "...",
                "updated_at": "...",
                "access_count": 0,          # 被检索命中次数
                "last_accessed": "...",       # 上次命中时间
                "source_sessions": ["s1"],    # 来源会话列表
                "confidence": 0.9,
            },
        ],
    }
    """

    def __init__(self, path: Path = SEMANTIC_JSON):
        self.path = path
        self._data = self._load()
        # 懒加载 bge model 用于语义检索
        self._embed_model = None

    def _load(self) -> dict:
        data = _load_json(self.path, {"facts": [], "version": 2})
        if "facts" not in data:
            data["facts"] = []
        # 兼容旧版本：补全新字段
        for f in data["facts"]:
            if "access_count" not in f:
                f["access_count"] = 0
            if "last_accessed" not in f:
                f["last_accessed"] = f.get("updated_at", f.get("created_at", _now_str()))
            if "source_sessions" not in f:
                f["source_sessions"] = [f.get("source_session", "")] if f.get("source_session") else []
        return data

    def _save(self):
        _save_json(self.path, self._data)

    def add_fact(self, content: str, category: str = "general",
                 source_session: str = "", confidence: float = 0.8) -> dict:
        """添加一条事实。跨会话重复出现时自动增强置信度。"""
        for f in self._data["facts"]:
            if f["content"] in content or content in f["content"]:
                # 跨会话增强
                f["confidence"] = max(f["confidence"], confidence)
                if source_session and source_session not in f["source_sessions"]:
                    f["source_sessions"].append(source_session)
                    # 跨会话加分
                    f["confidence"] = min(1.0, f["confidence"] * (1 + 0.05 * (len(f["source_sessions"]) - 1)))
                f["updated_at"] = _now_str()
                self._save()
                return f

        fact = {
            "id": f"fact_{len(self._data['facts'])+1}",
            "content": content,
            "category": category,
            "created_at": _now_str(),
            "updated_at": _now_str(),
            "access_count": 0,
            "last_accessed": _now_str(),
            "source_sessions": [source_session] if source_session else [],
            "confidence": confidence,
        }
        self._data["facts"].append(fact)
        self._save()
        return fact

    def _get_embedding(self, text: str) -> Optional[list[float]]:
        """用 bge 模型获取文本 embedding（懒加载，复用 RAG 模型）。"""
        if self._embed_model is None:
            try:
                from rag_search import _state as _rag_state
                self._embed_model = _rag_state.get("model")
            except Exception:
                return None
        if self._embed_model is None:
            return None
        try:
            vec = self._embed_model.encode([text], normalize_embeddings=True, convert_to_numpy=True)
            return vec[0].tolist()
        except Exception:
            return None

    def _score_fact(self, fact: dict) -> float:
        """计算一条事实的综合得分，用于排序和过滤。

        公式：final = 重要性(confidence × 访问系数) × 0.7 + 时效系数 × 0.3
        """
        confidence = fact.get("confidence", 0.5)
        access_count = fact.get("access_count", 0)

        # 访问系数：越常被检索越重要（sigmoid 平滑）
        access_bonus = _sigmoid(access_count / 5.0)

        # 重要性
        importance = confidence * (0.5 + 0.5 * access_bonus)

        # 时效系数：最近访问的加分
        try:
            last_accessed = datetime.fromisoformat(fact.get("last_accessed", fact["created_at"]))
            days_ago = (datetime.now() - last_accessed).days
        except Exception:
            days_ago = 999
        recency = math.exp(-days_ago / MEMORY_HALF_LIFE_DAYS)

        return importance * MEMORY_IMPORTANCE_WEIGHT + recency * MEMORY_RECENCY_WEIGHT

    def _update_access(self, fact: dict):
        """更新事实的访问指标。"""
        fact["access_count"] = fact.get("access_count", 0) + 1
        fact["last_accessed"] = _now_str()
        self._save()

    def get_facts(self, category: str = None, min_confidence: float = 0.5) -> list:
        """获取事实列表，按综合分排序。"""
        facts = [f for f in self._data["facts"] if f["confidence"] >= min_confidence]
        if category:
            facts = [f for f in facts if f["category"] == category]
        facts.sort(key=lambda f: self._score_fact(f), reverse=True)
        return facts

    def search_facts(self, query: str, top_k: int = 3) -> list:
        """混合检索语义记忆：embedding 语义相似度 + 关键词匹配。

        Returns: 按综合分排序的事实列表。
        """
        if not query.strip() or not self._data["facts"]:
            return []

        facts = [f for f in self._data["facts"] if f["confidence"] >= MEMORY_TRIGGER_MIN_CONFIDENCE]
        if not facts:
            return []

        # 1) 关键词匹配
        query_terms = set(_tokenize(query))
        kw_scores = []
        for f in facts:
            fact_terms = set(_tokenize(f["content"]))
            overlap = len(query_terms & fact_terms)
            if overlap > 0:
                kw_scores.append(overlap / max(len(query_terms), len(fact_terms), 1))
            else:
                kw_scores.append(0.0)

        # 2) Embedding 语义相似度
        query_vec = self._get_embedding(query)
        emb_scores = []
        if query_vec:
            import numpy as np
            qv = np.array(query_vec)
            for f in facts:
                f_vec = self._get_embedding(f["content"])
                if f_vec:
                    emb_scores.append(float(np.dot(qv, np.array(f_vec))))
                else:
                    emb_scores.append(0.0)
        else:
            emb_scores = [0.0] * len(facts)

        # 3) 混合加权：0.6 语义 + 0.4 关键词
        hybrid = [0.6 * e + 0.4 * k for e, k in zip(emb_scores, kw_scores)]

        # 4) 按综合分调整
        scored = []
        for i, f in enumerate(facts):
            base_score = self._score_fact(f)
            final = (base_score + hybrid[i]) / 2.0
            if final >= MEMORY_MIN_SCORE:
                scored.append((f, final))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [f for f, _ in scored[:top_k]]

        # 5) 更新命中事实的访问指标
        for f in results:
            self._update_access(f)

        return results

    def build_triggers(self, query: str, top_k: int = 2) -> list[dict]:
        """检测当前输入是否能触发某个记忆，返回可被 LLM 自然提及的回忆。

        Returns: [{"content": "...", "category": "...", "score": 0.xx}, ...]
        """
        facts = self.search_facts(query, top_k=top_k * 2)
        triggers = []
        for f in facts:
            if f.get("access_count", 0) >= 15:
                continue  # 提太多次了，不再触发
            score = self._score_fact(f)
            if score >= MEMORY_MIN_SCORE:
                triggers.append({
                    "content": f["content"],
                    "category": f.get("category", "general"),
                    "score": round(score, 3),
                })
        return triggers[:top_k]

    def format_for_prompt(self, facts: list) -> str:
        """把事实格式化成可注入 prompt 的字符串。"""
        if not facts:
            return ""
        lines = ["\n\n# 你记得的关于缅怀者的事（来自之前的对话）"]
        for f in facts:
            lines.append(f"- {f['content']}")
        lines.append("\n当上面这些话题出现时，可以自然地提起你记得的事。")
        return "\n".join(lines)

    def format_triggers_for_prompt(self, triggers: list) -> str:
        """把可触发的回忆格式化成 prompt 指导。"""
        if not triggers:
            return ""
        lines = ["\n# 主动回忆指导"]
        lines.append("当你发现用户当前的话题和你记得的以下某件事高度相关时，")
        lines.append("可以用逝者的语气自然地提起那段回忆（不要生硬，要自然融入对话）：")
        for t in triggers:
            lines.append(f"- 你记得：{t['content']}")
        lines.append("")
        lines.append("注意：如果话题不相关，不要强行提起。不知道或不记得就说不知道。")
        return "\n".join(lines)

    def consolidate_memory(self, min_confidence: float = 0.2,
                           max_facts: int = 200):
        """合并重复事实，清理低置信度条目，不超过上限。"""
        # 1) 移除低置信度
        self._data["facts"] = [f for f in self._data["facts"]
                               if f["confidence"] >= min_confidence]

        # 2) 合并内容高度相似的事实
        # 判断逻辑：
        #   a) 一个包含另一个（子串匹配）
        #   b) 关键词重叠 > 60%（同一主题的不同表述）
        def _similarity(a: str, b: str) -> float:
            a_tokens = set(_tokenize(a))
            b_tokens = set(_tokenize(b))
            if not a_tokens or not b_tokens:
                return 0.0
            intersection = a_tokens & b_tokens
            union = a_tokens | b_tokens
            return len(intersection) / max(len(union), 1)

        merged = []
        for f in sorted(self._data["facts"], key=lambda x: self._score_fact(x), reverse=True):
            is_dup = False
            for existing in merged:
                # Exact substring match
                if f["content"] in existing["content"] or existing["content"] in f["content"]:
                    is_dup = True
                # High keyword overlap (same topic, different phrasing)
                elif _similarity(f["content"], existing["content"]) > 0.4:
                    is_dup = True
                if is_dup:
                    existing["confidence"] = max(existing["confidence"], f["confidence"])
                    existing["source_sessions"] = list(set(existing["source_sessions"] + f["source_sessions"]))
                    existing["access_count"] = max(existing["access_count"], f["access_count"])
                    break
            if not is_dup:
                merged.append(f)

        # 3) 截断到上限
        if len(merged) > max_facts:
            merged = merged[:max_facts]

        self._data["facts"] = merged
        self._save()
        return len(merged)


# ---------- Episodic Memory（情景记忆）----------
class Session:
    """单个对话会话。"""

    def __init__(self, session_id: str, data: dict = None):
        self.id = session_id
        self._data = data or {}

    @property
    def title(self) -> str:
        return self._data.get("title", "未命名对话")

    @title.setter
    def title(self, val: str):
        self._data["title"] = val

    @property
    def created_at(self) -> str:
        return self._data.get("created_at", _now_str())

    @property
    def updated_at(self) -> str:
        return self._data.get("updated_at", _now_str())

    @property
    def turns(self) -> list:
        return self._data.get("turns", [])

    @property
    def summary(self) -> str:
        return self._data.get("summary", "")

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def add_turn(self, role: str, content: str):
        self._data.setdefault("turns", []).append({
            "role": role,
            "content": content,
            "timestamp": _now_str(),
        })
        self._data["updated_at"] = _now_str()
        if self._data.get("title") in ("", "未命名对话", None):
            user_msgs = [t["content"] for t in self.turns if t["role"] == "user"]
            if user_msgs:
                title = user_msgs[0][:20] + "..." if len(user_msgs[0]) > 20 else user_msgs[0]
                self._data["title"] = title

    def set_summary(self, summary: str):
        self._data["summary"] = summary
        self._data["summary_at"] = _now_str()

    def get_recent_turns(self, n: int = WORKING_MEMORY_TURNS) -> list:
        return self.turns[-n:] if self.turns else []

    def get_older_turns(self, n: int = SUMMARY_KEEP_RECENT) -> list:
        if len(self.turns) <= n:
            return []
        return self.turns[:-n]

    def to_dict(self) -> dict:
        return self._data

    def save(self, path: Path = None):
        if path is None:
            path = SESSIONS_DIR / f"{self.id}.json"
        _save_json(path, self._data)

    @classmethod
    def load(cls, session_id: str) -> Optional["Session"]:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        data = _load_json(path, {})
        return cls(session_id, data)


# ---------- Memory Manager（统一管理）----------
class MemoryManager:
    """统一记忆管理器：整合工作记忆、情景记忆、语义记忆。"""

    def __init__(self):
        _ensure_dirs()
        self.semantic = SemanticMemory()

    # ---- Session 管理 ----
    def create_session(self, title: str = "") -> Session:
        sid = _make_session_id()
        data = {
            "id": sid,
            "title": title or "未命名对话",
            "created_at": _now_str(),
            "updated_at": _now_str(),
            "turns": [],
            "summary": "",
        }
        session = Session(sid, data)
        session.save()
        return session

    def load_session(self, session_id: str) -> Optional[Session]:
        return Session.load(session_id)

    def list_sessions(self, limit: int = 50) -> list[Session]:
        sessions = []
        for p in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            sid = p.stem
            s = Session.load(sid)
            if s:
                sessions.append(s)
        return sessions[:limit]

    def delete_session(self, session_id: str) -> bool:
        path = SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ---- 工作记忆构建 ----
    def build_chat_context(self, session_id: str, user_input: str) -> dict:
        """为当前查询构建完整的聊天上下文。

        返回：{
            "session_id": str,
            "working_memory": list[dict],  # 最近 N 轮
            "session_summary": str,         # 会话摘要
            "semantic_facts": list,         # 相关语义记忆
            "triggers": list,               # NEW: 可触发的主动回忆
        }
        """
        session = self.load_session(session_id)
        if session is None:
            return {"session_id": session_id, "working_memory": [],
                    "session_summary": "", "semantic_facts": [], "triggers": []}

        working = session.get_recent_turns(WORKING_MEMORY_TURNS)
        summary = session.summary
        semantic_facts = self.semantic.search_facts(user_input, top_k=3)
        triggers = self.semantic.build_triggers(user_input, top_k=2)

        return {
            "session_id": session_id,
            "working_memory": working,
            "session_summary": summary,
            "semantic_facts": semantic_facts,
            "triggers": triggers,
        }

    # ---- 对话回合保存 ----
    def save_turn(self, session_id: str, user_msg: str, assistant_reply: str):
        session = self.load_session(session_id)
        if session is None:
            return
        session.add_turn("user", user_msg)
        session.add_turn("assistant", assistant_reply)
        session.save()

    # ---- 摘要 ----
    def summarize_session(self, session_id: str, llm_client, model: str) -> str:
        session = self.load_session(session_id)
        if session is None:
            return ""
        older = session.get_older_turns(SUMMARY_KEEP_RECENT)
        if not older:
            return session.summary
        formatted = "\n".join(f"{'用户' if t['role']=='user' else 'AI'}: {t['content']}" for t in older)
        prompt = f"""请把以下对话摘要成一段简洁的文字，保留关键事实和情感基调。

对话：
{formatted}

要求：
1. 用第三人称，简洁（100字以内）
2. 保留：用户提到的关键事实、情感状态、重要请求
3. 不保留：日常寒暄、重复内容
4. 格式：纯文本，不需要标题

摘要："""
        try:
            from openai import OpenAI
            if isinstance(llm_client, OpenAI):
                r = llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=0.3,
                )
                summary = (r.choices[0].message.content or "").strip()
                session.set_summary(summary)
                session.save()
                return summary
        except Exception as e:
            print(f"[memory] summarize failed: {e}", flush=True)
        return session.summary

    # ---- 语义记忆提取 ----
    def extract_semantic_facts(self, session_id: str, llm_client, model: str) -> list:
        """从最近几轮对话中提取值得长期记忆的事实。"""
        session = self.load_session(session_id)
        if session is None:
            return []
        recent = session.get_recent_turns(6)
        if not recent:
            return []
        formatted = "\n".join(f"{'用户' if t['role']=='user' else 'AI'}: {t['content']}" for t in recent)
        prompt = f"""请从以下对话中提取值得长期记忆的关键事实。
只提取真正重要的、与"缅怀者的生活状态/偏好/关系"相关的信息。
日常寒暄、重复内容、不重要的细节不需要提取。

对话：
{formatted}

请返回 JSON 数组，格式如下：
[{{"content": "用户最近搬到了上海", "category": "生活"}}]

category 可选：生活、情感、家庭、工作、健康、兴趣、其他

如果没有什么值得提取的，返回 []。

只返回 JSON，不要其他文字。"""

        facts = []
        try:
            from openai import OpenAI
            if isinstance(llm_client, OpenAI):
                try:
                    r = llm_client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=300,
                        temperature=0.3,
                        response_format={"type": "json_object"},
                    )
                except Exception:
                    r = llm_client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=300,
                        temperature=0.3,
                    )
                raw = r.choices[0].message.content or "[]"
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = data.get("facts", [])
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "content" in item:
                            self.semantic.add_fact(
                                content=item["content"],
                                category=item.get("category", "general"),
                                source_session=session_id,
                                confidence=0.8,
                            )
                            facts.append(item)
        except Exception as e:
            print(f"[memory] extract facts failed: {e}", flush=True)
        return facts

    # ---- 记忆维护 ----
    def consolidate_all(self):
        """整理所有记忆：合并、清理、去重。"""
        return self.semantic.consolidate_memory()


# ---------- StyleProfile（风格进化）----------
STYLE_PROFILE_PATH = MEMORY_DIR / "style_profile.json"

class StyleProfile:
    """追踪用户交互模式，渐进式调整回复风格。

    存储用户的行为信号，生成"风格提示"注入到 system prompt 中，
    让 AI 的回复在保持逝者身份的前提下，越来越贴近用户的习惯偏好。
    所有数据本地存储。
    """

    def __init__(self, path: Path = STYLE_PROFILE_PATH):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        default = {
            "total_sessions": 0,
            "total_turns": 0,
            "avg_turns_per_session": 0.0,
            "preferred_length": "medium",  # short / medium / long
            "common_topics": [],
            "updated_at": _now_str(),
        }
        return _load_json(self.path, default)

    def _save(self):
        _save_json(self.path, self._data)

    def record_session_end(self, turn_count: int, topics: list[str] = None):
        """在每次对话结束后调用，更新风格画像。"""
        self._data["total_sessions"] += 1
        self._data["total_turns"] += turn_count
        self._data["avg_turns_per_session"] = round(
            self._data["total_turns"] / max(self._data["total_sessions"], 1), 1
        )

        # 根据平均轮数推断偏好长度
        avg = self._data["avg_turns_per_session"]
        if avg <= 3:
            self._data["preferred_length"] = "short"
        elif avg <= 8:
            self._data["preferred_length"] = "medium"
        else:
            self._data["preferred_length"] = "long"

        if topics:
            for t in topics:
                existing = next((x for x in self._data["common_topics"] if x["topic"] == t), None)
                if existing:
                    existing["count"] += 1
                else:
                    self._data["common_topics"].append({"topic": t, "count": 1})
            self._data["common_topics"].sort(key=lambda x: x["count"], reverse=True)
            self._data["common_topics"] = self._data["common_topics"][:10]

        self._data["updated_at"] = _now_str()
        self._save()

    def get_style_hint(self) -> str:
        """生成风格提示文本，注入到 system prompt 中。"""
        if self._data["total_sessions"] < 2:
            return ""

        hints = []

        # 回复长度偏好
        length_map = {
            "short": "用 1-2 句短答，简洁直接，",
            "medium": "用 2-3 句中等长度的回复，",
            "long": "可以适当多说一些，",
        }
        hints.append(length_map.get(self._data["preferred_length"], ""))

        # 常见话题偏好
        top_topics = [t for t in self._data.get("common_topics", []) if t["count"] >= 2]
        if top_topics:
            topics_str = "、".join(t["topic"] for t in top_topics[:3])
            hints.append(f"用户常聊到 {topics_str}，可适当回应这些话题")

        if not hints:
            return ""

        return "。".join(hints) + "。"


# ---------- EmotionDetector（情感智能）----------
class EmotionDetector:
    """检测用户输入中的情绪信号，生成语气指导。

    用关键词 + 规则匹配，不走 LLM，零 token 成本。
    只在检测到显著情绪时才生成提示，保持逝者身份自然的回应。
    """

    # 消极情绪关键词
    _NEGATIVE = {
        "emo_sad": ["难过", "伤心", "悲伤", "痛苦", "心碎", "哭了", "流泪", "失望",
                    "孤独", "寂寞", "想你了", "想你", "怀念", "思念", "回忆"],
        "emo_tired": ["累了", "疲惫", "疲惫不堪", "没劲", "没精神", "好累"],
        "emo_angry": ["生气", "愤怒", "烦", "烦躁", "讨厌", "恨", "恶心"],
        "emo_anxious": ["焦虑", "担心", "不安", "害怕", "紧张", "压力"],
        "emo_lost": ["迷茫", "不知道怎么办", "无助", "没有方向", "不知所措"],
    }

    # 积极情绪关键词
    _POSITIVE = {
        "emo_happy": ["开心", "高兴", "快乐", "幸福", "美好", "感动", "温暖",
                      "谢谢", "感谢", "真好", "太好了"],
        "emo_nostalgic": ["记得", "那时候", "以前", "以前我们", "当年", "回忆",
                          "想起", "小时候"],
    }

    # 强度修饰词
    _INTENSIFIERS = ["很", "非常", "特别", "好", "太", "真", "有点", "有些", "总是"]

    @classmethod
    def detect(cls, text: str) -> dict:
        """检测输入文本中的情绪。

        Returns: {
            "emotion": "sad" | "tired" | "angry" | "anxious" | "happy" | "nostalgic" | None,
            "intensity": 1 | 2 | 3,
            "hint": str  # 语气提示文本
        }
        """
        if not text:
            return {"emotion": None, "intensity": 0, "hint": ""}

        # 检查强度
        has_intensifier = any(w in text for w in cls._INTENSIFIERS)
        intensity = 1

        # 匹配负面情绪
        for emo, keywords in cls._NEGATIVE.items():
            for kw in keywords:
                if kw in text:
                    if has_intensifier:
                        intensity = 3
                    elif intensity == 1:
                        intensity = 2

                    hint_map = {
                        "emo_sad": "用户情绪低落，用温柔、共情的语气，先接住情绪再缓缓带出希望",
                        "emo_tired": "用户感到疲惫，用平静、温暖的语气，无需说教，像老朋友一样轻描淡写地关心",
                        "emo_angry": "用户情绪激动，用沉稳、平和的语气，不要讲道理，先倾听",
                        "emo_anxious": "用户感到焦虑，用安定、从容的语气，不急不缓，给人安全感",
                        "emo_lost": "用户感到迷茫，用坚定但不强势的语气，陪着想想",
                        "emo_nostalgic": "用户正在回忆过去，用温和、带温度的语气，自然地一起回忆",
                        "emo_happy": "用户心情不错，用轻快的语气回应，分享喜悦",
                    }
                    emo_type = emo.replace("emo_", "")
                    return {
                        "emotion": emo_type,
                        "intensity": intensity,
                        "hint": hint_map.get(emo, ""),
                    }

        # 匹配正面情绪
        for emo, keywords in cls._POSITIVE.items():
            for kw in keywords:
                if kw in text:
                    hint_map = {
                        "emo_nostalgic": "用户正在回忆过去，用温和、带温度的语气，自然地一起回忆",
                        "emo_happy": "用户心情不错，用轻快的语气回应，分享喜悦",
                    }
                    emo_type = emo.replace("emo_", "")
                    return {
                        "emotion": emo_type,
                        "intensity": intensity + (1 if has_intensifier else 0),
                        "hint": hint_map.get(emo, ""),
                    }

        return {"emotion": None, "intensity": 0, "hint": ""}
