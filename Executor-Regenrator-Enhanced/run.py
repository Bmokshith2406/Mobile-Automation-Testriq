#!/usr/bin/env python3
"""
Playwright Step Repair Engine - Startup Wrapper

Launches the FastAPI application with customized logging modes for developer readability.

Usage:
  python run.py --mode pretty
  python run.py --mode console
  python run.py --mode json

Recommended for actual executor runs:
  python run.py --no-reload
"""

import os
import sys
import argparse

# Check if uvicorn is installed in the current Python environment
try:
    import uvicorn
except ImportError:
    print("❌ Error: 'uvicorn' is not installed in the active Python environment.")
    print("👉 Did you forget to activate the virtual environment?")
    print("   Run: .\\venv\\Scripts\\activate")
    print("   Then try running the command again.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Start the Playwright Step Repair Engine with custom log formatting."
    )

    parser.add_argument(
        "--mode",
        choices=["pretty", "console", "json"],
        default="pretty",
        help="Log formatting mode: 'pretty', 'console', or 'json'",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="The interface address to bind the server to (default: 127.0.0.1 for local compatibility)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="The port to run the web server on",
    )

    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reloading when source files change.",
    )

    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging level",
    )

    args = parser.parse_args()

    os.environ["LOG_FORMAT_MODE"] = args.mode.upper()
    os.environ["LOG_LEVEL"] = args.log_level.upper()

    green = "\033[32m"
    cyan = "\033[36m"
    yellow = "\033[33m"
    bold = "\033[1m"
    reset = "\033[0m"

    reload_enabled = not args.no_reload

    print("=" * 60)
    print(f"🚀 {bold}{green}Playwright Step Repair Engine{reset}")
    print(f"📡 Address: {cyan}http://{args.host}:{args.port}{reset}")
    print(f"🎨 Log Formatting Mode: {bold}{args.mode.upper()}{reset}")
    print(f"🔁 Auto Reload: {bold}{'ON' if reload_enabled else 'OFF'}{reset}")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.join(current_dir, "app")

    if reload_enabled:
        print(
            f"🛡️ Reload Excludes: {yellow}"
            "runs/, successful_runs/, artifacts/, temp outputs"
            f"{reset}"
        )

    print("=" * 60)
    print()

    reload_excludes = [
        "runs/*",
        "runs/**",
        "successful_runs/*",
        "successful_runs/**",
        "artifacts/*",
        "artifacts/**",
        "**/artifacts/*",
        "**/artifacts/**",
        "**/failures/*",
        "**/failures/**",
        "**/success/*",
        "**/success/**",
        "**/_video_tmp/*",
        "**/_video_tmp/**",
        "**/*.zip",
        "**/*.webm",
        "**/*.png",
        "**/*.jpg",
        "**/*.jpeg",
        "**/*.json",
        "**/*.txt",
        "**/*.html",
        "**/*.log",
        "**/*.py.bak.*",
        "**/__pycache__/*",
        "**/__pycache__/**",
    ]

    try:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=reload_enabled,
            reload_dirs=[app_dir] if reload_enabled else None,
            reload_excludes=reload_excludes if reload_enabled else None,
            log_level=args.log_level.lower(),
        )
    except KeyboardInterrupt:
        print(f"\n👋 {bold}Shutting down gracefully...{reset}")


if __name__ == "__main__":
    main()