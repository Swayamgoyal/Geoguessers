"""Run the tile server:  python -m server [--host 127.0.0.1] [--port 8765]

One process, one worker: every request must share the same caches and scheduler.
"""
import argparse

import uvicorn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    uvicorn.run("server.app:app", host=a.host, port=a.port, workers=1, log_level="warning")


if __name__ == "__main__":
    main()
