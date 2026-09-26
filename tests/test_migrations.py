"""数据库迁移测试。"""
import sqlite3

from sqlalchemy import text
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


def test_path_identity_migration_removes_relative_unique_and_preserves_related_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "artmirror.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE imageasset (
            id INTEGER NOT NULL, is_deleted INTEGER NOT NULL DEFAULT 0,
            update_time TEXT NOT NULL, file_path TEXT NOT NULL,
            abs_path TEXT NOT NULL, CONSTRAINT uq_image_path UNIQUE(file_path),
            PRIMARY KEY(id)
        );
        CREATE TABLE workflowmeta (
            id INTEGER PRIMARY KEY, image_id INTEGER NOT NULL UNIQUE,
            prompt TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(image_id) REFERENCES imageasset(id)
        );
        INSERT INTO imageasset VALUES
            (1, 0, '2026-01-01', 'a/same.png', 'E:/outputs/same.png'),
            (2, 0, '2026-02-01', 'b/same.png', 'E:/outputs/same.png');
        INSERT INTO workflowmeta VALUES (10, 1, 'old prompt'), (20, 2, 'new prompt');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(database.settings, "data_dir", str(tmp_path))

    database._migrate_sqlite(db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, is_deleted, path_key FROM imageasset ORDER BY id").fetchall()
    assert rows == [
        (1, 1, "e:\\outputs\\same.png"),
        (2, 0, "e:\\outputs\\same.png"),
    ]
    assert conn.execute("SELECT image_id, prompt FROM workflowmeta ORDER BY id").fetchall() == [
        (1, "old prompt"), (2, "new prompt")
    ]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("INSERT INTO imageasset (id,is_deleted,update_time,file_path,abs_path,path_key) VALUES (3,0,'2026-03-01','a/same.png','E:/other/same.png','e:\\other\\same.png')")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM imageasset").fetchone()[0] == 3
    assert (tmp_path / "artmirror.db.pre-path-identity.bak").exists()
    conn.close()

    database._migrate_sqlite(db_path)


def test_workflow_parser_revision_migration_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-meta.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE workflowmeta (id INTEGER PRIMARY KEY, image_id INTEGER)"))
    with engine.begin() as conn:
        database._ensure_workflow_parser_revision(conn)
        database._ensure_workflow_parser_revision(conn)
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(workflowmeta)")}
    assert "parser_revision" in cols
