#!/usr/bin/env python3
"""
Better PESU Acad — Unified Desktop Application Entry Point.
Launches the native pywebview desktop application window by default,
or starts the internal Flask HTTP server directly if run with --server-only.
"""

import argparse
import logging
import sys

from backend.config import Config
from backend.app import create_app
from desktop.launcher import DesktopApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("betterpesu")


def main():
    parser = argparse.ArgumentParser(description="Better PESU Acad Desktop Application")
    parser.add_argument("--server-only", action="store_true", help="Run local HTTP server without native desktop window")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind server (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind server (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    config = Config()

    if args.server_only:
        logger.info("Starting Better PESU Acad in server-only mode on %s:%d", args.host, args.port)
        app = create_app(config)
        app.run(host=args.host, port=args.port, debug=args.debug)
    else:
        logger.info("Launching Better PESU Acad desktop application")
        desktop_app = DesktopApp(data_dir=config.data_dir)
        desktop_app.start(debug=args.debug)


if __name__ == "__main__":
    main()
