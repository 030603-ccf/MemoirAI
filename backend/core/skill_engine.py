"""
skill_engine.py — MemoirAI Skill 管理引擎
==========================================
管理 Prompt Skill 文件的加载、组装、自动进化。

Skill 体系:
  000_profile.skill      — 从 memorial_profile.json 自动生成
  001_style.skill        — 说话风格（锁定）
  002_memory.skill       — 记忆触（锁定）
  003_boundary.skill     — 边界微调（锁定）
  004_evolver.skill      — 元技能（进化规则，不注入 prompt）
  005_insights.skill     — 实时洞察（每 100 轮由 DeepSeek 生成）"
"""
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional


# 仓库根目录的 skill 模板（开源、随项目分发）
# dev 模式：项目根/skills/，exe 模式：sys._MEIPASS/skills/
def _find_template_dir() -> Path:
    """查找仓库根的 skills/ 模板目录。"""
    if getattr(__import__("sys"), "frozen", False):
        # PyInstaller 打包：模板被打到 _MEIPASS/skills/
        meipass = getattr(__import__("sys"), "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / "skills"
            if candidate.is_dir():
                return candidate
    # dev 模式：core/skill_engine.py → 上两级 → 项目根
    return Path(__file__).resolve().parent.parent.parent / "skills"


# 运行时 skill 目录（用户私有，gitignore）
SKILL_DIR = Path(__file__).resolve().parent.parent / "data" / "skills"
TEMPLATE_DIR = _find_template_dir()
PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "memorial_profile.json"

# 不注入 System Prompt 的元技能
META_SKILLS = {"004_evolver"}

# 锁定的技能（永不被 evolution 修改）
LOCKED_SKILLS = {"001_style", "002_memory", "003_boundary"}


def _ensure_skill_dir():
    SKILL_DIR.mkdir(parents=True, exist_ok=True)


def _bootstrap_skills():
    """首次启动：把仓库根 skills/ 里的模板复制到 data/skills/。

    规则：
    - data/skills/ 不存在 → 整体复制
    - data/skills/ 存在但为空 → 整体复制
    - 已有同名文件 → 不覆盖（保留用户编辑）

    这样：
    - 新用户：直接拿到默认 4 个模板
    - 升级用户：保留自己的修改，只补上新增的模板
    """
    _ensure_skill_dir()
    if not TEMPLATE_DIR.is_dir():
        # 没有模板目录（开发环境未配置 / 打包漏文件）
        return
    existing = {f.name for f in SKILL_DIR.glob("*.skill")}
    copied = []
    for src in sorted(TEMPLATE_DIR.glob("*.skill")):
        dst = SKILL_DIR / src.name
        if dst.exists():
            continue
        try:
            shutil.copy2(src, dst)
            copied.append(src.name)
        except Exception as e:
            print(f"[skill] failed to bootstrap {src.name}: {e}", flush=True)
    if copied:
        print(f"[skill] bootstrapped {len(copied)} templates: {copied}", flush=True)


def _parse_skill_file(path: Path) -> Optional[dict]:
    """解析 .skill 文件（YAML front 格式）。"""
    try:
        content = path.read_text(encoding="utf-8")
        # simple YAML parser (no pyyaml dependency)
        data = {"path": str(path)}
        current_key = None
        current_value = []
        in_prompt = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if in_prompt:
                # prompt 内容行
                if line.startswith('  ') or line.startswith('\t') or stripped == '|':
                    if stripped == '|':
                        continue
                    current_value.append(line[2:] if line.startswith('  ') else line)
                    continue
                else:
                    # prompt 结束，保存
                    data[current_key] = '\n'.join(current_value)
                    in_prompt = False
                    current_value = []
            # 新的键值对
            if ':' in stripped and not stripped.startswith('-'):
                key, _, val = stripped.partition(':')
                key = key.strip()
                val = val.strip()
                if val == '|':
                    current_key = key
                    current_value = []
                    in_prompt = True
                else:
                    data[key] = val.strip('"').strip("'")
        if in_prompt and current_key:
            data[current_key] = '\n'.join(current_value)
        return data
    except Exception as e:
        print(f"[skill] failed to parse {path.name}: {e}", flush=True)
        return None


def _save_skill_file(name: str, prompt: str, description: str = "", version: int = 1):
    """保存 .skill 文件。"""
    now = time.strftime("%Y-%m-%d")
    data = {
        "name": f'"{name}"',
        "description": f'"{description}"' if description else '""',
        "version": str(version),
        "updated_at": f'"{now}"',
        "prompt": prompt,
    }
    content = f"""name: {data['name']}
description: {data['description']}
version: {data['version']}
updated_at: {data['updated_at']}
prompt: |
"""
    for line in prompt.splitlines():
        content += f"  {line}\n"
    (SKILL_DIR / f"{name}.skill").write_text(content, encoding="utf-8")


class SkillManager:
    """管理所有 Skill 文件。"""

    def __init__(self):
        _ensure_skill_dir()
        _bootstrap_skills()

    def load_skills(self) -> list[dict]:
        """加载所有 .skill 文件，返回排序后的 skill 列表。"""
        skills = []
        for f in sorted(SKILL_DIR.glob("*.skill")):
            data = _parse_skill_file(f)
            if data:
                skills.append(data)
        return skills

    def get_skills_prompt(self) -> str:
        """获取所有非元技能的 prompt 拼接结果。"""
        skills = self.load_skills()
        parts = []
        for s in skills:
            name = s.get("name", "").strip('"')
            # 跳过元技能（如 004_evolver）
            is_meta = any(name.startswith(m) for m in META_SKILLS)
            if is_meta:
                continue
            # 跳过空 prompt
            prompt = s.get("prompt", "").strip()
            if not prompt:
                continue
            parts.append(prompt)
        return "\n\n".join(parts)

    def generate_profile_skill(self) -> bool:
        """从 memorial_profile.json 生成 000_profile.skill。

        Returns: True 如果生成了新的 skill。
        """
        if not PROFILE_PATH.exists():
            return False
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return False

        name = profile.get("name", "")
        self_ref = profile.get("self_reference", "")
        user_ref = profile.get("user_reference", "")
        relationship = profile.get("relationship", "")
        traits = profile.get("personality_traits", [])
        style = profile.get("speaking_style", "")
        catchphrases = profile.get("catchphrases", [])

        if not name:
            return False

        lines = ["# 你是谁"]
        if relationship:
            lines.append(f"你的名字是「{name}」，你是用户的{relationship}。")
        else:
            lines.append(f"你的名字是「{name}」。")

        if traits:
            lines.append(f"你的性格特点：{'、'.join(traits)}。")
        if style:
            lines.append(f"你的说话风格：{style}。")
        lines.append("")

        lines.append("## 自称与称呼")
        lines.append(f"你自称「{self_ref or '我'}」，称呼用户为「{user_ref or '你'}」。")
        lines.append("")

        if catchphrases:
            lines.append("## 口头禅")
            phrases = "、".join(catchphrases)
            lines.append(f"你经常说：「{phrases}」。")

        prompt = "\n".join(lines)
        _save_skill_file("000_profile", prompt, "逝者人格画像（自动生成）", version=1)
        print(f"[skill] generated 000_profile.skill", flush=True)
        return True

    def evolve_insights(self, turns_text: str, llm_client, model: str) -> Optional[str]:
        """用 DeepSeek 分析最近 100 轮对话，生成 005_insights.skill。

        Args:
            turns_text: 格式化的最近 100 轮对话文本
            llm_client: OpenAI client
            model: LLM 模型名

        Returns: 新的 prompt 内容，或 None（无可改进）
        """
        # 加载现有 005（如果存在）
        existing = None
        for f in SKILL_DIR.glob("005_insights.skill"):
            data = _parse_skill_file(f)
            if data:
                existing = data.get("prompt", "")

        prompt = f"""你是 MemoirAI 的数据分析师。请分析以下最近 100 轮对话，提取关于用户的**新发现**。

## 分析维度
1. 用户最近关心的话题（工作/健康/家庭/情感）
2. 用户对 AI 回复的偏好（短回复/长回复/温暖/直接）
3. 用户最近的情绪状态（开心/低落/焦虑/平静）
4. 逝者口头禅/习惯用语的实际使用效果（哪些被用户接受了）
5. 任何新的、值得记下来的模式

## 现有洞察
{existing or "（暂无）"}

## 最近对话
{turns_text}

## 输出要求
- 只写新的发现，不要重复已有洞察
- 每条发现 1-2 句话，简洁
- 如果没有新的有意义发现，输出 "NO_NEW_INSIGHTS"
- 格式：纯文本，每行一条，不要 markdown 标题
"""

        try:
            from openai import OpenAI
            if isinstance(llm_client, OpenAI):
                r = llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.3,
                )
                result = (r.choices[0].message.content or "").strip()
                if "NO_NEW_INSIGHTS" in result or len(result) < 10:
                    print(f"[skill] evolution: no new insights found", flush=True)
                    return None

                # 保存为 005
                _save_skill_file("005_insights", "# 实时洞察\n\n" + result,
                                 "每 100 轮由 DeepSeek 自动生成", version=1)
                print(f"[skill] evolution: updated 005_insights.skill ({len(result)} chars)", flush=True)
                return result
        except Exception as e:
            print(f"[skill] evolution failed: {e}", flush=True)
        return None


# 全局单例
_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
