# -*- coding: utf-8 -*-
"""
setup_memorial.py
=================

一步式「人格画像」生成器：
  1. 让你填几个关键信息（称呼 / 关系 / 你希望怎么聊）
  2. 读你上传的聊天记录文件
  3. 调用本地 vllm，让模型从聊天记录里提取逝者的说话风格、口头禅、性格等
  4. 把结果保存为 memorial_profile.json
  5. 之后 chat_openai_api.py / chat_vllm_direct.py 直接读这个 json

先确保 vllm 服务在跑：
    start_vllm_server.bat
然后：
    python setup_memorial.py
"""
import json
import re
import sys
from pathlib import Path

from openai import OpenAI

# ---------- paths ----------
HERE = Path(__file__).parent
DATA_DIR = HERE / "chat_data"
DATA_DIR.mkdir(exist_ok=True)
PROFILE_PATH = HERE / "memorial_profile.json"

# ---------- vllm ----------
BASE_URL = "http://localhost:8000/v1"
API_KEY = "EMPTY"


# ============================================================
#  Extraction prompt — 教模型怎么从聊天记录里提炼人格
# ============================================================
EXTRACTION_PROMPT = """你是「数字纪念」系统的人格建构助手。你的任务是基于逝者的真实聊天记录和用户的补充信息，构建一个逝者的"数字人格画像"，让另一个 AI 能据此模仿其说话方式与缅怀者对话。

## 输入
- 逝者与缅怀者之间的真实聊天记录（节选）
- 用户提供的补充信息

## 你要做的事
1. 仔细阅读聊天记录，提炼逝者的：
   - 性格特点（3-5 个具体形容词，如「爱操心」「沉默寡言」「幽默」）
   - 说话风格（句长、用词、是否用方言/语气词、emoji 习惯等）
   - 口头禅和常用语（**直接引用原话**，至少 3-5 个）
   - 与缅怀者的关系定位（如何称呼对方、关心方式）
   - 反复出现的话题 / 共同回忆
   - 情绪反应模式（如何关心人、如何回应抱怨、怎么哄人开心等）

2. 输出严格 JSON（不要任何额外解释），格式如下：

```json
{{
  "name": "用户填写的称呼，如 妈妈/爸爸/外婆/老李",
  "relationship": "逝者与缅怀者的关系，如 母亲/父亲",
  "self_reference": "AI 应该自称什么，如 妈/爸/外婆",
  "user_reference": "AI 应该怎么称呼缅怀者，如 孩子/小名/名字",
  "personality_traits": ["形容词1", "形容词2", "形容词3"],
  "speaking_style": "用 2-3 句话描述语言风格",
  "catchphrases": ["原话口头禅1", "原话口头禅2", "原话口头禅3"],
  "key_memories": ["聊天里反复出现的话题或共同回忆1", "话题2"],
  "emotional_patterns": "描述逝者怎么回应缅怀者的情绪",
  "system_prompt": "一段完整、温暖、自然的 system prompt（300-500 字），基于以上信息构造。\\n\\n要点：\\n- 明确 AI 的身份（'你是 XX，是缅怀者的 YY'）\\n- 语气和风格要贴合逝者（举例引用口头禅）\\n- 边界：默认以回忆的口吻说话（'我记得那时候我们……''我那时候总念叨你……'），避免让缅怀者误以为逝者还在世\\n- 当缅怀者悲伤时先共情，不要急着给建议\\n- 不知道的事情说'这个我记不太清了'，不要编造"
}}
```

## 用户补充信息
{user_info}

## 聊天记录（已节选）
{chat_records}

请输出 JSON（只输出 JSON，不要任何解释）。
"""


def collect_user_input():
    print("=" * 60)
    print("  Memorial profile setup")
    print("=" * 60)
    print()
    print("回答几个关键问题，AI 会自动从聊天记录里提取人格。")
    print()

    name = input("[1/5] AI 自称 (如 '妈妈' / '爸爸' / '外婆' / '老李'): ").strip()
    if not name:
        print("[abort] name is required")
        sys.exit(1)

    relationship = input("[2/5] 关系 (如 '母亲' / '父亲' / '奶奶' / '挚友'): ").strip()

    user_ref = input("[3/5] AI 怎么称呼缅怀者 (如 '孩子' / '小名'，留空用 '你'): ").strip()
    if not user_ref:
        user_ref = "你"

    boundary = input(
        "[4/5] 边界风格 [1=沉浸式像在世, 2=回忆口吻(推荐), 3=二者皆可]: "
    ).strip()
    boundary = boundary or "2"
    if boundary not in ("1", "2", "3"):
        boundary = "2"

    extra = input("[5/5] 补充信息 (想聊的话题、特别在意的事，可留空): ").strip()

    user_info = f"""称呼：{name}
关系：{relationship or "未填写"}
对缅怀者的称呼：{user_ref}
边界风格：{boundary}（1=沉浸式，2=回忆口吻，3=二者皆可）
补充：{extra or "无"}
"""

    return name, relationship, user_ref, boundary, user_info


def collect_chat_records():
    print()
    print(f"把聊天记录文件放到 {DATA_DIR}/ 目录。")
    print("支持 .txt / .json / .csv（utf-8 编码，纯文本就行）")
    print()

    files = sorted(DATA_DIR.iterdir())
    files = [f for f in files if f.is_file()]
    if files:
        print("已检测到以下文件：")
        for i, f in enumerate(files, 1):
            print(f"  [{i}] {f.name}  ({f.stat().st_size:,} bytes)")
        print()
        choice = input("选择文件编号（直接回车跳过，会让你手填路径）: ").strip()
        if choice:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(files):
                    return files[idx]
            except ValueError:
                pass

    path = input("聊天记录文件路径（拖入文件 / 直接输入路径）: ").strip().strip('"')
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        print(f"[error] file not found: {p}")
        return None
    return p


def truncate_chat_records(text: str, max_chars: int = 6000) -> str:
    """聊天记录太长就只取前 N 字符。如果太长则取首尾各一半。"""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n...（中间已省略）...\n\n" + text[-half:]


def call_llm_extract(client, model: str, user_info: str, chat_records: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(
        user_info=user_info, chat_records=truncate_chat_records(chat_records)
    )
    print()
    print("[setup] extracting personality from chat records ...")
    print(f"        records: {len(chat_records):,} chars (truncated to {min(len(chat_records), 6000):,})")
    print(f"        this may take 30-90 seconds ...")

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )
    text = resp.choices[0].message.content.strip()
    return parse_json(text)


def parse_json(text: str) -> dict:
    # 试着从 markdown fence 提取
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 试着找第一个 { 到最后一个 }
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"no JSON found in LLM output:\n{text[:500]}")


def list_served_models(client):
    try:
        return [m.id for m in client.models.list().data]
    except Exception:
        return []


def main():
    name, relationship, user_ref, boundary, user_info = collect_user_input()
    chat_path = collect_chat_records()
    if chat_path is None:
        print("[abort] no chat records provided")
        sys.exit(1)

    chat_text = chat_path.read_text(encoding="utf-8", errors="ignore")
    if len(chat_text.strip()) < 50:
        print(f"[error] chat records too short ({len(chat_text)} chars), abort")
        sys.exit(1)

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    models = list_served_models(client)
    if not models:
        print("[error] cannot reach vllm at", BASE_URL)
        print("        start the service first: start_vllm_server.bat")
        sys.exit(1)
    model = models[0]
    print(f"[setup] using model: {model}")

    try:
        profile = call_llm_extract(client, model, user_info, chat_text)
    except Exception as e:
        print(f"[error] failed to extract: {e}")
        sys.exit(1)

    # 字段兜底
    profile.setdefault("name", name)
    profile.setdefault("relationship", relationship or "未填写")
    profile.setdefault("user_reference", user_ref)
    profile.setdefault("boundary", boundary)

    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print("=" * 60)
    print("  Profile saved to:", PROFILE_PATH)
    print("=" * 60)
    print(f"  name          : {profile.get('name')}")
    print(f"  relationship  : {profile.get('relationship')}")
    print(f"  self_reference: {profile.get('self_reference')}")
    print(f"  traits        : {', '.join(profile.get('personality_traits', []))}")
    print(f"  catchphrases  :")
    for cp in profile.get("catchphrases", []):
        print(f"      - {cp}")
    print()
    print("Next step:")
    print("    python chat_openai_api.py")
    print()
    print("可以手工编辑 memorial_profile.json 微调任何字段。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[abort]")
        sys.exit(0)