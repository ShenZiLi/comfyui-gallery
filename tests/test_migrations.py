"""数据库迁移测试（查询性能索引）。"""
from sqlmodel import SQLModel, create_engine

from artmirror import database


def test_ensure_indexes_creates_all_and_idempotent():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        database._ensure_indexes(conn)
        database._ensure_indexes(conn)  # 幂等：重复执行不报错
    with engine.connect() as conn:
        names = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
    assert {"ix_image_folder", "ix_image_ai_rating", "ix_image_rating"} <= names
