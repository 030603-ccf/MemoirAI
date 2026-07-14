# -*- coding: utf-8 -*-
"""
regenerate_profile.py
====================
无交互版本的 system_prompt 重新生成器：
- 输入：现有 profile（self_reference/relationship 等）+ chat_extracted.txt
- 输出：完整的 memorial_profile.json 字段（含 system_prompt）
- 用于：用户在 Web UI 改完称呼/关系后，点"重新生成画像"按钮调用

不依赖 input()，纯函数式，供后端 API 调用。
"""
import json
import re
import sys
from pathlib import Path

# 复用 setup_memorial.py 的核心工具
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from setup_memorial import EXTRACTION_PROMPT, truncate_chat_records, parse_json  # noqa: E402


def build_user_info(profile: dict) -> str:
    """把现有 profile 字段组装成 setup_memorial.py 需要的 user_info 字符串。"""
    name = profile.get("name") or profile.get("self_reference") or "TA"
    relationship = profile.get("relationship") or "未填写"
    user_ref = profile.get("user_reference") or "你"
    boundary = profile.get("boundary") or "2"

    # 把多字段补充信息拼起来
    extras = []
    if profile.get("personality_traits"):
        extras.append(f"已知性格特征：{'、'.join(profile['personality_traits'])}")
    if profile.get("catchphrases"):
        extras.append(f"已知口头禅：{'、'.join(profile['catchphrases'])}")
    if profile.get("key_memories"):
        extras.append(f"已知共同回忆：{'、'.join(profile['key_memories'])}")
    if profile.get("speaking_style"):
        extras.append(f"已知说话风格：{profile['speaking_style']}")
    if profile.get("emotional_patterns"):
        extras.append(f"已知情绪模式：{profile['emotional_patterns']}")
    extra = "\n".join(extras) if extras else "无"

    return f"""称呼：{name}
关系：{relationship}
对缅怀者的称呼：{user_ref}
边界风格：{boundary}（1=沉浸式，2=回忆口吻，3=二者皆可）
补充：
{extra}
"""


def regenerate_profile(client, model: str, profile: dict, chat_text: str, extra_body: dict | None = None) -> dict:
    """调 LLM 重新生成完整 profile（含 system_prompt）。"""
    if len(chat_text.strip()) < 50:
        raise ValueError(f"chat text too short ({len(chat_text)} chars)")

    user_info = build_user_info(profile)
    prompt = EXTRACTION_PROMPT.format(
        user_info=user_info,
        chat_records=truncate_chat_records(chat_text),
    )

    kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )
    if extra_body:
        kwargs["extra_body"] = extra_body

    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content.strip()
    new_profile = parse_json(text)

    # 字段兜底：保留用户最新填的称呼 / 关系（LLM 可能改）
    new_profile["name"] = (
        profile.get("self_reference")
        or profile.get("name")
        or new_profile.get("name")
        or "TA"
    )
    new_profile.setdefault("relationship", profile.get("relationship", "未填写"))
    new_profile.setdefault("self_reference", profile.get("self_reference", "TA"))
    new_profile.setdefault("user_reference", profile.get("user_reference", "你"))
    new_profile.setdefault("boundary", profile.get("boundary", "2"))
    new_profile.setdefault("few_shots", profile.get("few_shots", []))

    return new_profile