"""Rotate screens / serve config UI."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn

from pixelpixoo.config import load_config
from pixelpixoo.persist import configure_logging
from pixelpixoo.runtime import os_environ_preview, runtime

logger = logging.getLogger(__name__)


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

    verbose = args.verbose or os.environ.get("PIXELPIXOO_VERBOSE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    configure_logging(verbose=verbose)

    if args.config:
        os.environ["PIXELPIXOO_CONFIG"] = str(args.config)

    preview = args.preview
    if preview is None and os_environ_preview():
        preview = Path(os_environ_preview())
    once = args.once or os.environ.get("PIXELPIXOO_ONCE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    no_web = args.no_web or os.environ.get("PIXELPIXOO_NO_WEB", "").lower() in (
        "1",
        "true",
        "yes",
    )

    cfg = load_config()
    runtime.start(cfg, preview_dir=preview, once=once)

    if once or no_web:
        # Wait for loop thread to finish (once) or block until signal
        def _stop(signum: int, _frame: object) -> None:
            logger.info("Signal %s — stopping", signum)
            runtime.stop()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        thread = runtime._thread
        if thread:
            thread.join()
        return

    def _stop(signum: int, _frame: object) -> None:
        logger.info("Signal %s — shutting down", signum)
        runtime.stop(timeout=5)
        # uvicorn will exit via KeyboardInterrupt in main thread usually;
        # force process exit for SIGTERM in Docker
        os._exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

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
