
import logging
import logging.handlers
from pathlib import Path

# ── Anchor log directory to project root ─────────────────────────────────────
# backend/utils/logger.py → .parent = backend/utils → .parent = backend → .parent = project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR      = _PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Format strings ────────────────────────────────────────────────────────────
_FMT_CONSOLE = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_FMT_FILE    = "%(asctime)s [%(levelname)-8s] %(name)s %(funcName)s:%(lineno)d — %(message)s"
_DATE_FMT    = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
   
    logger = logging.getLogger(name)

    if logger.handlers:         
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False    

    # ── Console handler — INFO and above ──────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_FMT_CONSOLE, datefmt=_DATE_FMT))

    # ── Rotating file handler — DEBUG and above ───────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "docforge.log",
        maxBytes=5_000_000,  
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FMT_FILE, datefmt=_DATE_FMT))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger