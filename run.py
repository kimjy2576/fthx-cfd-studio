#!/usr/bin/env python
"""로컬 서버 실행:  python run.py  [--port 8020] [--host 127.0.0.1]"""
import argparse, sys, webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--reload", action="store_true", help="코드 수정 시 자동 재시작")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    import os
    if a.reload:
        os.environ["FTHX_RELOAD"] = "1"
    import uvicorn
    url = f"http://{a.host}:{a.port}"
    print(f"\n  FT-HX CFD Studio  →  {url}\n  (Ctrl+C 로 종료)\n")
    if not a.no_browser and not a.reload:
        try: webbrowser.open(url)
        except Exception: pass
    uvicorn.run("server.app:app", host=a.host, port=a.port, reload=a.reload)

if __name__ == "__main__":
    main()
