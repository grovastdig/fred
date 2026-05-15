"""
Fred Logger Utility
===================
Standard logging wrapper. Provides a consistent interface.
"""
import logging
import sys

def setup_logging(level: str = "INFO", log_file: str = None):
    """Configure root logger."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=getattr(logging, level), format=fmt, handlers=handlers)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"fred.{name}")
