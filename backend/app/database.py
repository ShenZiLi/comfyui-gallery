"""数据库初始化。

使用 SQLModel 连接 SQLite，建表逻辑集中在 models 包中导入后创建。
"""
from sqlmodel import SQLModel, Session, create_engine

from .config import settings

# SQLite 需 check_same_thread=False，便于未来后台线程访问。
engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)

# 引入所有模型以注册到 SQLModel.metadata（models 顶部统一导出）。
from . import models  # noqa: E402,F401


def init_db() -> None:
    """创建数据表与运行目录（幂等）。"""
    settings.ensure_dirs()
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI 依赖：提供数据库会话。"""
    with Session(engine) as session:
        yield session