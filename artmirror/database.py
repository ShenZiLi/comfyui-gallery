"""数据库初始化。

使用 SQLModel 连接 SQLite，建表逻辑集中在 models 包中导入后创建。
"""
import logging
import ntpath
import os
import re
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
    "loras_json": "TEXT DEFAULT ''",
    "parser_revision": "INTEGER NOT NULL DEFAULT 0",
}


def normalize_path_key(path: str) -> str:
    """返回跨平台比较用的规范化绝对路径。"""
    drive, _ = ntpath.splitdrive(path or "")
    if drive:
        return ntpath.normcase(ntpath.normpath(path))
    return os.path.normcase(os.path.abspath(os.path.normpath(path or "")))


def _backup_database(path) -> None:
    """通过 SQLite backup API 创建一次迁移前备份。"""
    backup_path = path.with_name(path.name + ".pre-path-identity.bak")
    if backup_path.exists():
        return
    source = sqlite3.connect(path, timeout=30)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
    finally:
        source.close()


def _migrate_image_path_identity(conn: sqlite3.Connection) -> bool:
    """移除全局相对路径唯一约束，增加未删除绝对路径唯一键。"""
    schema_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='imageasset'"
    ).fetchone()
    if not schema_row:
        return False
    schema = schema_row[0]
    columns = {r[1] for r in conn.execute("PRAGMA table_info(imageasset)")}
    needs_rebuild = "uq_image_path" in schema or "unique(file_path)" in schema.lower()
    needs_key = "path_key" not in columns
    if not needs_rebuild and not needs_key:
        rows = conn.execute("SELECT id, abs_path, path_key FROM imageasset").fetchall()
        for image_id, abs_path, current in rows:
            key = normalize_path_key(abs_path)
            if current != key:
                conn.execute("UPDATE imageasset SET path_key=? WHERE id=?", (key, image_id))
        _soft_delete_duplicate_path_keys(conn)
        return False

    # Build the replacement table from the existing schema so all legacy fields,
    # constraints and foreign keys remain intact. Only the relative-path unique
    # constraint is removed and path_key is appended when absent.
    new_schema = schema.replace("CREATE TABLE imageasset", "CREATE TABLE imageasset_new", 1)
    new_schema = re.sub(
        r",\s*CONSTRAINT\s+uq_image_path\s+UNIQUE\s*\(\s*file_path\s*\)",
        "",
        new_schema,
        flags=re.IGNORECASE,
    )
    new_schema = re.sub(
        r",\s*UNIQUE\s*\(\s*file_path\s*\)", "", new_schema, flags=re.IGNORECASE
    )
    if needs_key:
        constraint = re.search(
            r",\s*(?:CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE)\b",
            new_schema,
            flags=re.IGNORECASE,
        )
        if constraint:
            offset = constraint.start()
            new_schema = (
                new_schema[:offset]
                + ", path_key VARCHAR(4096) NOT NULL DEFAULT ''"
                + new_schema[offset:]
            )
        else:
            new_schema = new_schema.rstrip().rstrip(";")
            new_schema = new_schema[:-1] + ", path_key VARCHAR(4096) NOT NULL DEFAULT '')"

    old_columns = [r[1] for r in conn.execute("PRAGMA table_info(imageasset)")]
    new_columns = old_columns + (["path_key"] if needs_key else [])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(new_schema)
        target_cols = ",".join(f'"{c}"' for c in new_columns)
        source_cols = ",".join(f'"{c}"' for c in old_columns)
        if needs_key:
            conn.execute(
                f"INSERT INTO imageasset_new ({target_cols}) "
                f"SELECT {source_cols}, '' FROM imageasset"
            )
        else:
            conn.execute(
                f"INSERT INTO imageasset_new ({target_cols}) SELECT {source_cols} FROM imageasset"
            )
        for image_id, abs_path in conn.execute(
            "SELECT id, abs_path FROM imageasset_new"
        ).fetchall():
            conn.execute(
                "UPDATE imageasset_new SET path_key=? WHERE id=?",
                (normalize_path_key(abs_path), image_id),
            )
        _soft_delete_duplicate_path_keys(conn, table="imageasset_new")
        conn.execute("DROP TABLE imageasset")
        conn.execute("ALTER TABLE imageasset_new RENAME TO imageasset")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    logger.info("migrate: imageasset path identity")
    return True


def _soft_delete_duplicate_path_keys(conn: sqlite3.Connection, table: str = "imageasset") -> None:
    """同物理路径多条活动记录时保留最近更新的一条。"""
    rows = conn.execute(
        f"SELECT id, path_key, update_time FROM {table} WHERE is_deleted=0 AND path_key!=''"
    ).fetchall()
    grouped = {}
    for image_id, key, updated in rows:
        grouped.setdefault(key, []).append((str(updated or ""), int(image_id)))
    for duplicates in grouped.values():
        if len(duplicates) < 2:
            continue
        keep_id = max(duplicates)[1]
        for _, image_id in duplicates:
            if image_id != keep_id:
                conn.execute(f"UPDATE {table} SET is_deleted=1 WHERE id=?", (image_id,))


def _ensure_workflow_parser_revision(conn) -> None:
    cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(workflowmeta)")}
    if cols and "parser_revision" not in cols:
        conn.exec_driver_sql(
            "ALTER TABLE workflowmeta ADD COLUMN parser_revision INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("migrate: ADD COLUMN workflowmeta.parser_revision")


def _migrate_sqlite(db_path=None) -> None:
    settings.ensure_dirs()
    path = db_path or settings.db_path
    if not path.exists():
        return
    # Back up before any schema change; SQLite's backup API includes committed WAL data.
    probe = sqlite3.connect(path, timeout=30)
    try:
        table = probe.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='imageasset'"
        ).fetchone()
        cols = ({r[1] for r in probe.execute("PRAGMA table_info(imageasset)")} if table else set())
        meta_cols = {r[1] for r in probe.execute("PRAGMA table_info(workflowmeta)")}
        schema = table[0].lower() if table else ""
        migration_needed = (
            (table and ("uq_image_path" in schema or "unique(file_path)" in schema or "path_key" not in cols))
            or (meta_cols and "parser_revision" not in meta_cols)
        )
    finally:
        probe.close()
    if migration_needed:
        _backup_database(path)

    conn = sqlite3.connect(path, timeout=30)
    try:
        _migrate_image_path_identity(conn)
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
    "CREATE INDEX IF NOT EXISTS ix_imageasset_file_path ON imageasset(file_path)",
    "CREATE INDEX IF NOT EXISTS ix_imageasset_sha256 ON imageasset(sha256)",
    "CREATE INDEX IF NOT EXISTS ix_imageasset_path_key ON imageasset(path_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_image_path_key_active ON imageasset(path_key) WHERE is_deleted=0 AND path_key!=''",
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
        _ensure_workflow_parser_revision(conn)


def get_session():
    """FastAPI 依赖：提供数据库会话。"""
    with Session(get_engine()) as session:
        yield session
