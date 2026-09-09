"""行程缓存：相似请求（归一化城市+天数+档位+偏好）命中历史行程秒回。

对齐"携程速度"的关键一步——重复计算变查找。对话修改不回写：缓存里永远是
原始生成结果；命中后用户仍可用对话微调。同步 sqlite 读写（毫秒级、低频）。
"""

import json
import sqlite3
from pathlib import Path

from app.core.config import get_settings
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip

MAX_ENTRIES = 200  # LRU 容量上限

_db_path: str | None = None


def _resolve() -> str:
    global _db_path
    if _db_path is None:
        _db_path = get_settings().trip_cache_db
    return _db_path


def cache_key(req: GenerateRequest) -> str:
    """城市+天数即命中：偏好/档位差异交给命中后的对话微调（用户决策：放宽匹配）。"""
    city = (req.destination or "").strip().lower()
    return f"{city}::{req.days}"


def load(req: GenerateRequest) -> Trip | None:
    db = _resolve()
    if not db:
        return None
    try:
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT trip FROM trip_cache WHERE key = ?", (cache_key(req),)
            ).fetchone()
            return Trip.model_validate_json(row[0]) if row else None
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return None  # 库损坏/数据不合法：当未命中


def save(req: GenerateRequest, trip: Trip) -> None:
    db = _resolve()
    if not db:
        return
    try:
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS trip_cache "
                "(key TEXT PRIMARY KEY, trip TEXT, cached_at REAL)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO trip_cache (key, trip, cached_at) VALUES (?, ?, julianday('now'))",
                (cache_key(req), trip.model_dump_json(by_alias=True)),
            )
            # LRU：超容量删最旧
            conn.execute(
                "DELETE FROM trip_cache WHERE key NOT IN "
                "(SELECT key FROM trip_cache ORDER BY cached_at DESC LIMIT ?)",
                (MAX_ENTRIES,),
            )
            conn.commit()
        finally:
            conn.close()
    except (sqlite3.Error, ValueError, json.JSONDecodeError):
        pass  # 缓存写入失败不影响主流程


def clear() -> None:
    db = _resolve()
    if not db:
        return
    try:
        conn = sqlite3.connect(db)
        try:
            conn.execute("DELETE FROM trip_cache")
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass
