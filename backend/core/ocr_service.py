# -*- coding: utf-8 -*-
"""
ocr_service.py
==============
MemorialOCR.exe 的入口：起一个 HTTP service，接收聊天截图、跑 PaddleOCR、
写到 chat_extracted.txt。

设计：
- 单实例（PID 写到 data/_ocr_pid）
- 启动慢（PaddleOCR 模型 30-60s 第一次）→ /health 端点轮询 ready
- POST /ocr 接受 multipart upload images → 写到 chat_extracted.txt 追加
- GET /health → {ready: bool, ...}
- GET /quit → 主动退出（方便主 exe spawn 后停掉）

启动后默认端口 8089，文件目录在 DATA_DIR (默认 D:\project\data)。
"""
import io
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# ---------- 路径定位（dev vs exe） ----------
def is_frozen():
    return getattr(sys, "frozen", False)

if is_frozen():
    APP_DIR = Path(sys.executable).resolve().parent
    DATA_DIR = APP_DIR / "data"
else:
    # dev 模式：跟主 exe 保持一致
    APP_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = APP_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# 默认端口
DEFAULT_PORT = int(os.environ.get("OCR_SERVICE_PORT", 8089))
# 单实例锁
PID_FILE = DATA_DIR / "_ocr_pid"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
CHAT_TXT = DATA_DIR / "chat_extracted.txt"

# ---------- 启动横幅 ----------
BANNER = r"""
   __  ___                  __  __                __   __  ___           __
  /  |/  /___ _____  ____ _/ / / /  ___  ___ ____/ /  /  |/  /__ _____  / /
 / /|_/ / _ `/ _ \/ __/ _ `/ /_/ _ \/ _ \/ _ `/ _  /  / /|_/ / _ `/ _ \/ _ \
/_/  /_/\_,_/_//_/\__/\_,_/____|_.__/ .__/\_,_/\_,_/  /_/  /_/\_,_/_//_/_//_/
                                    /_/
                       Memorial OCR · 独立 OCR 服务
"""

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ocr-service")


# ---------- 单实例锁 ----------
def acquire_lock() -> bool:
    """写 PID 到 PID_FILE，进程退出时清理。如果已有别的进程 → 失败。"""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
        except Exception:
            old_pid = None
        if old_pid:
            import psutil  # type: ignore
            if psutil.pid_exists(old_pid):
                log.warning(f"另一个 OCR service 进程 {old_pid} 已在运行")
                return False
            else:
                log.info(f"stale PID file found (pid {old_pid}), removing")
        try:
            PID_FILE.unlink()
        except Exception:
            pass
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock():
    if PID_FILE.exists():
        try:
            txt = PID_FILE.read_text().strip()
            if txt == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass


# ---------- PaddleOCR 加载 ----------
_ocr_instance: Optional[object] = None
_ocr_lock = None
_ocr_ready = False
_ocr_load_error: Optional[str] = None


def _load_ocr():
    """懒加载 PaddleOCR（首次 ~30-60s 慢）。"""
    global _ocr_instance, _ocr_lock, _ocr_ready, _ocr_load_error
    if _ocr_lock is None:
        import threading
        _ocr_lock = threading.Lock()
    with _ocr_lock:
        if _ocr_instance is None:
            try:
                # frozen 模式下 Cython/Utility/ 模板可能缺失，从 models/ 补
                try:
                    import Cython as _cy
                    _cy_util = Path(_cy.__file__).resolve().parent / "Utility"
                    if not (_cy_util / "CppSupport.cpp").exists():
                        _models_util = Path(sys.executable).resolve().parent / "models" / "Cython" / "Utility"
                        if _models_util.exists():
                            import shutil
                            shutil.copytree(str(_models_util), str(_cy_util), dirs_exist_ok=True)
                            log.info(f"copied Cython/Utility from models/ ({len(list(_models_util.iterdir()))} files)")
                except Exception as _ce:
                    log.warning(f"Cython Utility copy failed (non-fatal): {_ce}")

                log.info("loading PaddleOCR (first run downloads models, ~30-60s)...")
                t0 = time.time()
                from paddleocr import PaddleOCR
                try:
                    _ocr_instance = PaddleOCR(use_textline_orientation=True, lang="ch")
                except TypeError:
                    _ocr_instance = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                _ocr_ready = True
                _ocr_load_error = None
                log.info(f"PaddleOCR ready in {time.time() - t0:.1f}s")
            except Exception as e:
                _ocr_ready = False
                _ocr_load_error = f"{type(e).__name__}: {e}"
                log.error(f"PaddleOCR load failed: {_ocr_load_error}")
                raise
    return _ocr_instance


# ---------- OCR 处理 ----------
def _ocr_images(image_paths: list) -> list:
    """调 PaddleOCR 处理每张图，返回 [{role, text, line_no, y, cx, ...}]。"""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from extract_chat_universal import process_image  # noqa: E402

    ocr = _ocr_instance  # 假设已加载
    all_msgs = []
    for i, p in enumerate(image_paths, 1):
        log.info(f"[{i}/{len(image_paths)}] {p.name}")
        items = process_image(
            ocr, p,
            threshold_ratio=0.5, center_band=0.1,
            crop_top_px=0, debug=False,
        )
        log.info(f"  -> {len(items)} chat lines")
        all_msgs.extend(items)
    return all_msgs


# ---------- HTTP server ----------
def run_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    """起 aiohttp / fastapi HTTP server。

    端点：
      GET  /health   → {ready, model_loaded, error?, port, pid, uptime_s}
      POST /ocr      → multipart upload, 处理 → 写 chat_extracted.txt → 返回 {messages, preview, count}
      GET  /quit     → 主动退出
    """
    try:
        from fastapi import FastAPI, File, UploadFile, HTTPException
        from fastapi.responses import JSONResponse
        import uvicorn
    except ImportError as e:
        log.error(f"fastapi/uvicorn not installed: {e}")
        sys.exit(1)

    app = FastAPI(title="Memorial OCR", version="1.0")
    start_t = time.time()

    @app.get("/")
    def root():
        return {
            "service": "MemoirAI OCR",
            "ready": _ocr_ready,
            "model_loaded": _ocr_instance is not None,
            "error": _ocr_load_error,
        }

    @app.get("/health")
    def health():
        return {
            "ready": _ocr_ready,
            "model_loaded": _ocr_instance is not None,
            "error": _ocr_load_error,
            "port": port,
            "pid": os.getpid(),
            "uptime_s": round(time.time() - start_t, 1),
            "data_dir": str(DATA_DIR),
        }

    @app.post("/ocr")
    async def ocr_endpoint(files: list[UploadFile] = File(...)):
        if not files:
            raise HTTPException(400, "no files uploaded")
        if not _ocr_ready:
            # 临时尝试懒加载（可能启动时还没 load）
            try:
                _load_ocr()
            except Exception as e:
                raise HTTPException(503, f"OCR not ready: {e}")

        # 保存到 screenshots/，调用 _ocr_images
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            ts = int(time.time() * 1000)
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in (f.filename or "upload"))
            dst = SCREENSHOTS_DIR / f"{ts}_{safe}"
            with dst.open("wb") as out:
                content = await f.read()
                out.write(content)
            saved.append(dst)

        # OCR（run in thread because PaddleOCR is blocking）
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            msgs = await loop.run_in_executor(None, _ocr_images, saved)
        except Exception as e:
            log.exception("OCR processing failed")
            raise HTTPException(500, f"ocr processing failed: {e}")

        # 写 chat_extracted.txt（追加）
        CHAT_TXT.parent.mkdir(parents=True, exist_ok=True)
        with CHAT_TXT.open("a", encoding="utf-8") as f:
            f.write(f"\n# --- OCR batch at {time.strftime('%Y-%m-%d %H:%M:%S')} ({len(saved)} imgs) ---\n")
            for m in msgs:
                role = "本人" if m["role"] == "self" else "对方"
                f.write(f"[{role}] {m['text']}\n")

        preview = "\n".join(
            f"[{'本人' if m['role'] == 'self' else '对方'}] {m['text']}"
            for m in msgs[:50]
        )
        log.info(f"OCR done: {len(msgs)} messages, written to {CHAT_TXT}")
        return {
            "message_count": len(msgs),
            "preview": preview,
            "saved_files": [str(p) for p in saved],
        }

    @app.get("/quit")
    def quit_endpoint():
        log.info("/quit received, shutting down")
        # 延迟退出，让 response 能回去
        import threading
        def _do():
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=_do, daemon=True).start()
        return {"ok": True, "bye": True}

    log.info(f"Memorial OCR listening on http://{host}:{port}")
    log.info(f"data dir: {DATA_DIR}")
    log.info(f"PID file: {PID_FILE}")
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


# ---------- 入口 ----------
def main():
    print(BANNER)
    if not acquire_lock():
        log.error(f"另一个实例在跑（PID file: {PID_FILE}）")
        sys.exit(2)

    # signal handler
    def _on_signal(*_):
        log.info("signal received, exiting")
        release_lock()
        os._exit(0)
    try:
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
    except Exception:
        pass  # Windows 不支持 SIGTERM 全部

    # 懒加载 OCR（后台线程，不阻塞 /health 立即可用）
    import threading
    def _bg_load():
        try:
            _load_ocr()
        except Exception:
            pass
    threading.Thread(target=_bg_load, daemon=True).start()

    port = DEFAULT_PORT
    try:
        run_server(port=port)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
