# MemoirAI Skill 系统

> 一份给"想深入理解或扩展 skill 系统"的开发者。

## 一、为什么需要 Skill 系统？

传统做法把人格调教硬编码进 system prompt（一长串文本），有两个问题：

1. **改不动**：要调一句口头禅，得改代码
2. **看不见**：用户不知道 AI 是在哪些规则下工作的

MemoirAI 把这些"规则"**外置成可读文本文件**（`.skill`），用 YAML frontmatter 描述元信息，用 `prompt:` 块描述内容。运行时拼接到 System Prompt 里。

这样：

- 改 prompt 不用动代码
- 用户可以审计 AI 的"行为准则"
- 可以支持**自动进化**（每 100 轮对话扫描，提炼新模式）

---

## 二、Skill 文件结构

### 2.1 物理位置

```
MemoirAI/
├── skills/                            # 仓库根：默认模板（开源、随项目分发）
│   ├── 001_style.skill
│   ├── 002_memory.skill
│   ├── 003_boundary.skill
│   └── 004_evolver.skill
└── data/
    └── skills/                        # 运行时实例（gitignore，用户私有）
        ├── 000_profile.skill          # 自动从 memorial_profile.json 生成
        ├── 001_style.skill            # ← 首次启动从 skills/ 复制
        ├── 002_memory.skill           # ← 首次启动从 skills/ 复制
        ├── 003_boundary.skill         # ← 首次启动从 skills/ 复制
        ├── 004_evolver.skill          # ← 首次启动从 skills/ 复制
        └── 005_insights.skill         # 自动每 100 轮生成
```

### 2.2 文件格式

```yaml
name: "说话风格优化"
description: "引导 LLM 模仿逝者的用词、句式、语气和口头禅"
version: 1
updated_at: "2026-07-14"
prompt: |
  # 说话风格与语气

  ## 用词和句式
  - 使用短句（1-3句），避免长篇大论。
  - 全部使用口语化表达，禁止书面语。

  ## 禁止的AI腔
  - 绝对不说"作为AI"、"根据分析"。
  ...
```

YAML 字段说明：

| 字段 | 必填 | 用途 |
|------|------|------|
| `name` | ✅ | 人类可读名（meta-skill 检测用） |
| `description` | ✅ | 描述作用（管理 UI 展示） |
| `version` | ✅ | 整数，每次更新 +1 |
| `updated_at` | ✅ | `YYYY-MM-DD` |
| `prompt` | ✅ | 多行块（YAML `\|`），注入到 System Prompt 的内容 |

> 解析器：`backend/core/skill_engine.py:_parse_skill_file()`
> 不依赖 PyYAML（手写小型 parser，避免给打包添麻烦）

---

## 三、Skill 分类

### 3.1 普通 Skill（注入 prompt）

文件名按字典序排序加载，prompt 拼接到 system prompt。

| 文件 | 名字 | 作用 |
|------|------|------|
| `000_profile.skill` | 逝者人格画像 | 名字 / 关系 / 性格 / 口头禅 |
| `001_style.skill` | 说话风格 | 句长 / 词汇 / AI 腔 / 角色一致性 |
| `002_memory.skill` | 记忆触发 | 何时 / 怎么提起回忆 |
| `003_boundary.skill` | 对话边界 | 沉浸感 / 主动 / 安全 |
| `005_insights.skill` | 实时洞察 | 最近对话提炼出的新模式 |

### 3.2 元 Skill（不注入 prompt）

文件名前缀命中 `META_SKILLS`（默认 `{"004_evolver"}`）的 skill **不注入** system prompt，而是用于控制系统行为本身。

| 文件 | 作用 |
|------|------|
| `004_evolver.skill` | 定义"每 100 轮扫描一次对话历史，提炼新模式" 的规则 |

### 3.3 锁定 Skill（不可被自动修改）

文件名前缀命中 `LOCKED_SKILLS`（默认 `{"001_style", "002_memory", "003_boundary"}`）的 skill **永不被 evolver 修改**。

设计意图：

| 锁定 | 不锁定 | 自动生成 |
|------|--------|----------|
| 行为契约（基础规则） | 可调优的策略 | 用户 / 系统数据 |
| 001 / 002 / 003 | （目前没有，未来可加） | 000 / 005 |

---

## 四、加载流程

### 4.1 首次启动（Bootstrap）

```python
def _bootstrap_skills():
    """把仓库根 skills/ 里的模板复制到 data/skills/（如果还没有）。"""
    if not TEMPLATE_DIR.is_dir():
        return
    existing = {f.name for f in SKILL_DIR.glob("*.skill")}
    for src in sorted(TEMPLATE_DIR.glob("*.skill")):
        dst = SKILL_DIR / src.name
        if dst.exists():
            continue  # 不覆盖用户已编辑的版本
        shutil.copy2(src, dst)
```

**好处**：
- 新用户：拿到 4 个默认模板，立刻能用
- 升级用户：保留自己的修改，只补上新增模板
- Fork 项目：上游改了模板，下游可以选择不覆盖

### 4.2 运行时加载

```python
class SkillManager:
    def load_skills(self) -> list[dict]:
        skills = []
        for f in sorted(SKILL_DIR.glob("*.skill")):
            data = _parse_skill_file(f)
            if data:
                skills.append(data)
        return skills

    def get_skills_prompt(self) -> str:
        """把所有非元 skill 的 prompt 拼起来。"""
        skills = self.load_skills()
        parts = []
        for s in skills:
            name = s.get("name", "").strip('"')
            is_meta = any(name.startswith(m) for m in META_SKILLS)
            if is_meta:
                continue
            prompt = s.get("prompt", "").strip()
            if not prompt:
                continue
            parts.append(prompt)
        return "\n\n".join(parts)
```

### 4.3 注入位置

在 `routers/api.py` 的 `/api/chat` handler 里：

```python
# Skills 层：注入所有非元技能的 prompt
smgr = get_skill_manager()
skills_prompt = smgr.get_skills_prompt()
if skills_prompt:
    messages.append({"role": "system", "content": skills_prompt})
```

**注入顺序**（在 system prompt 里的位置）：

```
┌─ System Prompt ─────────────────────────────────────┐
│  1. FALLBACK_SYSTEM（人格画像 base）               │
│  2. user_supplement（用户补充模板）                │
│  3. Semantic Memory Facts                          │
│  4. Memory Triggers                                │
│  5. Style Hint                                     │
│  6. Emotion Hint                                   │
│  7. Skills（000 + 001 + 002 + 003 + 005） ← 这里   │
│  8. RAG Context                                    │
│  9. Working Memory (10 turns)                      │
│  10. User Input                                    │
└────────────────────────────────────────────────────┘
```

---

## 五、自动进化（Evolver）

### 5.1 触发条件

`004_evolver.skill` 定义规则——当前实现是：**每累计 100 轮对话触发一次**。

### 5.2 提炼流程

`SkillManager.evolve_insights()` 实现：

1. 取出最近 100 轮对话（格式化）
2. 用 LLM（DeepSeek）扫描新模式
3. 输出新的 `005_insights.skill`

### 5.3 决策契约

Evolver **只提议，不写入**。所有变更需要用户确认：

```yaml
# 输出示例
- skill: 001_style
  field: catchphrases
  current: ["神经病", "废物"]
  proposed:
    - value: "诶我跟你说"
      evidence: "出现在 12 段对话中"
      confidence: high
```

Evolver **只追加不删除**——保护用户已有设置。

---

## 六、安全设计

### 6.1 不上传到公开仓库

`.gitignore` 保护：

```gitignore
data/skills/000_profile.skill    # 逝者人格（极私人）
data/skills/005_insights.skill   # 对话分析（极私人）
data/skills/                     # 整体（用户私有副本）
```

仓库根的 `skills/` 只有 4 个**通用模板**，不含任何个人数据。

### 6.2 Lock 机制

001/002/003 是**锁定 skill**——evolver 不能修改它们。

这意味着：
- 升级代码不会意外覆盖你的"行为契约"
- Fork 项目的合作者无法偷偷植入 prompt injection

### 6.3 Meta-skill 隔离

`004_evolver.skill` 定义了**系统行为本身**（"每 100 轮扫描并提议"），但它自己**不注入 prompt**——避免 prompt injection 风险（evolver 规则不会让 LLM 看到）。

---

## 七、自定义 Skill

### 7.1 改现有 skill

1. **不要改仓库根的 `skills/`**——会被 `git pull` 覆盖
2. 改 `data/skills/001_style.skill`（或任意 skill）
3. 重启应用生效

### 7.2 加新 skill

在 `data/skills/` 创建 `00X_xxx.skill`：

```yaml
name: "your-skill"
description: "What it does"
version: 1
updated_at: "2026-07-14"
prompt: |
  # Your rules here
  ...
```

文件名按字典序排序加载——用数字前缀控制顺序。

### 7.3 上游贡献

如果你的修改对所有用户都有价值：

1. 在仓库根的 `skills/` 改对应文件
2. 更新 `version` 和 `updated_at`
3. 在 `CHANGELOG.md` 加 entry
4. 开 PR

---

## 八、API 端点

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/skills` | GET | 列出所有 skill |
| `/api/skills/{name}` | GET | 查看单个 skill |
| `/api/skills/{name}` | PUT | 更新 skill（受 locked 限制） |
| `/api/skills/{name}/evolve` | POST | 手动触发 evolver（需 LLM 客户端） |

（具体实现见 `routers/api.py`）

---

## 九、设计哲学

> **AI 行为应该是可读的、可审的、可进化的。**

| 原则 | 实现 |
|------|------|
| 可读 | 纯文本 YAML，不用压缩格式 |
| 可审 | 单独文件，diff 友好 |
| 可改 | 不需要碰代码 |
| 可进 | evolver 提议新模式 |
| 可锁 | 关键 skill 不可被自动覆盖 |
| 可分 | 仓库模板 vs 用户实例，分层清晰 |

---

*最后更新：2026-07-14 · v0.3.0*
