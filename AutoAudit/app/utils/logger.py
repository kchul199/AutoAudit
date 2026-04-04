"""로깅 설정 모듈"""
import logging
import os
import sys
from pathlib import Path
from datetime import datetime


def get_logger(name: str, log_dir: str = None) -> logging.Logger:
    """
    모듈별 로거 생성.
    LOG_LEVEL 환경변수로 레벨 제어 (DEBUG/INFO/WARNING/ERROR).
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # 중복 핸들러 방지

    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 파일 핸들러 (선택)
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file = Path(log_dir) / f"autoaudit_{datetime.now().strftime('%Y%m%d')}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
