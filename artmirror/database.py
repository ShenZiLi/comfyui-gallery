"""数据库初始化。

使用 SQLModel 连接 SQLite，建表逻辑集中在 models 包中导入后创建。
"""
import logging
import sqlite3

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from .config import settings

logger = logging.getLogger(__name__)

# SQLite 需 check_same_thread=False，便于后台线程访问；timeout 让并发写入等待而非报“database is locked”。
# engine 改为懒创建：按当前 settings.db_path 绑定，双启动器切换 data_dir 后经 reset_engine() 重建。
_engine = None


def _create_engine():
    return create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def get_engine():
    """获取（懒创建）当前配置绑定的 engine。"""
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def reset_engine() -> None:
    """重建 engine 绑定（启动器切换 data_dir 后调用，确保连接新库；幂等）。"""
    global _engine
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:  # noqa: BLE001
            pass
    _engine = None

# 引入所有模型以注册到 SQLModel.metadata（models 顶部统一导出）。
from . import models  # noqa: E402,F401


# 新增列迁移：SQLModel create_all 不会给既有表加列，这里手工补齐。
_WORKFLOW_META_COLUMNS = {
    "ai_prompt": "TEXT DEFAULT ''",
    "ai_negative_prompt": "TEXT DEFAULT ''",
    "origin_prompts_json": "TEXT DEFAULT ''",
    "negative_prompts_json": "TEXT DEFAULT ''",
    "ai_prompts_json": "TEXT DEFAULT ''",
}


def _migrate_sqlite() -> None:
    settings.ensure_dirs()
    if not settings.db_path.exists():
        return
    conn = sqlite3.connect(settings.db_path, timeout=30)
    try:
        cur = conn.cursor()
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "workflowmeta" in tables:
            cols = {r[1] for r in cur.execute("PRAGMA table_info(workflowmeta)")}
            for name, ddl in _WORKFLOW_META_COLUMNS.items():
                if name not in cols:
                    cur.execute(f"ALTER TABLE workflowmeta ADD COLUMN {name} {ddl}")
                    logger.info("migrate: ADD COLUMN workflowmeta.%s", name)
        conn.commit()
    finally:
        conn.close()


# 查询性能索引：目录过滤 + 评分排序（幂等创建）
_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_image_folder ON imageasset(folder_id)",
    "CREATE INDEX IF NOT EXISTS ix_image_ai_rating ON imageasset(ai_rating)",
    "CREATE INDEX IF NOT EXISTS ix_image_rating ON imageasset(rating)",
)


def _ensure_indexes(conn) -> None:
    for ddl in _INDEX_DDL:
        conn.execute(text(ddl))


def init_db() -> None:
    """创建数据表与运行目录（幂等）。"""
    settings.ensure_dirs()
    _migrate_sqlite()
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        _ensure_indexes(conn)


def get_session():
    """FastAPI 依赖：提供数据库会话。"""
    with Session(get_engine()) as session:
        yield session