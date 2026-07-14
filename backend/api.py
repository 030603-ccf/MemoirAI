"""
api.py - Re-export for `uvicorn api:app` compatibility.
Usage: uvicorn api:app --host 0.0.0.0 --port 8088
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

from routers.api import app
