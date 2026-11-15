from __future__ import annotations

import logging
import sys


def configure_logging() -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return logging.getLogger("pdfexel_api")
