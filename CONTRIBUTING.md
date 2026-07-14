# Contributing to MemoirAI

First off, thank you for considering contributing to MemoirAI. 💚
This project is a personal/small-team effort, but every PR — even a typo fix — helps.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [What we're looking for](#what-were-looking-for)
- [How to contribute](#how-to-contribute)
- [Development setup](#development-setup)
- [Pull request process](#pull-request-process)
- [Style guide](#style-guide)
- [Commit message convention](#commit-message-convention)
- [Reporting bugs](#reporting-bugs)
- [Suggesting features](#suggesting-features)

---

## Code of Conduct

This project deals with sensitive emotional topics (loss, grief, identity). Be kind, patient, and respectful in all interactions. Disagreement is fine; rudeness is not.

## What we're looking for

**High-value contributions** (especially welcome):

- 🐛 **Bug fixes** — open an issue first, then submit a PR
- 🌍 **Internationalization** — UI text + system prompts in more languages
- 🧪 **Tests** — currently coverage is light
- 📚 **Documentation improvements** — clearer explanations, typo fixes
- 🎨 **UI/UX polish** — accessibility, mobile responsiveness
- 🔌 **New LLM/TTS/Embedding providers** — abstracted, with config
- 🛡️ **Hallucination Guard improvements** — NER patterns, safe-word list
- 📦 **Deployment recipes** — Docker, systemd, macOS app

**Will probably not merge**:

- ❌ Anything that requires sending user data to non-consensual third parties
- ❌ Features that fundamentally change the "local-first" principle
- ❌ Major rewrites without prior discussion
- ❌ Code without tests for non-trivial logic

## How to contribute

### 1. Pick or create an issue

- Check [issues](../../issues) for "good first issue" labels
- If proposing a new feature, **open an issue first** to discuss
- Comment on the issue to let others know you're working on it

### 2. Fork and branch

```bash
git fork
git clone https://github.com/<yourname>/MemoirAI.git
cd MemoirAI
git checkout -b feat/your-feature-name
```

### 3. Develop

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m uvicorn routers.api:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### 4. Test

```bash
# Backend
cd backend
ruff check .
pytest  # if tests exist

# Frontend
cd frontend
npm run lint
npm run build  # ensure production build works
```

### 5. Submit PR

See [Pull Request Process](#pull-request-process) below.

## Development setup

### Prerequisites

- Python 3.10 (recommend conda env)
- Node.js 18+
- ~10 GB free disk for models
- Windows / macOS / Linux — all supported in dev mode; EXE build is Windows-only

### Code layout

```
backend/
├── routers/api.py          # FastAPI entry — all routes
├── core/                   # Business logic, no FastAPI imports
│   ├── agent_memory.py     # 3-layer memory
│   ├── rag_search.py       # Hybrid retrieval
│   ├── hallucination_guard.py
│   └── ...
├── utils/                  # Scripts (model downloaders, etc.)
├── data/                   # Runtime data (gitignored)
└── run.py                  # Dev / EXE entry

frontend/
├── src/
│   ├── views/              # ChatView, UploadView, etc.
│   ├── api/                # Backend API client
│   ├── router/             # Vue Router
│   └── App.vue
└── package.json
```

## Pull request process

1. **Open an issue first** for non-trivial changes (features, refactors)
2. **Keep PRs focused** — one logical change per PR
3. **Update docs** — if you change API/behavior, update relevant `.md` files
4. **Pass CI** — lint + build must be green
5. **Add a changelog entry** under `## Unreleased` in [CHANGELOG.md](./CHANGELOG.md)
6. **Request review** — at least one maintainer approval required

### PR title format

```
<type>(<scope>): <subject>

# Examples:
feat(memory): add cross-session confidence boost
fix(guard): reduce false positive on brand names
docs(readme): clarify EXE build steps
refactor(api): split /api/chat into smaller handlers
test(rag): add unit tests for hybrid scoring
```

**Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`
**Scopes**: `memory`, `rag`, `guard`, `tts`, `ocr`, `api`, `frontend`, `readme`, `ci`, etc.

## Style guide

### Python (backend)

- Follow PEP 8
- Use type hints (Python 3.10+ syntax: `list[str]`, `dict[str, int]`, `X | None`)
- Maximum line length: 100
- Use `ruff` for linting
- Docstrings for public functions/classes
- No bare `except:` — catch specific exceptions

```python
# Good
def get_fact_score(fact: dict, now: datetime | None = None) -> float:
    """Compute memory score with confidence × recency weighting."""
    if now is None:
        now = datetime.now()
    ...

# Avoid
def get_fact_score(fact, now=None):
    try:
        ...
    except:  # too broad
        pass
```

### JavaScript / Vue (frontend)

- Vue 3 `<script setup>` syntax preferred
- Composition API over Options API for new components
- Element Plus for UI components
- ESLint + Prettier (config in package.json)
- camelCase for variables/functions, PascalCase for components

```vue
<!-- Good -->
<script setup>
import { ref } from 'vue'
const count = ref(0)
</script>

<template>
  <el-button @click="count++">{{ count }}</el-button>
</template>
```

## Commit message convention

We loosely follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>  (max 72 chars)

<body>  (wrap at 72; explain WHY not WHAT)

<footer>  (BREAKING CHANGE: ..., Closes #..., etc.)
```

Examples:

```
feat(memory): implement 30-day half-life decay

Previously all facts were weighted equally, causing old facts to
dominate the prompt. Now importance × recency is used.

Closes #42
```

## Reporting bugs

Use the [bug report template](../../issues/new?template=bug_report.md). Include:

- **What you did** — exact steps to reproduce
- **What you expected**
- **What actually happened** — full error message / screenshot
- **Environment** — OS, Python version, Node version, branch/commit
- **Logs** — relevant snippets from `data/logs/` or browser console

**Security issues**: please **do not** open a public issue. See [SECURITY.md](./SECURITY.md).

## Suggesting features

Use the [feature request template](../../issues/new?template=feature_request.md). Include:

- **Problem** — what pain point are you solving
- **Proposed solution** — how you'd like it to work
- **Alternatives** — what else you considered
- **Tradeoffs** — performance, complexity, privacy implications

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE).

---

Thank you for making MemoirAI better. 🙏
