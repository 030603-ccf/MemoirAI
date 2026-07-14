# skills/

This directory contains the **default skill templates** shipped with MemoirAI.
They are plain-text files with YAML frontmatter (`.skill` extension), each
defining one aspect of how the AI should behave.

## How skills work

On first launch, `backend/core/skill_engine.py` will copy all `.skill` files
from this directory into `../data/skills/` (a gitignored, user-private
directory). Users then edit the copies freely without touching the upstream
templates.

When the app builds a System Prompt, it:

1. Loads all `*.skill` files from `data/skills/` (sorted by filename)
2. Concatenates their `prompt:` fields in order
3. Skips "meta skills" (e.g. `004_evolver`) which define evolution rules but
   are not injected into the prompt

## What's in here

| File | Purpose | Locked? | Injected into prompt? |
|------|---------|---------|-----------------------|
| `001_style.skill` | Speaking style (catchphrases, sentence length, AI-isms to avoid) | ✅ Yes | ✅ Yes |
| `002_memory.skill` | When and how to bring up past memories | ✅ Yes | ✅ Yes |
| `003_boundary.skill` | Conversation boundaries, immersion, safety | ✅ Yes | ✅ Yes |
| `004_evolver.skill` | Evolution rules — when to suggest new skills based on chat history | N/A (meta) | ❌ No |

**Locked skills** cannot be auto-modified by the evolver. They are the
foundational behavior contract.

## Files NOT in here (auto-generated or user-private)

| File | Where | Why |
|------|-------|-----|
| `000_profile.skill` | `data/skills/` | Auto-generated from `memorial_profile.json` — contains the deceased's persona (name, traits, catchphrases) which is **highly personal** |
| `005_insights.skill` | `data/skills/` | Auto-generated every 100 turns by DeepSeek — contains **private analysis** of the user's conversation patterns |

Both are gitignored and never committed to the public repo.

## Customizing

To customize a skill:

1. **Don't edit the files here** — your changes will be overwritten on the
   next `git pull`.
2. Edit the copy in `data/skills/` instead. The runtime loads from there.
3. To upstream improvements, open a PR against this directory.

## Adding a new skill

Create `data/skills/00X_your_skill.skill` (any name, but use a number prefix
to control ordering). The YAML frontmatter looks like:

```yaml
name: "your-skill"
description: "What this skill does"
version: 1
updated_at: "2026-07-14"
prompt: |
  # Your skill instructions

  Lorem ipsum...
```

The first line of `prompt` is treated as a heading. Subsequent lines are
appended to the System Prompt after all earlier skills.

## Format reference

```
name: <string>           # required, used for meta-skill detection
description: <string>    # required, shown in management UI
version: <integer>       # required, increment on update
updated_at: <YYYY-MM-DD> # required
prompt: |                # required, multi-line block scalar (YAML)
  ...content lines...
```

Parsed by `backend/core/skill_engine.py:_parse_skill_file()` (no PyYAML
dependency — small custom parser).
