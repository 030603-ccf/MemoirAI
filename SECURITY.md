# Security Policy

## ⚠️ Sensitive Project Notice

MemoirAI handles highly personal data — chat logs, voice recordings, and personal information about deceased loved ones. We take security and privacy seriously, but **the responsibility for keeping your data safe ultimately rests with you**.

---

## Privacy Architecture

### What stays on your machine (NEVER leaves)

| Data type | Storage location |
|-----------|------------------|
| Chat logs (extracted text) | `data/chat_extracted.txt` |
| Memorial profile | `data/memorial_profile.json` |
| User settings (API keys) | `data/user_settings.json` |
| Session history | `data/memory/sessions/*.json` |
| Semantic memory | `data/memory/semantic_memory.json` |
| RAG indices | `data/rag_index/` |
| Voice samples | `data/voice_samples/*.wav` |
| TTS cache | `data/tts_cache/*.mp3` |
| Guard logs | `data/logs/guard_*.txt` |
| **Skill files (private)** | `data/skills/000_profile.skill`, `data/skills/005_insights.skill` |

### ⚠️ Skill files contain sensitive data

The `data/skills/` directory contains:

- **`000_profile.skill`** — Auto-generated from your memorial profile. Contains the deceased's name, relationship, personality traits, **and catchphrases** (their actual words). Treat this as **biographical data**.
- **`005_insights.skill`** — Auto-generated every 100 turns by DeepSeek analyzing your conversations. Contains **private analysis of your conversation patterns** (topics you raise, emotions you express, etc.).
- **`001/002/003_boundary.skill`** — Copies of upstream templates; can be edited by you to add personal rules.

**These files are gitignored for a reason.** Never commit them to a public repo, never share them, never include them in bug reports.

### What leaves your machine (and what doesn't)

| Service | What is sent | What is NOT sent |
|---------|--------------|-------------------|
| **LLM API** (DeepSeek, etc.) | Current-turn user message + system prompt + retrieved RAG context | Past sessions, voice samples, full chat history |
| **edge-tts** | Current synthesis text | Voice samples, anything else |
| **CosyVoice (DashScope)** | Synthesis text + the ~30s reference audio you uploaded | Past sessions, full chat history |
| **PaddleOCR (local)** | Nothing (runs on your machine) | N/A |
| **faster-whisper (local)** | Nothing (runs on your machine) | N/A |

**No telemetry, no analytics, no usage tracking.** We have no servers. There is nothing to phone home to.

---

## Sensitive Information Warning

Before publishing screenshots, recordings, or datasets that include real personal data:

- ❌ **Never commit** the `data/` directory to git (it is in `.gitignore` for a reason)
- ❌ **Never commit** `data/user_settings.json` (contains API keys)
- ❌ **Never commit** real voice samples to public repos
- ❌ **Never share** chat logs containing real names / phone numbers / addresses without consent
- ✅ When filing issues, redact all personal information from logs and screenshots

---

## Reporting a Security Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report privately via one of these channels:

1. **GitHub Security Advisories** (preferred): [Create a private security advisory](../../security/advisories/new)
2. **Email**: see the maintainer's contact in their GitHub profile

Please include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact (data leak, code execution, etc.)
- Suggested fix (if any)

We aim to acknowledge reports within **72 hours** and provide a fix timeline within **7 days** for critical issues.

---

## Known Security Considerations

### 1. Local API keys

`data/user_settings.json` contains plaintext API keys (DeepSeek, DashScope, etc.). On a shared machine:

- The file is readable by any user with access to your account
- Anyone who can read the file can extract the keys
- We recommend file system permissions: `chmod 600 data/user_settings.json` (macOS/Linux) or restrict via OS settings (Windows)

### 2. Voice samples are sensitive

Voice samples stored in `data/voice_samples/` can be used to clone the speaker's voice. Treat this directory like a password vault.

### 3. EXE distribution

When distributing a pre-built `MemoirAI.exe`:

- Anyone who runs the EXE has full code-level access to the bundled Python interpreter
- Source-level secrets (if any are added in the future) **will be extractable**
- We will **never** embed production API keys in the EXE
- Users must configure their own API keys

### 4. PyInstaller unpacking

PyInstaller EXEs can be unpacked with `pyinstxtractor` and similar tools. Treat the EXE as a transparent binary, not a security boundary.

### 5. PaddleOCR subprocess

OCR runs in a subprocess to avoid DLL conflicts (see [CHANGELOG.md v0.2.0](./CHANGELOG.md)). This is functional, not a security boundary — if a malicious chat log file were crafted, PaddleOCR's input parser is the attack surface. PaddleOCR is not a known target, but be aware.

---

## Ethical Use

MemoirAI is a **technical prototype**, not a grief counseling service.

The author(s) acknowledge that simulating the deceased raises serious questions:

- **Consent**: The "speaker" cannot consent to being simulated
- **Grief**: The technology can be used in healthy or harmful ways
- **Identity**: AI-generated speech in someone's voice carries weight
- **Closure**: There is no consensus on whether this technology helps or harms the grieving process

We ask users to:

- ✅ Use thoughtfully and respectfully
- ✅ Consider the impact on family members and other loved ones
- ✅ Treat AI responses as **impressions**, not veridical
- ❌ Do not use to deceive others into thinking the deceased "spoke"
- ❌ Do not use to replace professional grief support

If you are struggling with grief, please reach out to a qualified counselor. AI companions — including this one — are no substitute for human care.

---

## Compliance

This project makes no specific compliance claims (HIPAA, GDPR, etc.). It is a personal/local tool. **You are responsible** for ensuring your use complies with local laws regarding:

- Data protection
- Voice/image rights
- Post-mortem privacy

---

## Acknowledgements

This security policy draws on best practices from the open-source community. If you have suggestions for improvement, please open a PR.

---

*Last updated: 2026-07-14 · v0.3.0*
