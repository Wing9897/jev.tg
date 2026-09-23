"""Run the FastAPI server."""

from __future__ import annotations

import argparse

import uvicorn

from server.paths import BIND_HOST, DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="JEV Telegram Filter API")
    parser.add_argument("--host", default=BIND_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("server.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
