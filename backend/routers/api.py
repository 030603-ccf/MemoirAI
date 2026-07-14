# -*- coding: utf-8 -*-
import sys as _sys, io as _io
# 强制 UTF-8 输出（防止 Windows GBK 编码截断 Unicode 错误消息）
for _s in (_sys.stdout, _sys.stderr):
    if _s and hasattr(_s, "buffer"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
"""
backend/api.py - 数字纪念项目后端 API
=====================================
提供以下接口:
  GET  /api/profile             - 读 memorial_profile.json
  GET  /api/stats               - 数据统计(截图数,消息数,向量数)
  POST /api/upload-screenshots   - 接收图片, OCR 提取, 写到 chat_extracted.txt
  POST /api/rebuild-index       - 调用 rag_index.py 重建索引
  POST /api/chat                - 聊天入口:拼 system+RAG, 调 vLLM, 返回回复

启动:
  pip install fastapi uvicorn python-multipart openai
  uvicorn backend.api:app --host 0.0.0.0 --port 8088
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import hashlib

# ---------- API 限流 ----------
import time as _time
import collections as _col
_chat_rate_limiter = _col.defaultdict(list)  # {ip: [timestamp, ...]}

def _check_rate_limit(remote_ip: str, max_per_minute: int = 30) -> bool:
    """检查指定 IP 的请求频率。返回 True 表示允许，False 表示限流。"""
    now = _time.time()
    window = now - 60
    _chat_rate_limiter[remote_ip] = [t for t in _chat_rate_limiter[remote_ip] if t > window]
    if len(_chat_rate_limiter[remote_ip]) >= max_per_minute:
        return False
    _chat_rate_limiter[remote_ip].append(now)
    return True

# ---------- 路径 ----------
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
ROOT_DIR = PROJECT_DIR.parent  # 项目根目录（E:\MemoirAI\）
DATA_DIR = PROJECT_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
CHAT_TXT = DATA_DIR / "chat_extracted.txt"
PROFILE_JSON = DATA_DIR / "memorial_profile.json"
INDEX_DIR = DATA_DIR / "rag_index"
SETTINGS_JSON = DATA_DIR / "user_settings.json"

# 让 Python 能找到 core/ 模块(OCR + RAG + persona)
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "core"))

# 模型后端:默认 DeepSeek,env 可覆盖
# DeepSeek (官方): https://api.deepseek.com/v1
# 也可换其他 OpenAI 兼容服务(vLLM / 第三方代理)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")  # 'deepseek' | 'vllm'

# ---------- 内置 LLM Provider 配置(OpenAI 兼容格式) ----------
BUILTIN_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "description": "DeepSeek 官方 API",
    },
    "aliyun-bailian": {
        "name": "阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "description": "阿里云百炼(通义千问等)",
    },
    "siliconflow": {
        "name": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "description": "硅基流动(聚合多种模型)",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "description": "OpenRouter(多模型聚合)",
    },
    "custom": {
        "name": "自定义",
        "base_url": "",
        "default_model": "",
        "description": "自定义 OpenAI 兼容 API",
    },
}

def _get_builtin_provider(pid: str) -> dict | None:
    """返回内置 provider 配置,custom 返回空模板."""
    return BUILTIN_PROVIDERS.get(pid)


# ---------- 内置 TTS Provider 配置 ----------
BUILTIN_TTS_PROVIDERS = {
    "edge": {
        "name": "edge-tts",
        "base_url": "",
        "default_model": "",
        "need_key": False,
        "default_voice": "zh-CN-XiaoxiaoNeural",
        "description": "微软免费 TTS，无需 API Key",
    },
    "cosyvoice": {
        "name": "百炼 TTS",
        "base_url": "",
        "default_model": "cosyvoice-v3-flash",
        "need_key": True,
        "default_voice": "longanyang",
        "description": "阿里云百炼语音合成（CosyVoice），用户自持 Key",
    },
}


def _get_tts_config(settings: dict) -> dict:
    """返回当前 TTS 引擎的配置（base_url / api_key / model / voice）。"""
    engine = (settings.get("tts_engine") or "edge").strip().lower()
    builtin = BUILTIN_TTS_PROVIDERS.get(engine, BUILTIN_TTS_PROVIDERS["edge"])

    if engine == "edge":
        return {
            "engine": "edge",
            "base_url": "",
            "api_key": "",
            "model": "",
            "voice": settings.get("tts_voice", ""),
            "need_key": False,
        }

    # cosyvoice: 从 settings 读，缺失则用内置默认值
    base = (settings.get("cosyvoice_base_url") or builtin["base_url"]).strip()
    key = (settings.get("cosyvoice_api_key") or "").strip()
    model = (settings.get("cosyvoice_model") or builtin["default_model"]).strip()
    voice = (settings.get("cosyvoice_voice") or builtin["default_voice"]).strip()

    return {
        "engine": engine,
        "base_url": base,
        "api_key": key,
        "model": model,
        "voice": voice,
        "need_key": builtin["need_key"],
    }

# RAG 注入模板(与 chat_openai_api.py 一致)
RAG_INJECTION_TEMPLATE = (
    "\n\n# 风格参考(来自真实聊天记录,仅供学习语气/词汇/句式,不要照抄原话)\n"
    "以下片段来自 TA 过去说过的原话,挑选了与当前话题相关的几条:\n"
    "{chunks}\n\n"
    "提示:模仿 TA 的语气,用词和短句节奏,但要根据当前问题自由组织回复,不要逐字复述上面这些."
)

# ---------- App ----------
app = FastAPI(title="MemoirAI API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 记忆合并定时任务（每 6 小时运行一次）
def _consolidation_worker():
    """后台线程：定期合并记忆，清理低置信度事实。"""
    import threading
    def _run():
        # 首次启动时立即跑一次
        try:
            time.sleep(10)  # 等后端完全启动
            from agent_memory import MemoryManager
            mm = MemoryManager()
            n = mm.consolidate_all()
            print(f"[memory] startup consolidation: {n} facts remaining", flush=True)
        except Exception as e:
            print(f"[memory] startup consolidation failed: {e}", flush=True)
        while True:
            try:
                time.sleep(7200)  # 2 小时
                from agent_memory import MemoryManager
                mm = MemoryManager()
                n = mm.consolidate_all()
                print(f"[memory] auto-consolidation: {n} facts remaining", flush=True)
            except Exception as e:
                print(f"[memory] auto-consolidation failed: {e}", flush=True)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print("[memory] consolidation worker started (every 2h + startup)", flush=True)

_consolidation_worker()

# Profile Skill 自动生成（启动时从 memorial_profile.json 生成 000_profile.skill）
try:
    from skill_engine import get_skill_manager
    smgr = get_skill_manager()
    smgr.generate_profile_skill()
except Exception as e:
    print(f"[skill] profile generation failed: {e}", flush=True)


# ---------- Edge-tts 可用性检测 ----------
_EDGE_TTS_AVAILABLE = True
try:
    import edge_tts
except ImportError:
    _EDGE_TTS_AVAILABLE = False
    print("[warn] edge-tts not installed. Edge TTS will be unavailable.", flush=True)
    print("[warn] Install: pip install edge-tts", flush=True)


# ---------- 用户设置(API keys + 引擎选择) ----------
def _load_settings() -> dict:
    if not SETTINGS_JSON.exists():
        return {}
    try:
        return json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(s: dict):
    SETTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_JSON.write_text(
        json.dumps(s, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _mask_key(k: str) -> str:
    """key 显示给前端时遮住中间."""
    if not k:
        return ""
    if len(k) <= 8:
        return "***"
    return k[:4] + "*" * min(20, len(k) - 8) + k[-4:]


# 有效 LLM 配置:按 provider 读取 settings,缺失项用内置默认值兜底
def _get_llm_config() -> dict:
    s = _load_settings()
    provider = (s.get("llm_provider") or LLM_PROVIDER or "deepseek").strip().lower()
    builtin = _get_builtin_provider(provider)

    # 自定义 provider:全部从 settings 读
    if provider == "custom":
        key = (s.get("llm_api_key") or "").strip() or LLM_API_KEY
        base = (s.get("llm_base_url") or "").strip() or LLM_BASE_URL
        model = (s.get("llm_model") or "").strip() or LLM_MODEL
        return {"provider": provider, "key": key, "base": base, "model": model}

    # 内置 provider:key 从 settings 读(每个 provider 独立的 key 字段),base/model 用内置默认值
    # key 字段命名:provider.replace("-", "_") + "_api_key"
    key_field = f"{provider.replace('-', '_')}_api_key"
    key = (s.get(key_field) or "").strip()
    if not key:
        # fallback:旧字段兼容(deepseek_api_key)
        key = (s.get("deepseek_api_key") or "").strip()
    if not key:
        key = LLM_API_KEY

    base = (s.get("llm_base_url") or "").strip() or builtin.get("base_url", LLM_BASE_URL)
    model = (s.get("llm_model") or "").strip() or builtin.get("default_model", LLM_MODEL)

    return {"provider": provider, "key": key, "base": base, "model": model}


# ---------- 工具 ----------
def read_text_safe(path: Path) -> str:
    """读取文本文件，自动尝试 UTF-8 / GBK / GB18030。"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")

def read_json_safe(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            with path.open("r", encoding=enc) as f:
                return sum(1 for line in f if line.strip())
        except UnicodeDecodeError:
            continue
    return 0


def count_screenshots() -> int:
    if not SCREENSHOTS_DIR.exists():
        return 0
    return sum(1 for p in SCREENSHOTS_DIR.iterdir()
               if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"))


# ---------- OCR 提取(dev 用 subprocess,exe 模式 in-process 调)----------

# PaddleOCR 单例(加载要 30-60s,进程内只加载一次)
_OCR_INSTANCE = None
_OCR_LOCK = None

# 独立 OCR service(MemorialOCR.exe)相关
OCR_SERVICE_URL = os.environ.get("OCR_SERVICE_URL", "http://127.0.0.1:8089")
OCR_SERVICE_PORT = 8089
_OCR_SERVICE_SPAWNED = False  # 主 exe 自动 spawn 过 OCR 子进程?


def _get_ocr_instance():
    """懒加载 PaddleOCR 单例(仅 frozen / in-process 模式用)."""
    global _OCR_INSTANCE, _OCR_LOCK
    if _OCR_LOCK is None:
        import threading
        _OCR_LOCK = threading.Lock()
    if _OCR_INSTANCE is None:
        with _OCR_LOCK:
            if _OCR_INSTANCE is None:
                from paddleocr import PaddleOCR
                print("[ocr] loading PaddleOCR (first run downloads models, ~30-60s)...", flush=True)
                try:
                    _OCR_INSTANCE = PaddleOCR(use_textline_orientation=True, lang="ch")
                except TypeError:
                    _OCR_INSTANCE = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                print("[ocr] PaddleOCR ready", flush=True)
    return _OCR_INSTANCE


def _find_ocr_service_exe() -> Path | None:
    """找 MemorialOCR.exe 路径(exedir/ocr.exe)."""
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / "MemorialOCR.exe"
    if candidate.exists():
        return candidate
    return None


def _spawn_ocr_service_if_needed() -> bool:
    """如果是 frozen 主 exe 模式,自动 spawn MemorialOCR.exe 子进程(如果还没起)."""
    global _OCR_SERVICE_SPAWNED
    if _OCR_SERVICE_SPAWNED:
        return True
    if not getattr(sys, "frozen", False):
        return False
    ocr_exe = _find_ocr_service_exe()
    if not ocr_exe:
        return False
    # 检查 8089 已在听
    import socket
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", OCR_SERVICE_PORT))
        s.close()
        return True  # 已有别的实例
    except OSError:
        pass
    print(f"[ocr] spawning MemorialOCR.exe at {ocr_exe}", flush=True)
    try:
        subprocess.Popen(
            [str(ocr_exe)],
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS
        )
        _OCR_SERVICE_SPAWNED = True
        return True
    except Exception as e:
        print(f"[ocr] spawn failed: {e}", flush=True)
        return False


def _ocr_service_health() -> dict | None:
    """调 /health 检查 OCR service.返 None 表示不可达."""
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen(OCR_SERVICE_URL + "/health", timeout=3) as r:
            return _json.loads(r.read())
    except Exception:
        return None


def _ocr_service_post(files: list[tuple[str, bytes]]) -> dict:
    """通过 HTTP service 跑 OCR.files = [(filename, content_bytes), ...]"""
    import urllib.request, urllib.error, json as _json
    boundary = "----memorialocrboundary"
    body = b""
    for name, content in files:
        body += (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'
                 f"Content-Type: image/jpeg\r\n\r\n").encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        OCR_SERVICE_URL + "/ocr",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return _json.loads(r.read())




# ---------- 百炼多模态 OCR / ASR ----------
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BAILIAN_VL_MODEL = "qwen-vl-plus"


def _get_bailian_client() -> OpenAI | None:
    """返回百炼 client(用 user settings 的 bailian_api_key)."""
    s = _load_settings()
    key = (s.get("bailian_api_key") or "").strip()
    if not key:
        return None
    return OpenAI(base_url=BAILIAN_BASE_URL, api_key=key)


def _bailian_ocr(image_bytes: bytes) -> str:
    """用百炼 qwen-vl-plus 识别图片中的文字.

    返回:识别出的纯文本(按行分割).
    """
    client = _get_bailian_client()
    if not client:
        raise RuntimeError("百炼 API key 未配置")

    import base64
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    # 简单判断图片格式(用魔术字节)
    mime = "image/jpeg"
    if image_bytes[:4] == b"\x89PNG":
        mime = "image/png"
    elif image_bytes[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF":
        mime = "image/webp"

    data_url = f"data:{mime};base64,{b64}"

    resp = client.chat.completions.create(
        model=BAILIAN_VL_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "请识别这张聊天截图中的所有文字内容。按原格式输出对话内容，标明说话人。只输出文字，不要额外解释。"},
                ],
            }
        ],
        max_tokens=2048,
    )
    text = resp.choices[0].message.content or ""
    return text.strip()


async def _bailian_asr(audio_bytes: bytes, filename: str = "audio.wav") -> tuple[str, str]:
    """用 dashscope SDK 调用百炼 paraformer-v2 ASR 转文字.

    返回:(transcript, language)
    失败时抛出 RuntimeError.
    """
    s = _load_settings()
    key = (s.get("bailian_api_key") or "").strip()
    if not key:
        raise RuntimeError("百炼 API key 未配置")

    import dashscope
    from dashscope.audio.asr import Transcription
    dashscope.api_key = key

    ext = Path(filename).suffix.lower() or ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        # 发起异步转写任务
        task = Transcription.call(
            model="paraformer-v2",
            file_urls=[f"file://{tmp_path}"],
            language_hints=["zh-CN"],
        )
        if task.status_code != 200:
            raise RuntimeError(f"ASR 任务创建失败: {task.message}")

        task_id = task.output.task_id

        # 轮询获取结果（最多 60 秒）
        for _ in range(120):
            await asyncio.sleep(0.5)
            result = Transcription.fetch(task_id=task_id)
            if result.status_code != 200:
                continue
            status = result.output.task_status
            if status == "SUCCEEDED":
                results = result.output.results
                if results:
                    return results[0].transcription.strip(), "zh"
                return "", "zh"
            elif status == "FAILED":
                raise RuntimeError(f"ASR 任务失败: {result.message}")

        raise RuntimeError("ASR 任务超时")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

async def run_ocr(screenshot_paths: list[Path], enable_bailian: bool = False) -> dict:
    """跑 OCR 提取聊天文本,写到 chat_extracted.txt.

    优先级:
    1) OCR service(一体化版本:in-process;老版本:spawn MemorialOCR.exe)HTTP
    2) in-process PaddleOCR(仅 dev 模式 fallback)

    返回结构:{messages, preview, saved_files, new_count, service_result}
    messages 从 chat_extracted.txt 重新读(OCR 后追加的)
    """
    # 把截图复制到项目 screenshots/ 目录
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for src in screenshot_paths:
        dst = SCREENSHOTS_DIR / src.name
        shutil.copy2(src, dst)
        saved.append(dst)

    is_frozen = getattr(sys, "frozen", False)
    loop = asyncio.get_event_loop()

    # 记录 OCR 跑前 chat_extracted.txt 已有多少行(之后追加 = "新")
    def _count_existing_lines() -> int:
        if not CHAT_TXT.exists():
            return 0
        return count_lines(CHAT_TXT)

    before_count = _count_existing_lines()

    # -------- 优先:OCR service(HTTP)--------
    health = _ocr_service_health()
    if not health and _spawn_ocr_service_if_needed():
        # 等 ready(最多 60s)— 一体化版本 OCR service 已经在 run_app.py 起好了
        for _ in range(120):
            await asyncio.sleep(0.5)
            health = _ocr_service_health()
            if health and health.get("ready"):
                break
            health = _ocr_service_health()
    service_result = None
    if health and health.get("ready"):
        # 把图通过 HTTP 发过去
        files_data = [(p.name, p.read_bytes()) for p in saved]
        try:
            service_result = await loop.run_in_executor(None, lambda: _ocr_service_post(files_data))
        except Exception as e:
            print(f"[ocr] service POST failed: {e}", flush=True)
            # 继续尝试 fallback

    if service_result is None:
        # -------- fallback:in-process 或 报错 --------
        if is_frozen:
            raise RuntimeError(
                "OCR service 不可用(一体化 exe 应自动起 8089;如未起请重启 exe 或检查防火墙)"
            )
        # dev 模式 in-process 调(直接调 PaddleOCR)
        def _in_process_ocr():
            sys.path.insert(0, str(PROJECT_DIR / "core"))
            from extract_chat_universal import process_image  # noqa: E402
            ocr = _get_ocr_instance()
            all_msgs = []
            for i, img in enumerate(saved, 1):
                print(f"[ocr] {i}/{len(saved)}: {img.name}", flush=True)
                items = process_image(
                    ocr, img,
                    threshold_ratio=0.5, center_band=0.1,
                    crop_top_px=0, debug=False,
                )
                all_msgs.extend(items)
                print(f"[ocr]   -> {len(items)} chat lines", flush=True)
            # 输出
            CHAT_TXT.parent.mkdir(parents=True, exist_ok=True)
            with CHAT_TXT.open("a", encoding="utf-8") as f:
                f.write(f"\n# --- OCR batch at {time.strftime('%Y-%m-%d %H:%M:%S')} ({len(saved)} imgs) ---\n")
                for m in all_msgs:
                    role = "本人" if m["role"] == "self" else "对方"
                    f.write(f"[{role}] {m['text']}\n")
            return len(all_msgs)

        await loop.run_in_executor(None, _in_process_ocr)

    # 跑完 OCR 后,从 chat_extracted.txt 读出"新"的消息(从 before_count 开始)
    if not CHAT_TXT.exists():
        raise RuntimeError("OCR 后没生成 chat_extracted.txt")

    messages = []
    line_pattern = re.compile(r"^\[(本人|对方)]\s*(.+)$")
    for i, line in enumerate(read_text_safe(CHAT_TXT).splitlines(), 1):
        if i <= before_count:
            continue
        m = line_pattern.match(line.strip())
        if m:
            messages.append({"role": m.group(1), "text": m.group(2).strip(), "line_no": i})

    # -------- 百炼多模态 OCR 增强(可选) --------
    bailian_result = None
    if enable_bailian and saved:
        try:
            client = _get_bailian_client()
            if client:
                bailian_texts = []
                for img in saved:
                    print(f"[bailian-ocr] enhancing: {img.name}", flush=True)
                    txt = _bailian_ocr(img.read_bytes())
                    if txt:
                        bailian_texts.append(txt)
                if bailian_texts:
                    # 把百炼结果追加到 chat_extracted.txt
                    with CHAT_TXT.open("a", encoding="utf-8") as f:
                        f.write(f"\n# --- Bailian OCR enhancement at {time.strftime('%Y-%m-%d %H:%M:%S')} ({len(saved)} imgs) ---\n")
                        for txt in bailian_texts:
                            f.write(txt + "\n")
                    bailian_result = {"enhanced_images": len(bailian_texts), "total_chars": sum(len(t) for t in bailian_texts)}
                    print(f"[bailian-ocr] enhanced {len(bailian_texts)} images", flush=True)
            else:
                print("[bailian-ocr] skipped: no bailian api key configured", flush=True)
        except Exception as e:
            print(f"[bailian-ocr] error: {e}", flush=True)
            bailian_result = {"error": str(e)[:200]}

    # 如果有百炼增强,重新读取消息
    if bailian_result and not bailian_result.get("error"):
        messages = []
        for i, line in enumerate(read_text_safe(CHAT_TXT).splitlines(), 1):
            if i <= before_count:
                continue
            m = line_pattern.match(line.strip())
            if m:
                messages.append({"role": m.group(1), "text": m.group(2).strip(), "line_no": i})

    preview = "\n".join(f"[{m['role']}] {m['text']}" for m in messages[:50])
    return {
        "messages": messages,
        "preview": preview,
        "saved_files": [str(p) for p in saved],
        "new_count": len(messages),
        "service_result": service_result,
        "bailian_result": bailian_result,
    }


async def run_rebuild_index() -> dict:
    """重建 RAG 向量索引.

    策略：
    - dev 模式：用 subprocess 启动单独进程（避免 PaddleOCR 与 PyTorch DLL 冲突）
    - frozen 模式：in-process 调用（subprocess 会启动 exe 自身导致失败）
    """
    import subprocess as _sp

    is_frozen = getattr(sys, "frozen", False)

    if not is_frozen:
        # dev 模式：subprocess 跑 rag_index.py 脚本
        _ensure_bge_model()
        script = PROJECT_DIR / "core" / "rag_index.py"
        if not script.exists():
            raise RuntimeError(f"rag_index.py not found at {script}")

        def _run_subprocess():
            import json as _json
            result = _sp.run(
                [sys.executable, str(script), "--out-dir", str(INDEX_DIR), "--merge-window", "1"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, "INDEX_DIR": str(INDEX_DIR)},
            )
            if result.returncode != 0:
                err = (result.stderr or "")[-500:]
                raise RuntimeError(f"rebuild subprocess failed (rc={result.returncode}): {err}")
            # 从 meta.json 读取结果（最可靠）
            meta_file = INDEX_DIR / "meta.json"
            if meta_file.exists():
                return _json.loads(meta_file.read_text(encoding="utf-8"))
            return {"info": "index rebuilt (subprocess)"}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_subprocess)
    else:
        # frozen 模式：in-process 调用（避免 subprocess 启动 exe 自身）
        import importlib
        def _run():
            _ensure_bge_model()
            core_dir = PROJECT_DIR / "core"
            if core_dir.exists() and str(core_dir) not in sys.path:
                sys.path.insert(0, str(core_dir))
            ri = importlib.import_module("rag_index")
            ri.INDEX_DIR = INDEX_DIR
            ri.CHAT_TXT = CHAT_TXT
            return ri.build_index(out_dir=INDEX_DIR, merge_window=1)
        loop = asyncio.get_event_loop()
        meta = await loop.run_in_executor(None, _run)
        return meta


def _ensure_bge_model():
    """确保 bge 模型在 HF cache 路径可被 sentence-transformers 找到.

    sentence-transformers 用 HF cache 格式,期望结构:
      models--BAAI--bge-large-zh-v1.5/
        snapshots/main/
          config.json
          pytorch_model.bin
          ...

    查找顺序:
    1) exe 同目录 ./models/BAAI/bge-large-zh-v1.5/  (frozen 模式附的,优先级最高)
    2) 已有 HF cache ~/.cache/huggingface/hub/models--BAAI--bge-large-zh-v1.5/snapshots/main/
    3) 都没有 → raise RuntimeError

    如果 (1) 存在但 (2) 不存在 → 把 (1) 的内容 link/copy 到 (2) 的 snapshots/main/ 下
    """
    import shutil
    from pathlib import Path

    HF_CACHE = Path(os.path.expanduser("~/.cache/huggingface/hub"))
    HF_REPO = HF_CACHE / "models--BAAI--bge-large-zh-v1.5"
    HF_SNAPSHOT = HF_REPO / "snapshots" / "main"

    # 已存在 → 直接返回
    if HF_SNAPSHOT.exists() and (HF_SNAPSHOT / "config.json").exists():
        return

    # 找 exe 同目录的 ./models/BAAI/bge-large-zh-v1.5/
    candidates = []
    if getattr(sys, "frozen", False):
        # frozen: sys.executable = exe 路径
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "models" / "BAAI" / "bge-large-zh-v1.5")
    # dev 模式：检查多个可能的 models 路径
    # 1) 项目下的 qwen-chat-test/models/
    candidates.append(PROJECT_DIR / "models" / "BAAI" / "bge-large-zh-v1.5")
    # 2) 项目根目录下的 models/（如 E:\chat_v2\models\...）
    candidates.append(PROJECT_DIR.parent / "models" / "BAAI" / "bge-large-zh-v1.5")
    # 3) 当前工作目录下的 models/
    candidates.append(Path(os.getcwd()) / "models" / "BAAI" / "bge-large-zh-v1.5")
    # 4) utils/ 目录下的 models/（dl_bge_large.py 的默认下载位置）
    candidates.append(PROJECT_DIR / "utils" / "models" / "BAAI" / "bge-large-zh-v1.5")

    src = None
    for c in candidates:
        if c.exists() and (c / "config.json").exists():
            src = c
            break

    if src is None:
        # 都没有
        raise RuntimeError(
            f"bge-large-zh-v1.5 模型未找到.\n"
            f"查找位置:\n"
            f"  - {HF_SNAPSHOT}\n"
            f"  - {[str(c) for c in candidates]}\n\n"
            f"解决方法:\n"
            f"  1) 拷贝 dist/models/ 整个目录到 exe 同目录(推荐)\n"
            f"  2) 或从 HuggingFace 下载: https://huggingface.co/BAAI/bge-large-zh-v1.5"
        )

    # 链接到 HF cache 的 snapshots/main/
    print(f"[bge] linking {src} → {HF_SNAPSHOT}", flush=True)
    HF_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    if HF_SNAPSHOT.exists():
        # 清掉之前可能创建的空目录或残骸
        try:
            if HF_SNAPSHOT.is_symlink():
                HF_SNAPSHOT.unlink()
            else:
                shutil.rmtree(HF_SNAPSHOT)
        except OSError:
            pass
    try:
        os.symlink(src, HF_SNAPSHOT)
        print(f"[bge] symlinked OK", flush=True)
    except OSError:
        # 复制 (1.3GB 慢但稳)
        print(f"[bge] symlink failed, copying (1.3GB, ~1-3 min)...", flush=True)
        shutil.copytree(src, HF_SNAPSHOT)
        print(f"[bge] copied OK", flush=True)


# ---------- 文本 / JSON 导入(手动整理用) ----------
def parse_wechat_export(text: str) -> list[dict]:
    """把聊天文本解析成 [{role, text}] 列表.

    主要用途:用户在本地编辑 chat_extracted.txt 后重新上传.
    也支持手编 markdown / JSON 格式自动检测.

    支持的格式(自动检测):
    A) 已标准格式:[对方] xxx / [本人] xxx(每行一条)
    B) Markdown: **TA** 10:30\\n> 内容  /  **我** 10:32\\n> 回复
    C) 通用 JSON: [{ "senderName": "...", "content": "...", ... }]
    D) 简单格式:对方: xxx / 我: xxx

    返回:[{role: "对方"|"本人", text: str}]
    """
    import json as _json

    text = text.strip()
    if not text:
        return []

    # 1) 尝试 JSON
    if text.startswith("[") or text.startswith("{"):
        try:
            data = _json.loads(text)
            if isinstance(data, dict):
                data = data.get("messages", [])
            msgs = []
            for m in data:
                if not isinstance(m, dict):
                    continue
                content = m.get("content") or m.get("parsedContent") or m.get("rawContent") or ""
                content = str(content).strip()
                if not content or (content.startswith("[") and content.endswith("]")):
                    continue
                is_send = m.get("isSend")
                if is_send == 1 or is_send is True:
                    role = "本人"
                elif is_send == 0 or is_send is False:
                    role = "对方"
                else:
                    sender = (m.get("senderName") or m.get("accountName") or
                              m.get("sourceName") or m.get("sender") or "")
                    if any(k in str(sender) for k in ("我", "本人")):
                        role = "本人"
                    else:
                        role = "对方"
                msgs.append({"role": role, "text": content})
            if msgs:
                return msgs
        except Exception:
            pass

    # 2) 文本/Markdown 解析
    lines = text.splitlines()

    pat_a = re.compile(r"\[(对方|本人)]\s*(.+)")
    # Markdown: **TA** [时间戳] [可选内容]
    pat_b = re.compile(r"\*\*(TA|对方|我|本人|me|you|other|him|her)\*\*\s*(.*)$", re.IGNORECASE)
    pat_d = re.compile(r"^(对方|本人|我|TA)[::]\s*(.+)")
    quote_pat = re.compile(r"^>\s*(.+)")
    time_only_pat = re.compile(r"^\d{1,2}[::]\d{2}([::]\d{2})?(\s+\d{1,2}[/.月]\d{1,2}[日]?)?\s*$")
    time_pat = re.compile(r"^\d{1,2}[::]\d{2}([::]\d{2})?(\s|$)")
    date_pat = re.compile(r"^\d{4}[-/.年]\d{1,2}([-/.月]\d{1,2})?(日)?(\s|$|T)")

    out = []
    current_speaker = None  # '对方' / '本人'

    def normalize_speaker(s: str) -> str:
        s = s.strip()
        if s in ("本人", "我", "me"):
            return "本人"
        return "对方"  # 默认 TA/对方/其他都是对方

    def is_metadata_line(s: str) -> bool:
        s = s.strip()
        if not s:
            return True
        if s.startswith("# "):
            return True  # 一级标题
        if s in ("---", "***", "==="):
            return True
        if set(s) <= {"-", "*", "=", " "}:
            return True
        # 单独的时间戳/日期行
        if time_pat.match(s) and len(s) < 12:
            return True
        if date_pat.match(s) and len(s) < 14:
            return True
        return False

    for line in lines:
        raw = line
        line = line.strip()
        if not line:
            continue

        # 模式 A: [对方] / [本人]
        m = pat_a.match(line)
        if m:
            role = m.group(1)
            content = time_pat.sub("", m.group(2)).strip()
            if content:
                out.append({"role": role, "text": content})
                current_speaker = role
                continue

# 模式 B: **TA** [时间戳] [可选内容]
        m = pat_b.match(line)
        if m:
            speaker = normalize_speaker(m.group(1))
            rest = (m.group(2) or "").strip()
            # 如果剩下的只是时间戳(没内容),只切换 speaker
            if not rest or time_only_pat.match(rest) or time_pat.match(rest):
                current_speaker = speaker
                continue
            # 否则是内联内容(少见),append 一条消息
            content = time_pat.sub("", rest).strip()
            if content:
                out.append({"role": speaker, "text": content})
                current_speaker = speaker
            continue

        # 模式 D: 对方: xxx
        m = pat_d.match(line)
        if m:
            role = normalize_speaker(m.group(1))
            content = time_pat.sub("", m.group(2)).strip()
            if content:
                out.append({"role": role, "text": content})
                current_speaker = role
                continue

        # Markdown 引用块: > 内容
        m = quote_pat.match(line)
        if m and current_speaker:
            content = time_pat.sub("", m.group(1)).strip()
            if content:
                if out and out[-1]["role"] == current_speaker:
                    out[-1]["text"] += " " + content
                else:
                    out.append({"role": current_speaker, "text": content})
                continue

        # 元数据行跳过
        if is_metadata_line(line):
            continue

        # 续行(无 speaker 标记)
        if current_speaker and out:
            out[-1]["text"] += " " + line

    return out


async def run_import_text(text: str, source_label: str = "edited-text") -> dict:
    """解析聊天文本(用户编辑 chat_extracted.txt 后重新上传)→ append 到 chat_extracted.txt."""
    msgs = parse_wechat_export(text)
    if not msgs:
        raise RuntimeError("未能从文本中解析出任何消息,请检查格式(支持 [对方]/[本人],Markdown,JSON)")

    # 写文件(追加)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CHAT_TXT.open("a", encoding="utf-8") as f:
        if source_label:
            f.write(f"\n# --- imported from {source_label} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        for m in msgs:
            f.write(f"[{m['role']}] {m['text']}\n")

    return {
        "imported": len(msgs),
        "source": source_label,
        "preview": "\n".join(f"[{m['role']}] {m['text']}" for m in msgs[:20]),
    }


# ---------- 模型预热（避免 PaddleOCR 与 PyTorch DLL 冲突）----------
def _warmup_torch():
    """服务器启动时预热 torch + sentence-transformers，让 DLL 先加载。
    
    PaddleOCR（PaddlePaddle）和 PyTorch 在 Windows 下存在 shm.dll 冲突，
    必须先加载 torch，再加载 PaddlePaddle。
    """
    try:
        import torch as _t
        import sentence_transformers as _st
        print("[warmup] torch + sentence-transformers loaded OK", flush=True)
    except Exception as e:
        print(f"[warmup] torch/sentence-transformers load failed: {e}", flush=True)
        print("[warmup] RAG 索引重建可能需要单独处理", flush=True)

_warmup_torch()


# ---------- 输出后校验(防编造) ----------
from hallucination_guard import guard_reply, reset_chat_index


# ---------- RAG 检索(增强版,带上下文感知) ----------
def build_rag_context(user_input: str, top_k: int = 4, conversation_history: list = None) -> tuple[str, int, list[dict]]:
    """调用 rag_search 检索相关聊天片段,格式化注入.

    返回:(rag_context_string, num_chunks, raw_chunks)
    """
    try:
        from rag_search import search as rag_search
        results = rag_search(
            user_input,
            top_k=top_k,
            role_filter="对方",
            min_score=0.30,
            conversation_history=conversation_history,
        )
        if not results:
            return "", 0, []
        chunks_text = "\n".join(f"- {r['text']}" for r in results)
        return RAG_INJECTION_TEMPLATE.format(chunks=chunks_text), len(results), results
    except Exception as e:
        print(f"[warn] RAG search failed: {e}", file=sys.stderr)
        return "", 0, []


# ---------- API 路由 ----------
@app.get("/")
def root():
    # 如果前端 dist 存在，返回 SPA 页面（支持浏览器直接访问后端端口）
    spa_path = ROOT_DIR / "frontend" / "dist" / "index.html"
    if spa_path.exists():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(spa_path.read_text(encoding="utf-8"))
    return {"name": "MemoirAI API", "version": "0.2.0", "ok": True}


# Chrome DevTools 自动探测 + 一些浏览器健康检查端点 — 让它们 200/204 避免日志噪音
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_probe():
    """Chrome 启动时会请求这个端点探测 DevTools 配置.所有站点都会 404,
    我们返 200 + 空对象让日志干净."""
    return {}


@app.get("/favicon.ico")
def favicon():
    """避免 favicon 404(虽然有 static 兜底,但这里 fast-path)."""
    return Response(status_code=204)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/profile")
def get_profile():
    profile = read_json_safe(PROFILE_JSON, None)
    if profile is None:
        raise HTTPException(404, "memorial_profile.json not found")
    return profile


@app.put("/api/profile")
async def update_profile(payload: dict):
    """更新 memorial_profile.json 的可编辑字段.

    可编辑字段:
      基础身份:name / gender / age / relationship / self_reference / user_reference
      性格与风格:personality_traits / speaking_style / catchphrases / key_memories / emotional_patterns
      prompt:system_prompt(用户手写的人格 prompt)

    受保护字段:few_shots(对话示范,由 setup_memorial.py / 重新生成时管理)
    """
    profile = read_json_safe(PROFILE_JSON, None)
    if profile is None:
        profile = {}

    # 列表字段(前端可能传 string 或 list)
    list_fields = ("personality_traits", "catchphrases", "key_memories")

    # 受保护字段(不允许通过这个端点修改)
    protected = ("few_shots",)

    for key, val in payload.items():
        if val is None:
            continue
        if key in protected:
            continue
        if key in list_fields:
            if isinstance(val, str):
                val = [s.strip() for s in re.split(r"[,\n,,]+", val) if s.strip()]
            elif isinstance(val, list):
                val = [str(s).strip() for s in val if str(s).strip()]
            else:
                continue
        elif key in ("name", "gender", "age",
                     "relationship", "self_reference", "user_reference",
                     "speaking_style", "emotional_patterns", "system_prompt"):
            val = str(val).strip()
        else:
            # 未知字段:忽略(不主动给后面留坑)
            continue
        if val == "" or val == []:
            # 用户清空:删除该字段(清空 system_prompt 会让它降级到 FALLBACK_SYSTEM)
            profile.pop(key, None)
            continue
        profile[key] = val

    PROFILE_JSON.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 清缓存
    reset_system_prompt_cache()

    return {"ok": True, "profile": profile}


@app.post("/api/regenerate-profile")
async def regenerate_profile_endpoint():
    """调 LLM 基于现有 profile + 聊天记录,重新生成 system_prompt 和人格画像.

    用于:用户改完称呼/关系后,让 AI 真的知道自己是谁.
    """
    profile = read_json_safe(PROFILE_JSON, None)
    if profile is None:
        raise HTTPException(400, "memorial_profile.json not found, run setup_memorial.py first")

    if not CHAT_TXT.exists():
        raise HTTPException(400, "chat_extracted.txt not found, run OCR first")
    chat_text = read_text_safe(CHAT_TXT)
    if len(chat_text.strip()) < 50:
        raise HTTPException(400, "chat_extracted.txt too short")

    # 调 LLM
    client = get_llm_client()
    model_id = get_model_id()

    def _run():
        from regenerate_profile import regenerate_profile as regen
        kwargs = dict(client=client, model=model_id, profile=profile, chat_text=chat_text)
        # vLLM / 本地模型需要关闭 thinking 模式
        if get_current_provider() in ("vllm", "local"):
            return regen(**kwargs, extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        else:
            return regen(**kwargs)

    loop = asyncio.get_event_loop()
    try:
        new_profile = await loop.run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f"regenerate failed: {e}")

    # 写回
    PROFILE_JSON.write_text(
        json.dumps(new_profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    reset_system_prompt_cache()

    return {"ok": True, "profile": new_profile}


# ---------- /api/chat ----------
# 聊天入口:拼 system_prompt + 可选 RAG chunks,调 vLLM
from pydantic import BaseModel
from typing import Optional

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    use_rag: bool = True
    temperature: float = 0.7
    max_tokens: int = 300  # DeepSeek reasoning 会占用大量 max_tokens budget,给足空间
    session_id: Optional[str] = None  # 会话ID(Agent Memory 三层架构用)

# 缓存 OpenAI client 和 system prompt
_llm_client: Optional[OpenAI] = None
_llm_client_cfg_key: Optional[str] = None  # 用于检测 settings 变化后清缓存
_cached_system_prompt: Optional[str] = None
_cached_model_id: Optional[str] = None

# ---------- Memory Manager(Agent Memory 三层架构)----------
_mm_instance = None

def get_memory_manager():
    global _mm_instance
    if _mm_instance is None:
        from agent_memory import MemoryManager
        _mm_instance = MemoryManager()
    return _mm_instance


def get_llm_client() -> OpenAI:
    """返回 LLM client(用 user settings 的 key,没有则抛出清晰错误)"""
    global _llm_client, _llm_client_cfg_key
    cfg = _get_llm_config()
    if not cfg["key"]:
        raise HTTPException(400, "LLM API key 未配置，请在设置页填写 API key")
    cfg_key = f"{cfg['provider']}|{cfg['base']}|{cfg['key'][:8]}"
    if _llm_client is None or _llm_client_cfg_key != cfg_key:
        _llm_client = OpenAI(base_url=cfg["base"], api_key=cfg["key"])
        _llm_client_cfg_key = cfg_key
    return _llm_client


def get_current_provider() -> str:
    """返回当前 provider id"""
    s = _load_settings()
    return (s.get("llm_provider") or LLM_PROVIDER or "deepseek").strip().lower()


def get_model_id() -> str:
    """返回当前模型 id(优先 settings / env)"""
    global _cached_model_id
    if _cached_model_id is None:
        cfg = _get_llm_config()
        if cfg["model"]:
            _cached_model_id = cfg["model"]
        else:
            try:
                models = get_llm_client().models.list().data
                _cached_model_id = models[0].id if models else "deepseek-v4-flash"
            except Exception:
                _cached_model_id = "deepseek-v4-flash"
    return _cached_model_id

def reset_llm_cache():
    """settings 改了之后清缓存(下次 chat 用新 key/model)"""
    global _llm_client, _llm_client_cfg_key, _cached_model_id
    _llm_client = None
    _llm_client_cfg_key = None
    _cached_model_id = None


def get_full_system_prompt() -> str:
    """从 memorial_profile 加载 system_prompt + few_shots(懒加载 + 缓存)."""
    global _cached_system_prompt
    if _cached_system_prompt is None:
        from memorial_profile import get_system_prompt, get_few_shots_context, FALLBACK_SYSTEM
        sys_p = get_system_prompt()
        if not sys_p:
            sys_p = FALLBACK_SYSTEM  # 单一来源:memorial_profile.FALLBACK_SYSTEM
        fs_ctx = get_few_shots_context()
        if fs_ctx:
            sys_p = sys_p + fs_ctx
        _cached_system_prompt = sys_p
    return _cached_system_prompt


def reset_system_prompt_cache():
    """memorial_profile.json 更新后调用此函数清缓存."""
    global _cached_system_prompt
    _cached_system_prompt = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """接收 messages(user/assistant 历史),拼 system+RAG+Memory,调 LLM,返回回复."""
    # 0. 速率限制（每 IP 每分钟最多 30 次聊天请求）
    if not _check_rate_limit("default", max_per_minute=30):
        raise HTTPException(429, "请求过于频繁，请稍候再试")
    # 1. 过滤掉空内容消息
    filtered = [m for m in req.messages if m.content and m.content.strip()]
    if not filtered:
        raise HTTPException(400, "messages is empty")

    # 2. 限制 max_tokens
    max_tokens = max(1, min(int(req.max_tokens or 300), 4000))

    # 3. 获取 Memory Manager(如果 session_id 存在)
    mm = get_memory_manager()
    session_id = req.session_id
    session = None
    memory_context = None
    if session_id:
        session = mm.load_session(session_id)
        if session:
            # 获取当前对话上下文(最后一条用户输入用于 RAG)
            last_user = next((m.content for m in reversed(filtered) if m.role == "user"), "")
            memory_context = mm.build_chat_context(session_id, last_user)

    # 4. 拼 messages:system + Skills + 可选语义记忆 + 情景摘要 + RAG + 工作记忆
    messages = [{"role": "system", "content": get_full_system_prompt()}]

    # Skills 层: 注入所有非元技能的 prompt（000_profile + 001_style + 002_memory + 003_boundary + 005_insights）
    try:
        from skill_engine import get_skill_manager
        smgr = get_skill_manager()
        skills_prompt = smgr.get_skills_prompt()
        if skills_prompt:
            messages.append({"role": "system", "content": skills_prompt})
    except Exception:
        pass

    # 语义记忆:相关事实注入
    if memory_context and memory_context.get("semantic_facts"):
        from agent_memory import SemanticMemory
        sm = SemanticMemory()
        semantic_prompt = sm.format_for_prompt(memory_context["semantic_facts"])
        if semantic_prompt:
            messages.append({"role": "system", "content": semantic_prompt})

    # 主动记忆触发:检测到相关话题时指导 LLM 自然提起回忆
    if memory_context and memory_context.get("triggers"):
        from agent_memory import SemanticMemory
        sm = SemanticMemory()
        trigger_prompt = sm.format_triggers_for_prompt(memory_context["triggers"])
        if trigger_prompt:
            messages.append({"role": "system", "content": trigger_prompt})

    # 风格进化:注入用户交互模式提示
    try:
        from agent_memory import StyleProfile
        sp = StyleProfile()
        style_hint = sp.get_style_hint()
        if style_hint:
            messages.append({"role": "system", "content": f"\n# 风格提示（基于历史交互自动学习）\n{style_hint}"})
    except Exception:
        pass

    # 情感智能:检测用户情绪,注入语气指导
    try:
        from agent_memory import EmotionDetector
        last_user = next((m.content for m in reversed(filtered) if m.role == "user"), "")
        if last_user:
            emotion = EmotionDetector.detect(last_user)
            if emotion.get("hint"):
                messages.append({"role": "system", "content": f"\n# 语气指导\n{emotion['hint']}"})
    except Exception:
        pass
    except Exception:
        pass

    # 情景摘要:如果 session 有 summary,注入作为历史背景
    if memory_context and memory_context.get("session_summary"):
        summary_text = memory_context["session_summary"]
        if summary_text:
            messages.append({"role": "system", "content": f"\n\n# 之前的对话摘要\n{summary_text}"})

    n_rag = 0
    raw_rag_chunks = []
    if req.use_rag:
        last_user = next((m.content for m in reversed(filtered) if m.role == "user"), "")
        if last_user:
            # 传入 conversation history 用于上下文感知检索
            history = [{"role": m.role, "content": m.content} for m in filtered]
            rag_ctx, n_rag, raw_rag_chunks = build_rag_context(last_user, top_k=4, conversation_history=history)
            if rag_ctx:
                messages.append({"role": "system", "content": rag_ctx})

    # 工作记忆:如果 session 存在,从 session 取最近 N 轮;否则用前端传来的 messages
    if session and memory_context:
        working = memory_context.get("working_memory", [])
        if working:
            # 用 session 的 working memory(后端持久化)替代前端传来的
            messages.extend({"role": t["role"], "content": t["content"]} for t in working)
        else:
            messages.extend({"role": m.role, "content": m.content} for m in filtered)
        # 追加最新的用户输入（不在 working memory 中）
        last_user = next((m.content for m in reversed(filtered) if m.role == "user"), "")
        if last_user:
            messages.append({"role": "user", "content": last_user})
    else:
        messages.extend({"role": m.role, "content": m.content} for m in filtered)
    
    # 5. 调 LLM
    client = get_llm_client()
    model_id = get_model_id()

    def _call():
        kwargs = dict(
            model=model_id,
            messages=messages,
            temperature=req.temperature,
            top_p=0.85,
            max_tokens=max_tokens,
        )
        # vLLM / 本地模型需要额外参数关闭 thinking 模式
        provider = get_current_provider()
        if provider in ("vllm", "local"):
            kwargs["extra_body"] = {
                "repetition_penalty": 1.05,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        return client.chat.completions.create(**kwargs)

    loop = asyncio.get_event_loop()
    try:
        resp = await loop.run_in_executor(None, _call)
    except Exception as e:
        raise HTTPException(502, f"{get_current_provider()} call failed: {e}")

    # 调试日志
    print(f"[chat] model={model_id} finish={resp.choices[0].finish_reason} "
          f"content_len={len(resp.choices[0].message.content or '')} "
          f"raw_content={repr((resp.choices[0].message.content or '')[:100])}",
          file=sys.stderr, flush=True)
    if hasattr(resp, 'usage') and resp.usage:
        print(f"[chat] usage: {resp.usage}", file=sys.stderr, flush=True)

    raw_reply = (resp.choices[0].message.content or "").strip()

    # 6. 保存到 session(如果有 session_id)
    if session and session_id:
        last_user_msg = next((m.content for m in reversed(filtered) if m.role == "user"), "")
        mm.save_turn(session_id, last_user_msg, raw_reply)
        # 重新加载 session 获取最新 turn_count
        updated_session = mm.load_session(session_id)
        updated_turns = updated_session.turn_count if updated_session else 0
        # 检查是否需要摘要(异步触发,不阻塞)
        if updated_turns >= 20 and not (updated_session and updated_session.summary):
            try:
                await loop.run_in_executor(None, lambda: mm.summarize_session(session_id, client, model_id))
            except Exception as e:
                print(f"[memory] summarize async failed: {e}", file=sys.stderr, flush=True)
        # 检查是否需要提取语义事实(每 6 轮一次)
        if updated_turns > 0 and updated_turns % 6 == 0:
            try:
                await loop.run_in_executor(None, lambda: mm.extract_semantic_facts(session_id, client, model_id))
            except Exception as e:
                print(f"[memory] extract facts async failed: {e}", file=sys.stderr, flush=True)

        # 记录风格画像（每 6 轮更新一次）
        if updated_turns > 0 and updated_turns % 6 == 0:
            try:
                from agent_memory import StyleProfile
                sp = StyleProfile()
                topics = [m.content for m in filtered if m.role == "user"][:3] if filtered else []
                sp.record_session_end(updated_turns, topics=topics[:3])
            except Exception as e:
                print(f"[style] profile update failed: {e}", file=sys.stderr, flush=True)

        # Skill Evolution：每 100 轮触发一次 005_insights 更新
        if updated_turns > 0 and updated_turns % 100 == 0:
            try:
                from skill_engine import get_skill_manager
                smgr = get_skill_manager()
                # 收集最近 N 轮对话文本
                recent_turns = updated_session.turns[-100:] if updated_session else []
                turns_text = "\n".join(
                    f"{'用户' if t['role']=='user' else 'AI'}: {t['content']}"
                    for t in recent_turns
                )
                print(f"[skill] triggering evolution at {updated_turns} turns...", flush=True)
                await loop.run_in_executor(
                    None, lambda: smgr.evolve_insights(turns_text, client, model_id)
                )
            except Exception as e:
                print(f"[skill] evolution failed: {e}", file=sys.stderr, flush=True)

    # 7. 输出后校验:防编造
    guard_result = None
    if raw_reply:
        try:
            guard_result = guard_reply(raw_reply, raw_rag_chunks)
            if guard_result["status"] == "blocked":
                print(f"[guard] BLOCKED: {guard_result['reason']} "
                      f"original={raw_reply[:80]}... "
                      f"replaced={guard_result['reply']}",
                      file=sys.stderr, flush=True)
            elif guard_result["status"] == "warning":
                print(f"[guard] WARNING: {guard_result['reason']}", file=sys.stderr, flush=True)
            else:
                print(f"[guard] OK: {guard_result['reason']}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[guard] error: {e}", file=sys.stderr, flush=True)
            guard_result = None

    # 最终回复
    reply = guard_result["reply"] if guard_result and guard_result["status"] == "blocked" else raw_reply

    # 8. 构造响应
    response = {
        "reply": reply,
        "model": model_id,
        "rag_chunks": n_rag,
        "session_id": session_id,
    }

    if guard_result:
        response["guard_info"] = {
            "status": guard_result["status"],
            "reason": guard_result["reason"],
            "entities_count": len(guard_result.get("entities", [])),
            "unverified_count": len(guard_result.get("unverified", [])),
        }
        if guard_result["status"] == "blocked":
            response["guard_info"]["original_reply_preview"] = guard_result.get("original_reply", "")[:80] + "..."

    if raw_rag_chunks:
        response["rag_references"] = [
            {
                "role": c["role"],
                "text_preview": c["text"][:100] + "..." if len(c["text"]) > 100 else c["text"],
                "score": c["score"],
                "verified": c.get("verified", True),
            }
            for c in raw_rag_chunks
        ]

    return response


@app.get("/api/stats")
def stats():
    meta = read_json_safe(INDEX_DIR / "meta.json", {})
    return {
        "screenshots": count_screenshots(),
        "messages": count_lines(CHAT_TXT),
        "chunks": meta.get("num_chunks", "-"),
        "model": meta.get("model", "-"),
        "vector_dim": meta.get("vector_dim", "-"),
    }


def _status_inner():
    """前端总检查:返回各模块是否就绪,替代原来的 /v1/models(老 vLLM 接口,早就废了)."""
    import os as _os
    from pathlib import Path as _P

    # 1) profile
    profile_ok = PROFILE_JSON.exists()
    profile_has_system = False
    if profile_ok:
        try:
            p = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
            profile_has_system = bool(p.get("system_prompt"))
        except Exception:
            pass

    # 2) LLM(当前 provider 的 key 已配置即可)
    cfg = _get_llm_config()
    llm_ok = bool(cfg["key"] and cfg["key"].strip())
    provider_name = BUILTIN_PROVIDERS.get(cfg["provider"], {}).get("name", cfg["provider"])

    # 3) RAG 索引
    index_ok = (INDEX_DIR / "vectors.npy").exists() and (INDEX_DIR / "chunks.json").exists()
    chunks = 0
    if index_ok:
        try:
            chunks = len(json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8")))
        except Exception:
            index_ok = False

    # 4) TTS(edge 免费)
    tts_ok = True
    tts_msg = "edge 引擎(免费)"

    # 5) 聊天文本
    chat_ok = CHAT_TXT.exists() and CHAT_TXT.stat().st_size > 0

    # 综合判断:核心三件套(profile/llm/chat)OK 即可对话;TTS/RAG 是可选加成
    ready = profile_ok and llm_ok and chat_ok

    msgs = []
    if not profile_ok:
        msgs.append("还没生成逝者画像(先在 `/upload` 跑 OCR → 自动建)")
    if not llm_ok:
        msgs.append(f"还没填 {provider_name} API key(去 `/settings` 粘贴)")
    if not chat_ok:
        msgs.append("还没导入聊天记录(去 `/upload` 用截图 OCR)")
    if not index_ok:
        msgs.append("RAG 索引未建(聊天里能答但风格弱,OCR 后会自动建)")

    return {
        "ready": ready,
        "model": cfg["model"],
        "provider": cfg["provider"],
        "provider_name": provider_name,
        "checks": {
            "profile": profile_ok,
            "profile_system_prompt": profile_has_system,
            "llm": llm_ok,
            "chat_data": chat_ok,
            "rag_index": index_ok,
            "rag_chunks": chunks,
        },
        "message": ";".join(msgs) if msgs else "一切就绪,可以聊天",
    }


@app.get("/api/status")
def status():
    try:
        return _status_inner()
    except Exception as e:
        import traceback as _tb
        return {"error": str(e), "traceback": _tb.format_exc()}


@app.post("/api/upload-screenshots")
async def upload_screenshots(
    files: list[UploadFile] = File(...),
    rebuild: str = "auto",  # auto | skip
    enable_bailian_ocr: bool = Form(False),
):
    """接收聊天截图,跑 OCR,更新 chat_extracted.txt.

    exe 模式:通过 MemorialOCR.exe(独立 OCR service)跑 OCR
    dev 模式:in-process PaddleOCR

    默认 OCR 完自动 rebuild RAG 索引(?rebuild=skip 可关闭).
    """
    if not files:
        raise HTTPException(400, "no files uploaded")

    # 保存到临时目录（用 DATA_DIR 而非 BACKEND_DIR，frozen 模式下临时目录不可写）
    tmp_dir = DATA_DIR / "_tmp_uploads"
    tmp_dir.mkdir(exist_ok=True)
    saved_paths = []
    for f in files:
        ts = int(time.time() * 1000)
        safe_name = re.sub(r"[^\w.\-]", "_", f.filename or "upload")
        dst = tmp_dir / f"{ts}_{safe_name}"
        with dst.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(dst)

    # 跑 OCR
    before_count = count_lines(CHAT_TXT)
    try:
        result = await run_ocr(saved_paths, enable_bailian=enable_bailian_ocr)
    except Exception as e:
        # 清理临时
        for p in saved_paths:
            p.unlink(missing_ok=True)
        hint = ""
        err_str = str(e)
        if "No module named" in err_str:
            hint = "（提示：OCR 依赖缺失，请用 dev 模式启动（python -m uvicorn api:app）或启用百炼 OCR 增强）"
        raise HTTPException(500, f"OCR failed: {e}{hint}")

    after_count = count_lines(CHAT_TXT)
    new_count = after_count - before_count

    # 自动 rebuild 索引(新增了对话才需要;纯重复 OCR 不重做)
    rebuild_meta = None
    rebuild_error = None
    if rebuild == "auto" and new_count > 0:
        try:
            rebuild_meta = await run_rebuild_index()
        except Exception as e:
            rebuild_error = str(e)

    # 聊天数据变了,清 hallucination_guard 的缓存索引(下次 chat 会重新建)
    try:
        reset_chat_index()
    except Exception:
        pass

    return {
        "message_count": len(result["messages"]),
        "new_count": new_count,
        "preview": result["preview"],
        "saved_files": result["saved_files"],
        "rebuilt": rebuild_meta is not None,
        "rebuild_meta": rebuild_meta,
        "rebuild_error": rebuild_error,
    }


@app.post("/api/rebuild-index")
async def rebuild_index():
    """重建 RAG 向量索引."""
    try:
        meta = await run_rebuild_index()
    except Exception as e:
        raise HTTPException(500, f"rebuild failed: {e}")
    return meta


@app.post("/api/reset-data")
def reset_data():
    """清空已上传的聊天记录和 RAG 索引.

    删除:
    - data/chat_extracted.txt(提取出的对话文本)
    - data/screenshots/*(OCR 上传的截图)
    - data/rag_index/*(向量 + chunks + meta)

    保留:
    - memorial_profile.json(人格画像)
    - user_settings.json(API key 等设置)
    - voice_samples/(声音样本 + 元数据)

    ⚠️ 不可逆.请让用户先确认.
    """
    import shutil as _shutil
    deleted = {"chat_txt": False, "screenshots": 0, "index_files": 0, "index_dirs_removed": 0}
    errors = []

    def _remove_file(p: Path):
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
                return 1
            return 0
        except FileNotFoundError:
            return 0
        except Exception as e:
            errors.append(f"{p.name}: {e}")
            return 0

    # 1) chat_extracted.txt
    if CHAT_TXT.exists():
        if _remove_file(CHAT_TXT):
            deleted["chat_txt"] = True

    # 2) screenshots/* — 删空整个目录(含 .gitkeep 之类的隐藏残留)
    if SCREENSHOTS_DIR.exists():
        for p in SCREENSHOTS_DIR.iterdir():
            deleted["screenshots"] += _remove_file(p)
        try:
            _shutil.rmtree(SCREENSHOTS_DIR)
            # 重置后立刻重建空目录,保持 layout 一致
            SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"screenshots_dir: {e}")

    # 3) rag_index/* — 删文件 + 删空目录(保证下次 rebuild 是全新状态)
    if INDEX_DIR.exists():
        for p in INDEX_DIR.iterdir():
            deleted["index_files"] += _remove_file(p)
        # 删除整个目录(含可能的 __pycache__ 等),让下一次重建时彻底空
        try:
            _shutil.rmtree(INDEX_DIR)
            deleted["index_dirs_removed"] = 1
        except FileNotFoundError:
            pass
        except Exception as e:
            errors.append(f"index_dir: {e}")

    # 清 rag_search 的内存缓存(下次查询会从空目录重新加载)
    try:
        from rag_search import _state as _rag_state
        _rag_state["model"] = None
        _rag_state["chunks"] = None
        _rag_state["vectors"] = None
    except Exception:
        pass

    # 清 hallucination_guard 的聊天记录索引缓存
    try:
        reset_chat_index()
    except Exception:
        pass

    print(f"[reset-data] deleted={deleted} errors={errors}", file=sys.stderr, flush=True)
    return {
        "ok": True,
        "deleted": deleted,
        "errors": errors,
        "kept": [
            "memorial_profile.json",
            "user_settings.json",
            "voice_samples/",
        ],
        "note": "已清空聊天记录和 RAG 索引.重新上传聊天数据后会再次重建索引.",
    }


@app.post("/api/import-text")
async def import_text(file: UploadFile = File(...)):
    """导入用户编辑后的聊天文本(接 OCR 之后的修正流程).

    支持格式(自动检测):
    - [对方]/[本人] 一行一条(最简单)
    - Markdown:**对方** xxx / **我** xxx
    - 通用 JSON(含 senderName / isSend 字段)
    """
    try:
        raw = await file.read()
    except Exception as e:
        raise HTTPException(400, f"read failed: {e}")
    # 尝试多种编码
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "无法解码文件,请用 UTF-8 或 GBK 编码")

    print(f"[import-text] filename={file.filename} size={len(raw)} decoded_chars={len(text)}", file=sys.stderr, flush=True)

    try:
        result = await run_import_text(text, source_label=file.filename or "upload")
    except Exception as e:
        print(f"[import-text] parse failed: {e}", file=sys.stderr, flush=True)
        raise HTTPException(400, f"parse/import failed: {e}")

    # 自动 rebuild index(让 RAG 立即生效)
    try:
        meta = await run_rebuild_index()
        result["index"] = meta
    except Exception as e:
        print(f"[import-text] rebuild failed: {e}", file=sys.stderr, flush=True)
        result["index_error"] = str(e)

    # 聊天数据变了,清 hallucination_guard 的缓存索引
    try:
        reset_chat_index()
    except Exception:
        pass

    return result


@app.post("/api/audio-to-text")
async def audio_to_text(file: UploadFile = File(...)):
    '''上传音频文件,ASR 转文字.'''
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")

    # 保存到临时文件(faster-whisper 需要文件路径)
    ext = Path(file.filename or "audio.wav").suffix.lower()
    if ext not in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
        ext = ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    settings = _load_settings()
    asr_engine = (settings.get("asr_engine") or "faster-whisper").strip().lower()

    transcript = ""
    transcript_lang = ""

    try:
        if asr_engine == "bailian":
            transcript, transcript_lang = await _bailian_asr(raw, filename=file.filename or f"audio{ext}")
        else:
            # faster-whisper 本地 ASR
            try:
                from faster_whisper import WhisperModel
                import threading as _thr
                _whisper_state = {"model": None, "lock": _thr.Lock()}

                def _ensure_model():
                    with _whisper_state["lock"]:
                        if _whisper_state["model"] is None:
                            print("[audio-to-text] loading whisper base model...", file=sys.stderr, flush=True)
                            _whisper_state["model"] = WhisperModel("base", device="cpu", compute_type="int8")
                        return _whisper_state["model"]

                def _do_asr(path_str):
                    m = _ensure_model()
                    segs, info = m.transcribe(path_str, language="zh", beam_size=5)
                    return "".join(s.text for s in segs).strip(), info.language

                loop = asyncio.get_event_loop()
                transcript, transcript_lang = await loop.run_in_executor(None, _do_asr, tmp_path)
            except ImportError:
                raise HTTPException(500, "faster-whisper 未安装")
            except Exception as e:
                raise HTTPException(500, f"ASR 失败: {type(e).__name__}: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"text": transcript, "engine": asr_engine, "language": transcript_lang}


# ---------- TTS ----------
from fastapi.responses import Response
from pydantic import Field

VOICE_SAMPLES_DIR = DATA_DIR / "voice_samples"
VOICE_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_JSON = VOICE_SAMPLES_DIR / "samples.json"

# TTS 缓存:把每条合成结果落到本地,避免重复合成扣费(Fish 按字符计费)
TTS_CACHE_DIR = DATA_DIR / "tts_cache"
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _tts_preprocess(text: str) -> tuple[str, str]:
    """清理 TTS 文本，提取语气指令。

    括号内容 → 作为 instruction 传给 CosyVoice 指令控制
    括号 + emoji → 从朗读文本中移除

    Returns: (cleaned_text, instruction)
    """
    import re
    if not text:
        return text, ""

    # 1) 去掉 emoji
    text_no_emoji = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u27BF\uFE00-\uFE0F\u200D]', '', text)

    # 2) 提取所有 (中文) /（中文）块
    L = chr(0xFF08)
    R = chr(0xFF09)
    pattern = re.compile(fr'[\(${L}]([^\(\)${L}${R}\n]{{1,40}})[\)${R}]')

    instructions = []
    def collect(m):
        inner = m.group(1).strip()
        if inner:
            instructions.append(inner)
        return ""

    cleaned = pattern.sub(collect, text_no_emoji).strip()
    instruction = "；".join(instructions) if instructions else ""
    return cleaned, instruction


def _tts_cache_key(engine: str, text: str, voice: str | None, voice_id: str | None,
                   rate: str, pitch: str, volume: str, instruction: str = "") -> str:
    """算缓存 key.所有影响合成的字段都参与 hash."""
    raw = f"{engine}|{voice_id or ''}|{text}|{voice or ''}|{rate}|{pitch}|{volume}|{instruction}"
    import hashlib as _hl
    return _hl.sha1(raw.encode("utf-8")).hexdigest()


def _tts_cache_get(key: str) -> tuple[bytes, dict] | None:
    """命中返 (audio_bytes, meta),否则 None."""
    p = TTS_CACHE_DIR / f"{key}.mp3"
    if not p.exists():
        return None
    try:
        audio = p.read_bytes()
    except Exception:
        return None
    meta_p = TTS_CACHE_DIR / f"{key}.json"
    meta = {}
    if meta_p.exists():
        try:
            import json as _j
            meta = _j.loads(meta_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return audio, meta


def _tts_cache_put(key: str, audio: bytes, meta: dict) -> None:
    """把合成结果写到本地缓存."""
    try:
        import json as _j
        (TTS_CACHE_DIR / f"{key}.mp3").write_bytes(audio)
        (TTS_CACHE_DIR / f"{key}.json").write_text(
            _j.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception as e:
        print(f"[tts-cache] write failed: {e}", file=sys.stderr, flush=True)


def _tts_cache_stats() -> dict:
    """统计缓存大小."""
    files = list(TTS_CACHE_DIR.glob("*.mp3"))
    total_size = sum(p.stat().st_size for p in files)
    return {
        "count": len(files),
        "size_bytes": total_size,
        "size_mb": round(total_size / 1024 / 1024, 2),
        "dir": str(TTS_CACHE_DIR),
    }


def _load_samples_index() -> dict:
    if not SAMPLES_JSON.exists():
        return {}
    try:
        return json.loads(SAMPLES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_samples_index(idx: dict):
    SAMPLES_JSON.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None  # None = 后端按 f0 自动选男/女声;用户显式指定时用指定值
    rate: str = "+0%"   # 语速 -50% ~ +100%(覆盖自动分析)
    pitch: str = "+0Hz"  # 音调(覆盖自动分析)
    voice_id: Optional[str] = None  # 指向已上传的 voice sample
    volume: str = "+0%"
    engine: Optional[str] = None  # "edge" | "cosyvoice"


# 可选音色列表(让前端展示)
TTS_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓(女·温柔)", "gender": "female"},
    {"id": "zh-CN-YunxiNeural", "name": "云希(男·青年)", "gender": "male"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬(男·新闻)", "gender": "male"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊(女·甜)", "gender": "female"},
    {"id": "zh-CN-YunjianNeural", "name": "云健(男·体育)", "gender": "male"},
    {"id": "zh-CN-XiaomoNeural", "name": "晓墨(女·故事)", "gender": "female"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏(男·儿童)", "gender": "male"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北(女·东北)", "gender": "female"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮(女·陕西方言)", "gender": "female"},
]


async def _synthesize(text: str, voice: str, rate: str, pitch: str, volume: str = "+0%") -> bytes:
    """调 edge-tts 流式合成,返回 mp3 字节."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch, volume=volume)
    buf = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


@app.get("/api/tts/voices")
def list_tts_voices():
    return TTS_VOICES


# ---------- 声音样本管理 ----------

@app.get("/api/tts/samples")
def list_voice_samples():
    """列出所有已上传的声音样本."""
    idx = _load_samples_index()
    out = []
    for vid, info in idx.items():
        # 验证文件还在
        path = Path(info.get("path", ""))
        if path.exists():
            out.append({
                "voice_id": vid,
                "filename": info.get("filename"),
                "uploaded_at": info.get("uploaded_at"),
                "features": info.get("features"),
                "size": path.stat().st_size,
                "format": info.get("format"),
            })
    return {"samples": out}


@app.post("/api/tts/samples")
async def upload_voice_sample(
    file: UploadFile = File(...),
    voice_id: Optional[str] = Form(None),
    display_name: Optional[str] = Form(None),
):
    """上传逝者的声音样本(wav/mp3/m4a 等),分析特征,注册 voice_id.

    - voice_id: 自定义 ID(默认 = 文件名去扩展名)
    - 上传后自动提取:duration, f0_mean, speech_rate, rms
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")

    # 文件名清理
    raw_name = file.filename or "sample"
    safe_name = re.sub(r"[^\w.\-]", "_", raw_name)
    ext = Path(safe_name).suffix.lower() or ".audio"
    if ext not in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
        raise HTTPException(400, f"unsupported format: {ext}(仅支持 wav/mp3/m4a/aac/flac/ogg/opus)")

    # voice_id(保留中文,字母,数字,下划线,连字符;其他字符替换成 _)
    vid = (voice_id or Path(safe_name).stem or "sample").strip()
    # \w 包含 Unicode 字母数字 + 下划线;保留中文 + Latin + 数字 + 空格/标点 → 转 _
    vid = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", vid)
    vid = vid.strip("_") or "sample"
    if not vid:
        raise HTTPException(400, "voice_id required")

    # 全部转 wav 存盘(用户要求 7/9)—— 统一格式,后续 TTS/特征不依赖第三方 codec
    VOICE_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = VOICE_SAMPLES_DIR / f"{vid}.tmp{ext}"
    wav_path = VOICE_SAMPLES_DIR / f"{vid}.wav"
    tmp_path.write_bytes(raw)
    convert_info = {}
    try:
        from audio_features import convert_to_wav
        convert_info = convert_to_wav(str(tmp_path), str(wav_path))
        tmp_path.unlink(missing_ok=True)  # 删临时原文件,只留 wav
    except FileNotFoundError as e:
        if tmp_path.exists(): tmp_path.unlink()
        raise HTTPException(400, f"file disappeared: {e}")
    except Exception as e:
        # 转 wav 失败 —— 把原文件留作 fallback(避免数据丢失)
        if tmp_path.exists():
            tmp_path.rename(wav_path.with_suffix(ext))
        print(f"[tts-sample] convert_to_wav failed, kept original: {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)
        convert_info = {"error": f"{type(e).__name__}: {str(e)[:200]}"}

    # 特征提取(始终基于 wav)
    features = {"duration": 0, "f0_mean": 0, "speech_rate": 0, "rms": 0}
    try:
        from audio_features import extract_features
        raw_feats = extract_features(str(wav_path))
        features = {
            "duration": raw_feats.get("duration", 0),
            "f0_mean": raw_feats.get("f0_mean", 0),
            "speech_rate": raw_feats.get("speech_rate", 0),
            "rms": raw_feats.get("rms", 0),
            "sample_rate": raw_feats.get("sample_rate", 0),
        }
    except FileNotFoundError as e:
        print(f"[tts-sample] file not found: {e}", file=sys.stderr, flush=True)
        features["error"] = str(e)
    except ValueError as e:
        print(f"[tts-sample] extract failed: {e}", file=sys.stderr, flush=True)
        features["warning"] = str(e)
    except Exception as e:
        print(f"[tts-sample] feature extract error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        features["warning"] = f"特征提取失败: {type(e).__name__}: {str(e)[:100]}"

    # ASR: 根据 settings 选择引擎
    settings = _load_settings()
    asr_engine = (settings.get("asr_engine") or "faster-whisper").strip().lower()

    transcript = ""
    transcript_lang = ""
    transcript_warning = None

    if asr_engine == "bailian":
        try:
            transcript, transcript_lang = await _bailian_asr(raw, filename=safe_name)
            if not transcript:
                transcript_warning = "百炼 ASR 返回空结果"
            else:
                print(f"[tts-sample] Bailian ASR transcript ({len(transcript)} chars): {transcript[:80]}", file=sys.stderr, flush=True)
        except RuntimeError as e:
            transcript_warning = f"百炼 ASR: {e}"
            print(f"[tts-sample] {transcript_warning}", file=sys.stderr, flush=True)
        except Exception as e:
            transcript_warning = f"百炼 ASR 失败: {type(e).__name__}: {e}"
            print(f"[tts-sample] {transcript_warning}", file=sys.stderr, flush=True)
    else:
        # 默认: faster-whisper 本地 ASR
        try:
            from faster_whisper import WhisperModel
            import threading as _thr
            _whisper_state = {"model": None, "lock": _thr.Lock()}

            def _ensure_model():
                with _whisper_state["lock"]:
                    if _whisper_state["model"] is None:
                        print(f"[tts-sample] loading whisper base model...", file=sys.stderr, flush=True)
                        _whisper_state["model"] = WhisperModel("base", device="cpu", compute_type="int8")
                    return _whisper_state["model"]

            def _do_asr(path_str):
                try:
                    m = _ensure_model()
                    segs, info = m.transcribe(path_str, language="zh", beam_size=5)
                    return "".join(s.text for s in segs).strip(), info.language
                except Exception as e:
                    return None, str(e)

            loop = asyncio.get_event_loop()
            transcript, transcript_lang = await loop.run_in_executor(None, _do_asr, str(wav_path))
            if transcript is None:
                transcript_warning = f"ASR failed: {transcript_lang}"
                transcript = ""
            else:
                print(f"[tts-sample] ASR transcript ({len(transcript)} chars): {transcript[:80]}", file=sys.stderr, flush=True)
        except ImportError:
            transcript_warning = "faster-whisper 未安装,跳过 ASR"
            print(f"[tts-sample] {transcript_warning}", file=sys.stderr, flush=True)
        except Exception as e:
            transcript_warning = f"ASR init failed: {type(e).__name__}: {e}"
            print(f"[tts-sample] {transcript_warning}", file=sys.stderr, flush=True)
    # 元数据
    idx = _load_samples_index()
    idx[vid] = {
        "voice_id": vid,
        "display_name": display_name or vid,
        "filename": safe_name,
        "path": str(wav_path),
        "format": ".wav",  # 永远 wav(统一格式)
        "src_format": ext,
        "size": wav_path.stat().st_size if wav_path.exists() else len(raw),
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "features": features,
        "convert": convert_info,
        "transcript": transcript,  # ASR 出来的样本文字(Fish Audio reference 用)
        "transcript_lang": transcript_lang,
        "transcript_warning": transcript_warning,
    }
    _save_samples_index(idx)

    # CosyVoice Voice Enrollment：用用户的百炼 API key 注册音色
    cosy_key = (settings.get("cosyvoice_api_key") or "").strip()
    enrollment_result = None
    if cosy_key and wav_path.exists():
        try:
            import dashscope
            dashscope.api_key = cosy_key
            print(f"[tts-sample] voice '{vid}' ready for CosyVoice VC mode", flush=True)
            enrollment_result = {"registered": True, "voice_id": vid}
        except ImportError:
            print(f"[tts-sample] dashscope not installed, skip enrollment", flush=True)
        except Exception as e:
            enrollment_result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"[tts-sample] voice enrollment failed: {e}", flush=True)
    if enrollment_result:
        idx[vid]["cosyvoice_enrollment"] = enrollment_result
        _save_samples_index(idx)

    return {
        "voice_id": vid,
        "filename": safe_name,
        "format": ".wav",
        "src_format": ext,
        "size": wav_path.stat().st_size if wav_path.exists() else 0,
        "features": features,
        "convert": convert_info,
        "transcript": transcript,
        "transcript_warning": transcript_warning,
    }


@app.post("/api/tts/samples/{voice_id}/retranscribe")
async def retranscribe_voice_sample(voice_id: str):
    """重跑 ASR(样本没 transcript 时用)"""
    idx = _load_samples_index()
    info = idx.get(voice_id)
    if not info:
        raise HTTPException(404, f"voice_id not found: {voice_id}")
    path = Path(info.get("path", ""))
    if not path.exists():
        raise HTTPException(404, f"file not found: {path}")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(500, "faster-whisper 未安装")

    def _do():
        m = WhisperModel("base", device="cpu", compute_type="int8")
        segs, info = m.transcribe(str(path), language="zh", beam_size=5)
        return "".join(s.text for s in segs).strip(), info.language

    loop = asyncio.get_event_loop()
    transcript, lang = await loop.run_in_executor(None, _do)
    info["transcript"] = transcript
    info["transcript_lang"] = lang
    info["transcript_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    info.pop("transcript_warning", None)
    _save_samples_index(idx)
    return {"voice_id": voice_id, "transcript": transcript, "transcript_lang": lang}


@app.get("/api/tts/cache/stats")
def tts_cache_stats():
    """TTS 缓存统计:文件数 + 占用空间."""
    return _tts_cache_stats()


@app.delete("/api/tts/cache")
def tts_cache_clear():
    """清空 TTS 缓存(mp3 + json metadata)."""
    import shutil
    deleted = 0
    if TTS_CACHE_DIR.exists():
        for p in TTS_CACHE_DIR.glob("*"):
            try:
                if p.is_file() or p.is_symlink():
                    p.unlink()
                    deleted += 1
            except Exception as e:
                print(f"[tts-cache] delete failed {p}: {e}", file=sys.stderr, flush=True)
    return {"deleted": deleted, "dir": str(TTS_CACHE_DIR)}


@app.delete("/api/tts/samples/{voice_id}")
def delete_voice_sample(voice_id: str):
    """删除声音样本."""
    idx = _load_samples_index()
    info = idx.pop(voice_id, None)
    if info is None:
        raise HTTPException(404, f"voice_id not found: {voice_id}")
    path = Path(info.get("path", ""))
    if path.exists():
        try:
            path.unlink()
        except Exception as e:
            print(f"[tts-sample] delete file failed: {e}", file=sys.stderr, flush=True)
    _save_samples_index(idx)
    return {"ok": True, "voice_id": voice_id}


@app.post("/api/tts")
async def tts_endpoint(req: TTSRequest):
    """文字转语音,返回 mp3.

    引擎选择(按优先级):
    A) req.engine(请求级覆盖)
    B) settings.tts_engine
    C) "edge"(默认)

    缓存:
    - 同样的 (text, voice, voice_id, rate, pitch, volume, engine) → 直接返本地 mp3

    edge 引擎:
    - 只传 voice → edge-tts 默认音色
    - 传 voice + voice_id → 用样本特征自动调 SSML(风格模拟,免费)
    """
    import traceback as _tb
    try:
        return await _tts_endpoint_inner(req)
    except HTTPException:
        raise
    except Exception as e:
        _tb.print_exc()
        raise HTTPException(500, f"TTS 内部错误: {type(e).__name__}: {e}")


async def _tts_endpoint_inner(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text is empty")
    if len(text) > 2000:
        raise HTTPException(400, "text too long (max 2000 chars)")

    settings = _load_settings()
    engine = (req.engine or settings.get("tts_engine") or "edge").lower()

    # 提取语气指令 + 纯净朗读文本
    tts_text, instruction = _tts_preprocess(text)

    # ---- 缓存命中检查(任何引擎都查) ----
    cache_key = _tts_cache_key(
        engine, tts_text, req.voice, req.voice_id, req.rate, req.pitch, req.volume, instruction,
    )
    hit = _tts_cache_get(cache_key)
    if hit:
        audio, meta = hit
        print(f"[tts-cache] HIT {cache_key[:8]} (text='{text[:30]}')", file=sys.stderr, flush=True)
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'inline; filename="tts.mp3"',
                "Cache-Control": "no-cache",
                "X-Tts-Engine": meta.get("engine", engine),
                "X-Tts-Voice": meta.get("voice", req.voice or ""),
                "X-Tts-Cache": "hit",
                "X-Tts-Cache-Key": cache_key[:12],
            },
        )

    # ---- 缓存 miss:实际合成 ----
    if engine == "cosyvoice":
        resp = await _tts_cosyvoice_engine(tts_text, instruction, req, settings)
    else:
        resp = await _tts_edge_engine(tts_text, req, settings)

    # ---- 存缓存(仅 200 + 非空 mp3) ----
    if resp.status_code == 200 and resp.body:

        actual_engine = resp.headers.get("X-Tts-Engine", engine) or engine
        meta = {
            "engine": actual_engine,
            "voice": resp.headers.get("X-Tts-Voice", req.voice or ""),
            "voice_id": req.voice_id or "",
            "text": text,
            "rate": req.rate,
            "pitch": req.pitch,
            "volume": req.volume,
            "size": len(resp.body),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _tts_cache_put(cache_key, resp.body, meta)
        # 加 header 标识 miss
        new_headers = {
            **dict(resp.headers),
            "X-Tts-Cache": "miss",
            "X-Tts-Cache-Key": cache_key[:12],
        }
        return Response(
            content=resp.body,
            media_type=resp.media_type,
            status_code=resp.status_code,
            headers=new_headers,
        )
    return resp


def _ascii_safe(s: str, max_len: int = 200) -> str:
    """把任意字符串转成适合 HTTP header 的 ASCII(其余字符用 ? 替换)."""
    return (
        s.encode("ascii", errors="replace")
        .decode("ascii")[:max_len]
        .replace("\n", " ")
        .replace("\r", " ")
    )


async def _tts_edge_engine(text: str, req: TTSRequest, settings: dict) -> Response:
    """edge-tts + 风格模拟(完全免费)."""
    if not _EDGE_TTS_AVAILABLE:
        raise HTTPException(503, "edge-tts 未安装，请执行 pip install edge-tts")
    rate = req.rate
    pitch = req.pitch
    volume = req.volume
    style_source = None

    voice_id = req.voice_id or settings.get("tts_voice_id") or None
    feats = None
    if voice_id:
        idx = _load_samples_index()
        info = idx.get(voice_id)
        if info:
            feats = info.get("features", {}) or {}
            try:
                from audio_features import map_to_ssml
                ssml_params = map_to_ssml(feats)
                if rate == "+0%":
                    rate = ssml_params["rate"]
                if pitch == "+0Hz":
                    pitch = ssml_params["pitch"]
                if volume == "+0%":
                    volume = ssml_params["volume"]
                style_source = {
                    "voice_id": voice_id,
                    "features": feats,
                    "applied": {"rate": rate, "pitch": pitch, "volume": volume},
                }
            except Exception as e:
                print(f"[tts-edge] map_to_ssml failed: {e}", file=sys.stderr, flush=True)

    # 根据 f0 自动选男/女声(仅当用户没显式指定 voice 时)
    # 约定:req.voice 为 None 或空字符串 = 让后端选;非空 = 用户显式指定,必须尊重
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
    voice = req.voice
    if not voice and feats:
        f0 = feats.get("f0_mean", 0.0) or 0.0
        if f0 > 0:
            # f0 < 150Hz 男声(80-150 低沉男/普通男),150-180 普通男,180-220 女声,> 220 高亢女
            if f0 < 180:
                # 男声:青年用云希,新闻/低沉用云扬
                voice = "zh-CN-YunxiNeural" if f0 > 130 else "zh-CN-YunyangNeural"
            else:
                # 女声:温柔用晓晓,年轻用晓伊
                voice = "zh-CN-XiaoxiaoNeural" if f0 < 220 else "zh-CN-XiaoyiNeural"
            if style_source:
                style_source["auto_voice"] = {"f0": f0, "selected": voice}
            print(f"[tts-edge] auto-voice by f0={f0}: {voice}", file=sys.stderr, flush=True)
    if not voice:
        voice = DEFAULT_VOICE  # fallback(无 features 或 f0=0 时用女声)

    try:
        audio = await _synthesize(text, voice, rate, pitch, volume)
    except Exception as e:
        raise HTTPException(500, f"edge-tts failed: {e}")

    if not audio:
        raise HTTPException(500, "edge-tts returned empty audio")

    headers = {
        "Content-Disposition": f'inline; filename="tts.mp3"',
        "Cache-Control": "no-cache",
        "X-Tts-Engine": "edge",
        "X-Tts-Voice": voice,
    }
    if style_source:
        headers["X-Style-Source"] = style_source["voice_id"]

    return Response(content=audio, media_type="audio/mpeg", headers=headers)


async def _tts_cosyvoice_engine(text: str, instruction: str, req: TTSRequest, settings: dict) -> Response:
    """调用阿里云百炼 CosyVoice（dashscope SDK，WebSocket 协议）合成语音。

    支持指令控制：括号内的语气描写（如"停顿片刻""语气温和"）
    作为 instruction 参数传给 CosyVoice，让 TTS 按指定语气朗读。
    """
    cfg = _get_tts_config(settings)
    if not cfg["api_key"]:
        raise HTTPException(400, "百炼 API key 未配置，请在设置页填写")

    model = cfg["model"]
    voice = req.voice or cfg["voice"]

    def _do_synthesis():
        import dashscope
        dashscope.api_key = cfg["api_key"]
        from dashscope.audio.tts_v2 import SpeechSynthesizer

        def _try(voice_name, instr):
            k = dict(model=model, voice=voice_name)
            if instr:
                k["instruction"] = instr
            s = SpeechSynthesizer(**k)
            a = s.call(text)
            if a and len(a) >= 100:
                return a
            return None

        audio = _try(voice, instruction)
        if not audio and instruction:
            # 系统音色不支持指令，降级重试
            print(f"[cosyvoice] instruction failed, retrying without instruction", flush=True)
            audio = _try(voice, "")
        if not audio:
            # 音色无效，用默认音色
            default_voice = BUILTIN_TTS_PROVIDERS.get("cosyvoice", {}).get("default_voice", "longanyang")
            print(f"[cosyvoice] voice '{voice}' failed, falling back to '{default_voice}'", flush=True)
            audio = _try(default_voice, "")
        return audio

    loop = asyncio.get_event_loop()
    try:
        audio = await loop.run_in_executor(None, _do_synthesis)
    except ImportError as e:
        raise HTTPException(500, f"dashscope SDK 未安装: {e}（执行 pip install dashscope）")
    except Exception as e:
        err = str(e)
        if "418" in err:
            err += "。请先在阿里云百炼平台开通 CosyVoice 服务（模型广场 → cosyvoice → 开通）"
        raise HTTPException(502, f"CosyVoice 合成失败: {err}")

    if not audio:
        raise HTTPException(500, "CosyVoice 返回空音频")

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="tts.mp3"',
            "Cache-Control": "no-cache",
            "X-Tts-Engine": "cosyvoice",
            "X-Tts-Voice": voice,
            "X-Tts-Text-Sha1": hashlib.sha1(text.encode()).hexdigest()[:8],
        },
    )


@app.get("/api/settings")
def get_user_settings():
    """返回当前用户设置(API key 遮住中间)."""
    s = _load_settings()
    provider = s.get("llm_provider", "deepseek")

    # 各 provider 的 key 状态
    provider_keys = {}
    for pid in BUILTIN_PROVIDERS:
        key_field = f"{pid.replace('-', '_')}_api_key"
        key = s.get(key_field, "")
        provider_keys[f"{pid}_api_key_set"] = bool(key)
        provider_keys[f"{pid}_api_key_masked"] = _mask_key(key)

    # 旧字段兼容(deepseek 也走新命名)
    if not provider_keys.get("deepseek_api_key_set"):
        old_key = s.get("deepseek_api_key", "")
        provider_keys["deepseek_api_key_set"] = bool(old_key)
        provider_keys["deepseek_api_key_masked"] = _mask_key(old_key)

    # TTS 各引擎 key 状态
    tts_provider_states = {}
    for pid, info in BUILTIN_TTS_PROVIDERS.items():
        if info.get("need_key"):
            key_field = f"{pid}_api_key"
            key = s.get(key_field, "")
            tts_provider_states[f"{pid}_api_key_set"] = bool(key)
            tts_provider_states[f"{pid}_api_key_masked"] = _mask_key(key)

    return {
        **provider_keys,

        "tts_engine": s.get("tts_engine", "edge"),
        "tts_voice_id": s.get("tts_voice_id", ""),
        "llm_model": s.get("llm_model", ""),
        "llm_base_url": s.get("llm_base_url", ""),
        "llm_provider": provider,
        "llm_api_key": "",  # 前端不显示实际 key
        "bailian_api_key_set": bool(s.get("bailian_api_key", "")),
        "bailian_api_key_masked": _mask_key(s.get("bailian_api_key", "")),
        "enable_bailian_ocr": s.get("enable_bailian_ocr", False),
        "asr_engine": s.get("asr_engine", "faster-whisper"),
        "providers": [
            {
                "id": pid,
                "name": info["name"],
                "description": info["description"],
                "default_model": info["default_model"],
                "base_url": info["base_url"],
            }
            for pid, info in BUILTIN_PROVIDERS.items()
        ],
        "tts_providers": [
            {
                "id": pid,
                "name": info["name"],
                "description": info["description"],
                "need_key": info.get("need_key", False),
                "default_model": info.get("default_model", ""),
                "default_voice": info.get("default_voice", ""),
                "base_url": info.get("base_url", ""),
            }
            for pid, info in BUILTIN_TTS_PROVIDERS.items()
        ],
        **tts_provider_states,
        "cosyvoice_base_url": s.get("cosyvoice_base_url", BUILTIN_TTS_PROVIDERS["cosyvoice"]["base_url"]),
        "cosyvoice_model": s.get("cosyvoice_model", BUILTIN_TTS_PROVIDERS["cosyvoice"]["default_model"]),
        "cosyvoice_voice": s.get("cosyvoice_voice", BUILTIN_TTS_PROVIDERS["cosyvoice"]["default_voice"]),
        "cosyvoice_vc_model": s.get("cosyvoice_vc_model", "qwen3-tts-vc-2026-01-22"),
    }


@app.put("/api/settings")
def update_user_settings(payload: dict):
    """更新用户设置.可清空字段(传空字符串 / null).

    可写字段:各 provider api_key, bailian_api_key, tts_engine,
    tts_voice_id, llm_model, llm_base_url, llm_provider, llm_api_key (custom 用)
    """
    s = _load_settings()
    # 所有可接受字段
    accepted = set()
    # provider api keys
    for pid in BUILTIN_PROVIDERS:
        accepted.add(f"{pid.replace('-', '_')}_api_key")
    # 旧兼容
    accepted.add("deepseek_api_key")
    accepted.update({
        "bailian_api_key", "enable_bailian_ocr", "asr_engine",
        "tts_engine", "tts_voice_id", "tts_voice",
        "llm_model", "llm_base_url", "llm_provider", "llm_api_key",
        "cosyvoice_api_key", "cosyvoice_base_url", "cosyvoice_model",
        "cosyvoice_voice", "cosyvoice_vc_model",
    })
    for k in accepted:
        if k in payload:
            v = payload[k]
            if v is None or (isinstance(v, str) and v.strip() == ""):
                s.pop(k, None)
            else:
                s[k] = v.strip() if isinstance(v, str) else v
    _save_settings(s)
    reset_llm_cache()
    reset_system_prompt_cache()
    return {"ok": True, "settings": get_user_settings()}
@app.post("/api/settings/test-provider")
async def test_provider_key(payload: dict = Body(default=None)):
    """Test provider connectivity.

    Payload may include {provider: "xxx"} to override current provider.
    """
    req_provider = (payload or {}).get("provider", "").strip()
    if req_provider:
        # 临时用指定 provider 测试(不从 settings 读,用内置默认值 + env)
        builtin = _get_builtin_provider(req_provider)
        if builtin:
            base = builtin.get("base_url", "")
            model = builtin.get("default_model", "")
        else:
            base = LLM_BASE_URL
            model = LLM_MODEL
        # key 从 settings 读对应字段
        s = _load_settings()
        key_field = f"{req_provider.replace('-', '_')}_api_key"
        key = (s.get(key_field) or "").strip()
        if not key:
            key = (s.get("deepseek_api_key") or "").strip()
        if not key:
            key = LLM_API_KEY
    else:
        cfg = _get_llm_config()
        base = cfg["base"]
        key = cfg["key"]
        model = cfg["model"]
        req_provider = cfg["provider"]

    if not key or not base:
        return {"ok": False, "error": f"provider={req_provider}: no key or base_url configured"}

    try:
        client = OpenAI(base_url=base, api_key=key)
        r = client.chat.completions.create(
            model=model or "gpt-3.5-turbo",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
        )
        return {
            "ok": True,
            "reply": (r.choices[0].message.content or "").strip()[:50],
            "model": model,
            "base": base,
            "provider": req_provider,
        }
    except Exception as e:
        err = str(e)[:300]
        # 友好提示:如果看起来不是 OpenAI 兼容格式
        if "not_found" in err.lower() or "invalid" in err.lower() or "unsupported" in err.lower():
            err += "(该 API 可能不是 OpenAI 兼容格式)"
        return {"ok": False, "error": err, "provider": req_provider}


# 保留旧接口兼容
@app.post("/api/settings/test-deepseek")
async def test_deepseek_key():
    """用 user key 测一下 DeepSeek 是否可用(拿一个 ping 响应)."""
    cfg = _get_llm_config()
    if not cfg["key"]:
        return {"ok": False, "error": "no key configured"}
    try:
        client = OpenAI(base_url=cfg["base"], api_key=cfg["key"])
        r = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
        )
        return {
            "ok": True,
            "reply": (r.choices[0].message.content or "").strip()[:50],
            "model": cfg["model"],
            "base": cfg["base"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}



@app.post("/api/settings/test-cosyvoice")
async def test_cosyvoice_key(payload: dict = Body(default=None)):
    """测试百炼 TTS（CosyVoice）API key 是否可用。"""
    s = _load_settings()
    key = (payload or {}).get("api_key", "") or s.get("cosyvoice_api_key") or ""
    model = (payload or {}).get("model", "") or s.get("cosyvoice_model") or BUILTIN_TTS_PROVIDERS["cosyvoice"]["default_model"]
    voice = (payload or {}).get("voice", "") or s.get("cosyvoice_voice") or BUILTIN_TTS_PROVIDERS["cosyvoice"]["default_voice"]

    if not key:
        return {"ok": False, "error": "百炼 API key 未配置"}

    try:
        import dashscope
        dashscope.api_key = key
        from dashscope.audio.tts_v2 import SpeechSynthesizer
        synth = SpeechSynthesizer(model=model, voice=voice)
        audio = synth.call("测试")
        if audio and len(audio) > 100:
            return {"ok": True, "model": model, "voice": voice}
        else:
            hints = []
            if not voice or voice == "longxiaochun":
                hints.append(f'音色 "{voice}" 可能不存在于模型 {model}。建议使用 "longanyang"（通用男声）或 "longxiaochun_v3"（温柔女声）')
            return {"ok": False, "error": f"TTS 返回空音频。{' '.join(hints)}"}
    except ImportError:
        return {"ok": False, "error": "请先安装 dashscope: pip install dashscope"}
    except Exception as e:
        err = str(e)
        if "418" in err:
            err += "。请在阿里云百炼平台开通 CosyVoice 服务（模型广场 → cosyvoice-v3-flash → 开通）"
        return {"ok": False, "error": f"{type(e).__name__}: {err[:200]}"}


@app.post("/api/sessions")
async def create_session(payload: dict = Body(default=None)):
    """创建新对话会话."""
    mm = get_memory_manager()
    title = (payload or {}).get("title", "")
    session = mm.create_session(title=title)
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "turn_count": 0,
    }


@app.get("/api/sessions")
def list_sessions():
    """列出所有会话,按更新时间倒序."""
    mm = get_memory_manager()
    sessions = mm.list_sessions(limit=100)
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "turn_count": s.turn_count,
                "summary": s.summary,
            }
            for s in sessions
        ]
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """获取会话详情(含完整对话历史)."""
    mm = get_memory_manager()
    session = mm.load_session(session_id)
    if not session:
        raise HTTPException(404, f"session not found: {session_id}")
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "turn_count": session.turn_count,
        "summary": session.summary,
        "turns": session.turns,
    }


@app.post("/api/sessions/{session_id}/rename")
async def rename_session(session_id: str, payload: dict = Body(...)):
    """重命名会话."""
    mm = get_memory_manager()
    session = mm.load_session(session_id)
    if not session:
        raise HTTPException(404, f"session not found: {session_id}")
    new_title = (payload or {}).get("title", "")
    if new_title:
        session.title = new_title
        session.save()
    return {"id": session.id, "title": session.title}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话."""
    mm = get_memory_manager()
    ok = mm.delete_session(session_id)
    if not ok:
        raise HTTPException(404, f"session not found: {session_id}")
    return {"ok": True, "deleted": session_id}


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str):
    """导出会话为纯文本格式。"""
    mm = get_memory_manager()
    session = mm.load_session(session_id)
    if not session:
        raise HTTPException(404, f"session not found: {session_id}")
    lines = [f"# {session.title}"]
    lines.append(f"# 创建: {session.created_at}  更新: {session.updated_at}")
    lines.append("")
    for turn in session.turns:
        role_label = "用户" if turn["role"] == "user" else "AI"
        lines.append(f"[{role_label}] {turn['content']}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), headers={
        "Content-Disposition": f'attachment; filename="{session.title or session.id}.txt"',
    })


# ---------- SPA fallback（serve dist/ 下的静态文件，支持 SPA 路由）----------
_spa_dir = ROOT_DIR / "frontend" / "dist"
if _spa_dir.exists() and (_spa_dir / "index.html").exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(_spa_dir / "assets")), name="spa_assets")

    _spa_html = (_spa_dir / "index.html").read_text(encoding="utf-8")
    @app.get("/favicon.svg", include_in_schema=False)
    async def _favicon():
        from fastapi.responses import FileResponse
        return FileResponse(str(_spa_dir / "favicon.svg"))
    @app.get("/icons.svg", include_in_schema=False)
    async def _icons():
        from fastapi.responses import FileResponse
        return FileResponse(str(_spa_dir / "icons.svg"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_catch_all(full_path: str):
        from fastapi.responses import HTMLResponse
        from fastapi.responses import FileResponse
        file_path = _spa_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return HTMLResponse(_spa_html)


# ---------- main ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088, log_level="info")
