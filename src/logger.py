import logging
import os
from datetime import datetime
from pathlib import Path


class LoggerService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, log_dir: str = "logs", level: int = logging.DEBUG):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(log_dir, f"{ts}_exec.log")
        self._logger = logging.getLogger("scraping")
        self._logger.setLevel(level)
        fh = logging.FileHandler(path, encoding="utf-8")
        ch = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        if not self._logger.handlers:
            self._logger.addHandler(fh)
            self._logger.addHandler(ch)

    def debug(self, msg): self._logger.debug(msg)
    def info(self, msg): self._logger.info(msg)
    def warning(self, msg): self._logger.warning(msg)
    def error(self, msg): self._logger.error(msg)
