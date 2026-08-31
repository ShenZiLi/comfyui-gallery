"""通用工具：时间字段。"""
from datetime import datetime


def now() -> datetime:
    """统一时间戳（本地时间，满足 yyyy-MM-dd HH:mm:ss 传输）。"""
    return datetime.now()