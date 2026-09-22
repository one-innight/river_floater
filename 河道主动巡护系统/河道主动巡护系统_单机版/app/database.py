import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .config import DATABASE_PATH


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(DATABASE_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                longitude REAL,
                latitude REAL,
                level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 3),
                level_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                risk_score REAL NOT NULL,
                image_url TEXT NOT NULL,
                annotated_image_url TEXT,
                objects_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_no TEXT UNIQUE,
                location TEXT NOT NULL,
                longitude REAL,
                latitude REAL,
                level INTEGER NOT NULL,
                level_name TEXT NOT NULL,
                warning TEXT NOT NULL,
                title TEXT NOT NULL,
                advice TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                image_url TEXT NOT NULL,
                detection_id INTEGER NOT NULL,
                verification_detection_id INTEGER,
                handler TEXT,
                processing_note TEXT,
                verification_image_url TEXT,
                verification_level INTEGER,
                verification_name TEXT,
                verification_confidence REAL,
                verification_result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                handled_at TEXT,
                closed_at TEXT,
                FOREIGN KEY(detection_id) REFERENCES detections(id),
                FOREIGN KEY(verification_detection_id) REFERENCES detections(id)
            );

            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_detection_location_time
                ON detections(location, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_event_status
                ON events(status, updated_at DESC);
            """
        )
        # 兼容已存在的 MVP 数据库，增量补齐事件闭环字段。
        _ensure_column(db, "events", "handler", "TEXT")
        _ensure_column(db, "events", "processing_note", "TEXT")
        _ensure_column(db, "events", "verification_image_url", "TEXT")
        _ensure_column(db, "events", "verification_level", "INTEGER")
        _ensure_column(db, "events", "verification_name", "TEXT")
        _ensure_column(db, "events", "verification_confidence", "REAL")
        _ensure_column(db, "events", "verification_result", "TEXT")
        _ensure_column(db, "detections", "annotated_image_url", "TEXT")
        level_names = {
            0: "未发现漂浮物",
            1: "少量漂浮物",
            2: "中等数量漂浮物",
            3: "大量漂浮物",
        }
        for level, name in level_names.items():
            db.execute("UPDATE detections SET level_name = ? WHERE level = ?", (name, level))
            db.execute("UPDATE events SET level_name = ? WHERE level = ?", (name, level))


def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    if "objects_json" in item:
        item["objects"] = json.loads(item.pop("objects_json"))
    return item


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection() as db:
        return [row_to_dict(row) for row in db.execute(sql, params).fetchall()]


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connection() as db:
        return row_to_dict(db.execute(sql, params).fetchone())
