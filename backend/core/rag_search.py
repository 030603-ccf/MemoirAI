# -*- coding: utf-8 -*-
"""
rag_search.py
=============
检索接口：输入 query，返回 top-k 相关 chunks。

用法：
  from rag_search import search
  results = search("想你了", top_k=3, role_filter="对方")
  for r in results:
      print(r["role"], r["text"], r["score"])
"""
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np


# ---------- 路径 ----------
# ROOT = 项目根目录（qwen-chat-test/）
# core/rag_search.py → parent.parent = qwen-chat-test/
ROOT = Path(__file__).resolve().parent.parent
# 索引目录：优先用环境变量 INDEX_DIR（用于 A/B 对比），否则默认 data/rag_index/
INDEX_DIR = Path(os.environ.get("INDEX_DIR", str(ROOT / "data" / "rag_index")))


# ---------- 懒加载 ----------
_state = {
    "model": None,
    "chunks": None,
    "vectors": None,
}


def _find_local_model_path(model_name: str) -> str:
    """Find HF cache snapshot dir for a given model name (works offline).

    Search order:
      1. Windows HF cache (~/.cache/huggingface/hub/...)
      2. Windows ModelScope cache
      3. WSL HF cache via \\wsl$\<distro>\... (auto-detected)
      4. WSL ModelScope cache
    """
    from pathlib import Path
    import os
    import re

    repo_dir_name = "models--" + model_name.replace("/", "--")

    # Build all candidate paths (Windows-side + WSL-side)
    candidates = []

    # Windows user home (may differ from WSL user)
    win_home = Path(os.path.expanduser("~"))
    candidates += [
        win_home / ".cache" / "huggingface" / "hub" / repo_dir_name / "snapshots" / "main",
        win_home / ".cache" / "modelscope" / "hub" / model_name,
    ]

    # Local project models/ directories (same structure as HF snapshot)
    ROOT = Path(__file__).resolve().parent.parent  # qwen-chat-test/
    repo_short = model_name.split("/")[-1]  # "bge-large-zh-v1.5"
    candidates += [
        ROOT / "models" / model_name,                 # qwen-chat-test/models/BAAI/bge-large-zh-v1.5/
        ROOT.parent / "models" / model_name,           # project_root/models/BAAI/bge-large-zh-v1.5/
        Path(os.getcwd()) / "models" / model_name,     # cwd/models/BAAI/bge-large-zh-v1.5/
        ROOT / "utils" / "models" / model_name,        # utils/models/BAAI/bge-large-zh-v1.5/
    ]

    # WSL caches via \\wsl$ UNC paths
    wsl_distros = []
    if os.name == "nt":
        wsl_root = Path(r"\\wsl$")
        if wsl_root.exists():
            for d in wsl_root.iterdir():
                if d.is_dir():
                    wsl_distros.append(d)

    for distro in wsl_distros:
        # Conventional WSL layout: <distro>\home\<user>\.cache\...
        candidates += [
            distro / "home" / "Administrator" / ".cache" / "huggingface" / "hub" / repo_dir_name / "snapshots" / "main",
            distro / "home" / "Administrator" / ".cache" / "modelscope" / "hub" / model_name,
        ]

    # Also support Linux paths directly (when run inside WSL/Linux)
    candidates += [
        Path("/home/Administrator/.cache/huggingface/hub") / repo_dir_name / "snapshots" / "main",
        Path("/home/Administrator/.cache/modelscope/hub") / model_name,
    ]

    for c in candidates:
        try:
            if c.exists() and (c / "config.json").exists():
                return str(c)
        except (OSError, PermissionError):
            continue

    # 回退：返回 model name（会触发网络，但保持原行为）
    return model_name


# 在测试或简单调用时，可临时切换模型版本
# （默认从 environment variable RAG_EMBED_MODEL 读，否则用 bge-large）
ACTIVE_MODEL_NAME = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-large-zh-v1.5")


def _ensure_loaded():
    """首次调用时加载模型、索引。后续复用。"""
    if _state["model"] is None:
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        from sentence_transformers import SentenceTransformer
        with (INDEX_DIR / "meta.json").open("r", encoding="utf-8") as f:
            meta = json.load(f)

        # 优先用 meta 里记录的模型（确保 chunks 和 embeddings 是同一模型出来的）
        # 如不一致会报警告
        model_to_load = meta["model"]
        if model_to_load != ACTIVE_MODEL_NAME:
            print(f"[rag] WARNING: index built with {model_to_load}, "
                  f"but ACTIVE_MODEL_NAME={ACTIVE_MODEL_NAME}", flush=True)
            print(f"[rag] falling back to index's model: {model_to_load}", flush=True)

        local_path = _find_local_model_path(model_to_load)
        print(f"[rag] loading model from {local_path}...", flush=True)
        _state["model"] = SentenceTransformer(local_path)
        _state["chunks"] = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
        _state["vectors"] = np.load(INDEX_DIR / "vectors.npy")
        print(f"[rag] indexed {meta['num_chunks']} chunks (dim={meta['vector_dim']})", flush=True)
    return _state["model"], _state["chunks"], _state["vectors"]


# ---------- Query 扩展：融入对话上下文 ----------
def _expand_query(query: str, history: Optional[list[dict]]) -> str:
    """把用户 query 用最近对话上下文扩展，提高检索相关性。"""
    if not history or len(history) < 2:
        return query

    # 取最近 2-3 轮对话
    recent = history[-4:]  # 最多 2 轮（user + assistant）
    context_parts = []
    for msg in recent:
        if msg.get("role") == "user":
            context_parts.append(f"用户问：{msg.get('content', '')}")
        elif msg.get("role") == "assistant":
            context_parts.append(f"AI答：{msg.get('content', '')}")

    if context_parts:
        return f"{'；'.join(context_parts)}；当前问题：{query}"
    return query


# ---------- BM25 稀疏检索 ----------
_STOPWORDS = {
    "的", "了", "在", "是", "我", "你", "他", "她", "有", "和", "就",
    "不", "人", "都", "一个", "上", "也", "很", "到", "说", "要",
    "去", "会", "着", "没有", "看", "好", "自己", "这", "那", "啊",
    "吧", "呢", "吗", "嘛", "嗯", "哦", "哈", "啦",
}


def _tokenize(text: str) -> list[str]:
    """简单分词：中文按字，英文按空格，过滤停用词。"""
    tokens = []
    # 中文按字
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if ch not in _STOPWORDS:
                tokens.append(ch)
    # 英文/数字词
    for word in re.findall(r"[a-zA-Z0-9]+", text):
        if len(word) >= 2 and word.lower() not in ("the", "and", "for"):
            tokens.append(word.lower())
    return tokens


def _bm25_score(query: str, chunks: list[dict]) -> np.ndarray:
    """简化的 BM25 关键词打分。"""
    query_terms = set(_tokenize(query))
    if not query_terms:
        return np.zeros(len(chunks))

    # 计算 IDF
    N = len(chunks)
    df = {}
    for c in chunks:
        text_terms = set(_tokenize(c["text"]))
        for t in query_terms:
            if t in text_terms:
                df[t] = df.get(t, 0) + 1

    idf = {}
    for t in query_terms:
        idf[t] = math.log((N - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5) + 1.0)

    # 对每个 chunk 打分
    scores = np.zeros(N)
    k1 = 1.5
    b = 0.75
    avgdl = sum(len(c["text"]) for c in chunks) / max(N, 1)

    for i, c in enumerate(chunks):
        text = c["text"]
        text_terms = _tokenize(text)
        term_freq = {}
        for t in text_terms:
            term_freq[t] = term_freq.get(t, 0) + 1

        score = 0.0
        for t in query_terms:
            if t not in term_freq:
                continue
            tf = term_freq[t]
            dl = len(text)
            denom = tf + k1 * (1 - b + b * dl / avgdl)
            score += idf.get(t, 0) * (tf * (k1 + 1)) / max(denom, 1e-6)
        scores[i] = score

    # 归一化到 [0, 1]
    if scores.max() > 0:
        scores = scores / scores.max()
    return scores


# ---------- 重排序 ----------
def _rerank(query: str, expanded_query: str, chunks: list[dict], indices: np.ndarray, base_scores: np.ndarray) -> list[tuple[int, float]]:
    """重排序：用更精细的语义匹配提升 top 结果质量。

    策略：
      1. 对粗排结果用 pair embedding 做语义相似度
      2. 加入"对话连贯性"加分：如果 chunk 是连续对话的一部分，加分
      3. 融合：base 0.6 + pair 0.4
    """
    model = _state["model"]
    results = []

    # 取粗排候选的文本
    candidates = [chunks[i]["text"] for i in indices]

    if not candidates:
        return []

    # pair embedding: query + chunk 拼接后的语义相似度
    pair_texts = [f"{expanded_query} [SEP] {c}" for c in candidates]
    pair_vecs = model.encode(pair_texts, normalize_embeddings=True, convert_to_numpy=True)
    query_vec = model.encode(
        [f"为这个句子生成表示以用于检索相关文章：{expanded_query}"],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0]

    # 计算 pair 相似度
    pair_scores = pair_vecs @ query_vec

    # 融合：base 0.6 + pair 0.4
    combined_scores = 0.6 * base_scores[indices] + 0.4 * pair_scores

    # 对话连贯性加分：如果相邻 chunk 也被选中，说明是一段完整对话
    for idx_pos, idx in enumerate(indices):
        bonus = 0.0
        line_no = chunks[idx].get("line_no", 0)
        for other_idx in indices:
            if other_idx == idx:
                continue
            other_line = chunks[other_idx].get("line_no", 0)
            if abs(other_line - line_no) <= 3:  # 相邻 3 行内
                bonus += 0.05
        combined_scores[idx_pos] += min(bonus, 0.15)  # 上限 0.15

    # 组装结果
    for idx_pos, idx in enumerate(indices):
        results.append((idx, float(combined_scores[idx_pos])))

    # 按分数降序
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ---------- 检索增强（hybrid + 重排序 + 上下文感知） ----------
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def search(
    query: str,
    top_k: int = 3,
    role_filter: Optional[str] = None,
    min_score: float = 0.30,
    conversation_history: Optional[list[dict]] = None,
) -> list[dict]:
    """增强版检索：hybrid search + 多轮上下文 + 重排序。

    参数：
        query:       用户输入或检索关键词
        top_k:       返回数量（默认 3）
        role_filter: 只保留指定角色，"本人" / "对方" / None（不限）
        min_score:   相似度阈值，低于此分数的结果会被过滤掉
        conversation_history: 最近几轮对话历史（用于上下文感知检索）

    返回：
        list of dict: [{role, text, line_no, score, source, verified}, ...] 按分数降序
    """
    if not query.strip():
        return []

    model, chunks, vectors = _ensure_loaded()

    # --- 1. Query 改写：融入最近对话上下文 ---
    expanded_query = _expand_query(query, conversation_history)

    # --- 2. Dense retrieval（向量检索）---
    query_vec = model.encode(
        [QUERY_PREFIX + expanded_query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0]

    # cos sim = dot product（已 L2 归一化）
    dense_scores = vectors @ query_vec  # shape: (N,)

    # --- 3. Sparse retrieval（关键词匹配，BM25 简化版）---
    sparse_scores = _bm25_score(expanded_query, chunks)

    # --- 4. Hybrid fusion：dense + sparse 加权融合 ---
    alpha = 0.7  # dense 权重
    hybrid_scores = alpha * dense_scores + (1 - alpha) * sparse_scores

    # 过滤角色
    if role_filter:
        mask = np.array([c["role"] == role_filter for c in chunks])
        hybrid_scores = np.where(mask, hybrid_scores, -1.0)

    # --- 5. 粗排取 top-2k ---
    coarse_top_k = min(top_k * 4, len(chunks))
    coarse_idx = np.argsort(-hybrid_scores)[:coarse_top_k]

    # --- 6. 重排序 ---
    reranked = _rerank(query, expanded_query, chunks, coarse_idx, hybrid_scores)

    # --- 7. 取最终 top_k ---
    results = []
    for idx, score in reranked[:top_k]:
        s = float(score)
        if s < min_score:
            continue
        c = chunks[idx]
        results.append({
            "role": c["role"],
            "text": c["text"],
            "line_no": c.get("line_no", 0),
            "score": round(s, 4),
            "source": "rag",
            "verified": True,  # RAG 检索到的都是真实记录
        })
    return results


# 兼容旧接口：原始 search 函数签名保留
# 旧调用方式仍可用（不传的参数会用默认值）

# ---------- 格式化 ----------
def format_for_prompt(results: list[dict]) -> str:
    """把检索结果格式化成可注入 system 的字符串。"""
    if not results:
        return ""
    lines = ["\n\n**参考聊天片段**（来自真实对话，用于还原说话风格，仅供参考不要照抄）："]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r['role']}] {r['text']}")
    return "\n".join(lines)


# ---------- CLI 测试 ----------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rag_search.py <query> [top_k]")
        sys.exit(1)
    q = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"query: {q}\n")
    results = search(q, top_k=k)
    for r in results:
        print(f"  [{r['role']}] ({r['score']:.3f}) {r['text']}")
    if not results:
        print("  (no matches above threshold)")
