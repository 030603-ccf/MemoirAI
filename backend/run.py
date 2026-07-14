"""
run.py - MemoirAI 后端入口
"""
import os
import sys
import io as _io
import time
import socket
import threading
import webbrowser
from pathlib import Path

# 强制 UTF-8 输出（修复 Windows 控制台中文乱码）
for _s in (sys.stdout, sys.stderr):
    if _s and hasattr(_s, "buffer"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
try:
    os.system("chcp 65001 > nul 2>&1")
except Exception:
    pass

# ---------- 路径定位（dev vs exe） ----------
def is_frozen():
    """PyInstaller 打包后会设置 sys._MEIPASS"""
    return getattr(sys, "frozen", False)


if is_frozen():
    APP_DIR = Path(sys.executable).resolve().parent
    DATA_DIR = APP_DIR / "data"
    MEIPASS = Path(getattr(sys, "_MEIPASS", str(APP_DIR)))
    STATIC_DIR = MEIPASS / "static"
else:
    # dev 模式
    APP_DIR = Path(__file__).resolve().parent
    PROJECT_DIR = APP_DIR
    STATIC_DIR = PROJECT_DIR.parent / "frontend" / "dist"
    DATA_DIR = PROJECT_DIR / "data"
    # 一次性迁移：如果 D:\project\data 不存在但 qwen-chat-test\data 存在 → 复制过去
    legacy_data = APP_DIR / "data"
    if not DATA_DIR.exists() and legacy_data.exists():
        import shutil
        try:
            shutil.copytree(legacy_data, DATA_DIR)
            print(f"[run_app] 一次性数据迁移: {legacy_data} → {DATA_DIR}", flush=True)
        except Exception as e:
            print(f"[run_app] 数据迁移失败: {e}", flush=True)

# 本地 PaddleOCR 模型路径（dev / frozen 都生效）
_models = Path(sys.executable).parent / "models" / "paddleocr" if is_frozen() else APP_DIR / "models" / "paddleocr"
if _models.exists():
    os.environ["PADDLEOCR_HOME"] = str(_models)
    print(f"  [OCR] models: {_models}", flush=True)

DATA_DIR.mkdir(parents=True, exist_ok=True)

# 日志目录
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 子目录迁移（rag_index 等旧位置的数据可能只在 legacy_data 下）
# 例：dev 模式重建过索引，但 index 存在 qwen-chat-test/data/rag_index/
# 不会因为顶层 DATA_DIR 已存在而被上面 copytree 整体迁移走
if not is_frozen() and legacy_data.exists():
    import shutil
    for sub in ("rag_index", "voice_samples", "screenshots"):
        src_sub = legacy_data / sub
        dst_sub = DATA_DIR / sub
        if src_sub.is_dir() and src_sub.exists():
            if not dst_sub.exists() or not any(dst_sub.iterdir()):
                try:
                    shutil.copytree(src_sub, dst_sub, dirs_exist_ok=True)
                    print(f"[run_app] 子目录迁移: {src_sub} → {dst_sub}", flush=True)
                except Exception as e:
                    print(f"[run_app] 子目录迁移失败 {sub}: {e}", flush=True)

# 把 APP_DIR 注入到环境变量，让 backend 模块能找到 data 目录
os.environ["MEMORIAL_DATA_DIR"] = str(DATA_DIR)
os.environ["MEMORIAL_STATIC_DIR"] = str(STATIC_DIR)

# ---------- banner ----------
BANNER = r"""
   __  ___                  __  __                __   __  ___           __
  /  |/  /___ _____  ____ _/ / / /  ___  ___ ____/ /  /  |/  /__ _____  / /
 / /|_/ / _ `/ _ \/ __/ _ `/ /_/ _ \/ _ \/ _ `/ _  /  / /|_/ / _ `/ _ \/ _ \
/_/  /_/\_,_/_//_/\__/\_,_/____|_.__/ .__/\_,_/\_,_/  /_/  /_/\_,_/_//_/_//_/
                                    /_/
                       MemoirAI · 一键启动
"""


def find_free_port(preferred: int = 8088, max_tries: int = 20) -> int:
    """找一个空闲端口（8088 被占就用 8089, 8090...）"""
    for offset in range(max_tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"无法找到空闲端口（{preferred}-{preferred+max_tries-1}）")


def open_browser_delayed(url: str, delay: float = 2.0):
    """等 server 起来后再开浏览器"""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[browser] failed to open: {e}")
    threading.Thread(target=_open, daemon=True).start()


def main():
    print(BANNER)
    print(f"  data  dir: {DATA_DIR}")

    # Early-init: 预热 sentence-transformers + bge 模型
    # 解决 frozen exe 下 shm.dll / torch_python.dll 加载顺序冲突：
    # MemorialChat 启动后 OCR 走 paddleocr 链，paddle 的 paddle.* DLL 占用了一些全局状态，
    # 之后再 import torch 时 _load_dll_libraries 会触发 shm.dll 第二次加载，
    # 报错 [WinError 127] 找不到指定的程序。
    # 修法：启动时先 import torch + sentence_transformers + 加载 bge 模型一次，
    # 后面 OCR 跑 paddleocr 触发 paddle 的 import 也不会影响（torch DLL 已经在内存里）。
    if is_frozen():
        print("  [init] 预热 sentence-transformers + bge 模型（frozen exe 需要）...")
        try:
            import torch  # noqa
            from sentence_transformers import SentenceTransformer  # noqa
            # 不在这里 load model（model load 慢 ~10s，懒加载到 rebuild 时再做）
            print("  [OK] sentence-transformers 预热完成")
        except Exception as e:
            print(f"  [WARN] sentence-transformers 预热失败: {e}")
            print("         → OCR 完自动建索引会失败，需要手动处理")
    print(f"  static dir: {STATIC_DIR}")
    print()

    # 把 DATA_DIR 注入到 backend 模块的 sys.path
    if not is_frozen():
        project_dir = APP_DIR.parent
        backend_dir = APP_DIR / "routers"
        core_dir = APP_DIR / "core"
        # 把 routers 目录加进 sys.path（让 import api 能找到）
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        # 把 core 目录加进 sys.path（让 from audio_features / from regenerate_profile 能找到）
        if str(core_dir) not in sys.path:
            sys.path.insert(0, str(core_dir))
    else:
        # exe 模式：所有东西都在 APP_DIR（PyInstaller 把它们打进 exe）
        core_dir = APP_DIR  # core 在 APP_DIR 或 _MEIPASS
        # backend/ 子目录里的 api.py 跟 run_app.py 一起被打包
        if str(APP_DIR) not in sys.path:
            sys.path.insert(0, str(APP_DIR))

    # 强制 backend 模块使用我们的路径
    from routers import api as backend_api
    # 重写 backend_api 里的关键路径
    backend_api.DATA_DIR = DATA_DIR
    backend_api.SCREENSHOTS_DIR = DATA_DIR / "screenshots"
    backend_api.CHAT_TXT = DATA_DIR / "chat_extracted.txt"
    backend_api.PROFILE_JSON = DATA_DIR / "memorial_profile.json"
    backend_api.INDEX_DIR = DATA_DIR / "rag_index"
    backend_api.SETTINGS_JSON = DATA_DIR / "user_settings.json"
    backend_api.VOICE_SAMPLES_DIR = DATA_DIR / "voice_samples"
    backend_api.SAMPLES_JSON = DATA_DIR / "voice_samples" / "samples.json"

    # 创建子目录
    for sub in (backend_api.SCREENSHOTS_DIR, backend_api.INDEX_DIR, backend_api.VOICE_SAMPLES_DIR):
        sub.mkdir(parents=True, exist_ok=True)

    # 挂载静态文件（前端 dist）—— 把整个前端 dist 挂到 /，让浏览器直接访问 /
    from fastapi.staticfiles import StaticFiles
    # 先删除 backend/api.py 里的 root 路由（避免和 static mount 冲突）
    backend_api.app.router.routes = [
        r for r in backend_api.app.router.routes
        if not (getattr(r, "path", "") == "/" and getattr(r, "methods", set()) == {"GET"})
    ]
    if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
        # 直接挂到 /，这样浏览器访问 / 时直接拿到 index.html，
        # 资源路径 /assets/xxx.js 也都正常
        backend_api.app.mount(
            "/",
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="frontend",
        )
        # 健康检查挪到 /health（不抢 /）
        @backend_api.app.get("/health", include_in_schema=False)
        def _health():
            return {"name": "Memorial Chat API", "version": "0.1.0", "ok": True}
        print(f"  [OK] 前端已挂载：http://127.0.0.1:{{port}}/")
    else:
        print(f"  [WARN] 静态目录为空（{STATIC_DIR}），请确保前端 build 产物存在")

    # 找空闲端口
    port = int(os.environ.get("PORT", "8088"))
    port = find_free_port(port)
    url = f"http://127.0.0.1:{port}"

    print(f"  [OK] 数据目录：{DATA_DIR}")
    print(f"  [OK] 服务地址：{url}")
    print()
    print("  按 Ctrl+C 关闭服务")
    print()

    # 自动开浏览器（dev 模式也可以通过环境变量关闭）
    if not os.environ.get("NO_BROWSER"):
        open_browser_delayed(url, delay=1.5)

    # 启动时自动起 in-process OCR service（一体化版本：主 exe 自带 PaddleOCR）
    # - 后台线程 daemon：跑 uvicorn on 8089（ocr_service.app）
    # - 后台线程 daemon：调 ocr_service._load_ocr() 懒加载 PaddleOCR
    # - run_ocr() 通过 HTTP 调 127.0.0.1:8089/ocr（与双 exe 模式走同一接口）
    if getattr(sys, "frozen", False):
        try:
            from core import ocr_service as _ocr_svc
            import threading as _thr

            ocr_port = find_free_port(8089, max_tries=3)
            if ocr_port != 8089:
                print(f"  [WARN] Port 8089 已被占用，跳过 OCR 服务", flush=True)
            else:
                def _ocr_bg_load():
                    try:
                        _ocr_svc._load_ocr()
                    except Exception as e:
                        print(f"  [WARN] OCR model load failed: {e}", flush=True)
                _thr.Thread(target=_ocr_bg_load, daemon=True).start()

                def _ocr_run():
                    try:
                        _ocr_svc.run_server(port=8089, host="127.0.0.1")
                    except Exception as e:
                        print(f"  [WARN] OCR service crashed: {e}", flush=True)
                _thr.Thread(target=_ocr_run, daemon=True).start()
                print("  [OK] 内置 OCR service 已启动（http://127.0.0.1:8089）", flush=True)
        except Exception as e:
            print(f"  [WARN] OCR service 启动失败: {e}")

    # 启动 uvicorn
    import uvicorn
    uvicorn.run(
        backend_api.app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[bye] 服务已关闭")
    except Exception as e:
        print(f"\n[fatal] {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        input("\n按回车键退出...")