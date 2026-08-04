"""Rotate screens / serve config UI."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

import uvicorn

from pixelpixoo.config import load_config
from pixelpixoo.persist import configure_logging
from pixelpixoo.runtime import os_environ_preview, runtime

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PixelPixoo Pixoo 64 dashboard")
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to config.yaml (default: PIXELPIXOO_CONFIG or ./config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render each screen once then exit (no web UI)",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Write PNG previews to this directory instead of pushing to the Pixoo",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Disable the config web UI",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("PIXELPIXOO_WEB_HOST", "0.0.0.0"),
        help="Web UI bind host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PIXELPIXOO_WEB_PORT", "8080")),
        help="Web UI port",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args(argv)

    verbose = args.verbose or _env_flag("PIXELPIXOO_VERBOSE")
    configure_logging(verbose=verbose)

    if args.config:
        os.environ["PIXELPIXOO_CONFIG"] = str(args.config)

    preview = args.preview
    if preview is None and os_environ_preview():
        preview = Path(os_environ_preview())
    once = args.once or _env_flag("PIXELPIXOO_ONCE")
    no_web = args.no_web or _env_flag("PIXELPIXOO_NO_WEB")

    cfg = load_config()
    runtime.start(cfg, preview_dir=preview, once=once)

    def _stop(signum: int, _frame: object, *, hard_exit: bool) -> None:
        logger.info("Signal %s — stopping", signum)
        runtime.stop(timeout=5 if hard_exit else 10)
        if hard_exit:
            # uvicorn will exit via KeyboardInterrupt in main thread usually;
            # force process exit for SIGTERM in Docker
            os._exit(0)

    if once or no_web:
        stopped = False

        def _stop_loop(signum: int, _frame: object) -> None:
            nonlocal stopped
            _stop(signum, _frame, hard_exit=False)
            stopped = True

        signal.signal(signal.SIGINT, _stop_loop)
        signal.signal(signal.SIGTERM, _stop_loop)
        thread = runtime._thread
        if thread:
            # Short-interval joins so signals are handled promptly; after stop()
            # (which already joins with a timeout), do not wait forever.
            deadline: float | None = None
            while thread.is_alive():
                if stopped:
                    if deadline is None:
                        deadline = time.monotonic() + 1.0
                    if time.monotonic() >= deadline:
                        logger.warning(
                            "Runtime thread still alive after shutdown deadline"
                        )
                        break
                thread.join(timeout=0.5)
        return

    def _stop_web(signum: int, _frame: object) -> None:
        _stop(signum, _frame, hard_exit=True)

    signal.signal(signal.SIGINT, _stop_web)
    signal.signal(signal.SIGTERM, _stop_web)

    logger.info("Web UI on http://%s:%s", args.host, args.port)
    uvicorn.run(
        "pixelpixoo.web.app:app",
        host=args.host,
        port=args.port,
        log_level="debug" if verbose else "info",
        access_log=verbose,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        runtime.stop()
        sys.exit(0)
