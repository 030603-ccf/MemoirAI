# -*- coding: utf-8 -*-
"""
rag_index.py
============
一次性脚本：把聊天记录向量化保存。

流程：
  1. 读取 chat_data/chat_extracted.txt（OCR 提取的纯文本）
  2. 解析每条消息为 {role, text, line_no} 三元组
  3. 调用 bge-large-zh-v1.5 生成 embedding（首跑会下载 ~1.3GB 模型）
  4. 保存到 chat_data/rag_index/：
     - chunks.json  消息列表
     - vectors.npy  embedding 矩阵 (N x 512)
     - meta.json    元信息（模型名、生成时间、条数）

用法：
  python rag_index.py
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np


# ---------- 路径 ----------
# ROOT = 项目根目录（qwen-chat-test/）
# core/rag_index.py → parent.parent = qwen-chat-test/
ROOT = Path(__file__).resolve().parent.parent
CHAT_TXT = ROOT / "data" / "chat_extracted.txt"
INDEX_DIR = ROOT / "data" / "rag_index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)


# ---------- 文本预处理 ----------
LINE_PATTERN = re.compile(r"^\[(本人|对方)]\s*(.+)$")

# 系统消息 / OCR 噪音标记（含这些子串的行直接跳过）
SYSTEM_MARKERS = (
    "通话时长",      # 系统通话记录
    "对方已取消",    # 撤回提示
    "[图片]",        # 图片消息
    "[表情]",        # 表情消息
    "[语音]",        # 语音消息
    "[文件]",        # 文件消息
    "[位置]",        # 位置分享
    "[链接]",        # 链接卡片
)

# 过滤掉这些纯标点 / 表情 / 噪音字符
NOISE_PATTERN = re.compile(r"^[\s\W]+$")  # 只有空格或非字母数字
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")  # 至少含一个中文字符


def is_valid_message(text: str) -> bool:
    """判断一条消息是否值得保留为训练样本。"""
    text = text.strip()
    if len(text) < 2:
        return False
    if any(m in text for m in SYSTEM_MARKERS):
        return False
    if NOISE_PATTERN.match(text):
        return False
    return True


def parse_chat(path: Path) -> list[dict]:
    """解析 chat_extracted.txt 为 [{role, text, line_no}, ...]"""
    chunks = []
    skipped = 0
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            m = LINE_PATTERN.match(line)
            if not m:
                continue
            role, text = m.group(1), m.group(2).strip()
            if not is_valid_message(text):
                skipped += 1
                continue
            chunks.append({
                "role": role,
                "text": text,
                "line_no": i,
            })
    print(f"[parse] {len(chunks)} kept, {skipped} skipped (system/noise)")
    return chunks


def merge_chunks(messages: list[dict], window: int = 3) -> list[dict]:
    """把相邻 window 条消息合并为一个 chunk。

    保留每条消息的角色标签和原文，合并后用换行连接。
    metadata 保留第一条的 line_no 和参与合并的消息数量。
    """
    if window <= 1:
        return messages

    merged = []
    step = max(1, window // 2)  # 滑动步长，避免过度重叠
    i = 0
    while i < len(messages):
        window_msgs = messages[i:i + window]
        if not window_msgs:
            break
        # 合并文本
        text = "\n".join(f"[{m['role']}] {m['text']}" for m in window_msgs)
        line_nos = [m["line_no"] for m in window_msgs]
        merged.append({
            "role": window_msgs[0]["role"],  # 第一条的角色作为主导
            "text": text,
            "line_no": line_nos[0],
            "line_nos": line_nos,           # 所有涉及的行号
            "n_messages": len(window_msgs),  # 合并了几条
            "is_merged": True,
        })
        if i + window >= len(messages):
            break  # 最后不到 window 条也合并进去
        i += step

    print(f"[merge] {len(messages)} messages -> {len(merged)} chunks (window={window}, step={step})")
    return merged


# ---------- embedding ----------
# 可选: BAAI/bge-small-zh-v1.5 (100MB, 512d) | BAAI/bge-base-zh-v1.5 (400MB, 768d) | BAAI/bge-large-zh-v1.5 (1.3GB, 1024d)
MODEL_NAME = "BAAI/bge-large-zh-v1.5"


def build_embeddings(chunks: list[dict]) -> np.ndarray:
    """调用 sentence-transformers 生成 embedding 矩阵 (N x 512)."""
    # 离线优先：避免 SSL 问题。如果本地有缓存就跳过网络
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    from sentence_transformers import SentenceTransformer

    print(f"[embed] loading model {MODEL_NAME} (offline mode)...", flush=True)
    try:
        model = SentenceTransformer(MODEL_NAME, local_files_only=True)
    except Exception as e:
        print(f"[embed] local_files_only failed ({e}), trying fallback to local path...", flush=True)
        # Fallback: 显式指向 HF cache 路径
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        # Search order: HF cache → project models/ → cwd models/
        candidates = [
            Path(os.path.expanduser("~/.cache/huggingface/hub")) / "models--BAAI--bge-large-zh-v1.5" / "snapshots" / "main",
            ROOT / "models" / "BAAI" / "bge-large-zh-v1.5",
            ROOT.parent / "models" / "BAAI" / "bge-large-zh-v1.5",
            Path(os.getcwd()) / "models" / "BAAI" / "bge-large-zh-v1.5",
        ]
        local_path = None
        for c in candidates:
            if c.exists() and (c / "config.json").exists():
                local_path = c
                break
        if local_path:
            model = SentenceTransformer(str(local_path))
        else:
            raise RuntimeError(
                f"Model not found. Searched: {[str(c) for c in candidates]}. "
                "Please run dl_bge_modelscope.py first to download via ModelScope."
            )

    # bge 系列要求：query 加指令前缀，passage 不加
    # 我们是"段落"索引（每次检索时把 user_input 当 query 加前缀）
    texts = [c["text"] for c in chunks]
    print(f"[embed] encoding {len(texts)} chunks...", flush=True)
    t0 = time.time()
    vectors = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,  # L2 归一化，方便后续 cos sim = dot product
        convert_to_numpy=True,
    )
    print(f"[embed] done in {time.time() - t0:.1f}s, shape={vectors.shape}", flush=True)
    return vectors


# ---------- main ----------
def build_index(out_dir: Path = None, merge_window: int = 1) -> dict:
    """建 RAG 向量索引（无 argparse 的纯函数版本，frozen exe 也能 in-process 调）。"""
    import time as _time
    from collections import Counter

    out_dir = Path(out_dir) if out_dir else INDEX_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[index] chat source: {CHAT_TXT}")
    if not CHAT_TXT.exists():
        raise FileNotFoundError(f"chat file not found: {CHAT_TXT}")

    # 1. parse
    messages = parse_chat(CHAT_TXT)
    if not messages:
        raise RuntimeError("no messages parsed, check file format")

    role_count = Counter(m["role"] for m in messages)
    print(f"[parse] roles: {dict(role_count)}")

    # 2. merge
    chunks = merge_chunks(messages, window=merge_window)
    if not chunks:
        raise RuntimeError("no chunks after merging")

    # 3. embed
    vectors = build_embeddings(chunks)

    # 4. save
    np.save(out_dir / "vectors.npy", vectors)
    with (out_dir / "chunks.json").open("w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    meta = {
        "model": MODEL_NAME,
        "vector_dim": int(vectors.shape[1]),
        "num_chunks": len(chunks),
        "merge_window": merge_window,
        "created_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "role_count": dict(role_count),
    }
    with (out_dir / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[index] saved to {out_dir}/")
    print(f"[index] {meta}")
    return meta


def main():
    import argparse
    parser = argparse.ArgumentParser(description="建 RAG 向量索引")
    parser.add_argument(
        "--merge-window", type=int, default=1,
        help="把相邻 N 条消息合并为一个 chunk（默认 1=不合并，推荐 3）",
    )
    parser.add_argument(
        "--out-dir", type=str, default=None,
        help="索引输出目录（默认 data/rag_index/）",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else INDEX_DIR
    build_index(out_dir=out_dir, merge_window=args.merge_window)


if __name__ == "__main__":
    main()