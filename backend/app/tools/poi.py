import asyncio
import json
import re
import sqlite3
import time

from app.core.config import get_settings
from app.schemas.trip import Location
from app.services.amap import AMapError, AMapService, PoiResult

# 落盘缓存：同城市重复生成零 API 定位调用（TTL 7 天，坐标/地址基本不变）。
# 读全走内存（启动加载），写经队列异步穿盘；空路径=纯内存（测试用）。
POI_CACHE_TTL = 7 * 86400

_cache_db_path: str | None = None
_cache: dict[tuple[str, str, str], PoiResult | None] = {}
_cache_loaded = False
_writes: asyncio.Queue = asyncio.Queue()


def _resolve_db_path() -> str | None:
    global _cache_db_path
    if _cache_db_path is None:
        _cache_db_path = get_settings().poi_cache_db
    return _cache_db_path or None


def _load_cache() -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    db = _resolve_db_path()
    if not db:
        return
    try:
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT key, result, cached_at FROM poi_cache WHERE cached_at > ?",
                (time.time() - POI_CACHE_TTL,),
            ).fetchall()
            now = time.time()
            for key, result, cached_at in rows:
                if now - cached_at > POI_CACHE_TTL:
                    continue
                k = tuple(json.loads(key))
                _cache[k] = None if result is None else PoiResult.model_validate_json(result)
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # 缓存库损坏/不存在：当空缓存用，不能拖垮定位


async def _flush_cache() -> None:
    """排空写队列，立即落盘（测试与优雅收尾用）。"""
    db = _resolve_db_path()
    if not db:
        while not _writes.empty():
            _writes.get_nowait()
        return
    import os

    os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS poi_cache "
            "(key TEXT PRIMARY KEY, result TEXT, cached_at REAL)"
        )
        while not _writes.empty():
            key, value = _writes.get_nowait()
            result_json = None if value is None else value.model_dump_json()
            conn.execute(
                "INSERT OR REPLACE INTO poi_cache (key, result, cached_at) VALUES (?, ?, ?)",
                (json.dumps(key, ensure_ascii=False), result_json, time.time()),
            )
        conn.commit()
    finally:
        conn.close()


_flush_task: asyncio.Task | None = None


async def _periodic_flush() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            await _flush_cache()
        except Exception:  # noqa: BLE001 —— 后台落盘失败不影响定位，下轮再试
            pass


def _cache_set(key: tuple[str, str, str], value: PoiResult | None) -> None:
    global _flush_task
    _cache[key] = value
    db = _resolve_db_path()
    if db:
        _writes.put_nowait((key, value))
        if _flush_task is None or _flush_task.done():  # 懒启动定时落盘
            _flush_task = asyncio.create_task(_periodic_flush())


def clean_keyword(name: str) -> str:
    """LLM 生成的活动名常带类型前缀和分店后缀（"午餐·张老二凉粉（文殊院店）"），
    POI 搜索前剥掉，只留主名。"""
    s = re.sub(r"[（(].*?[)）]", "", name)
    parts = re.split(r"[·•・:：]", s)
    s = parts[-1].strip()
    return s or name


def _to_location(result: PoiResult | None) -> Location | None:
    if result is None:
        return None
    return Location(
        name=result.name,
        address=result.address,
        longitude=result.longitude,
        latitude=result.latitude,
        amap_poi_id=result.poi_id,
        resolved=True,
    )


async def search_poi(city: str, keyword: str, service: AMapService) -> Location | None:
    """POI 定位三级降级：POI 搜索（清洗名）→ POI 搜索（原名）→ 地理编码兜底。
    全部落空返回 None（resolved=false，前端降级展示）。结果进落盘缓存（含负缓存）。"""
    _load_cache()
    cleaned = clean_keyword(keyword)

    for kind, kw in (("clean", cleaned), ("raw", keyword)):
        cache_key = (city, kw, kind)
        if cache_key in _cache:
            loc = _to_location(_cache[cache_key])
            if loc is not None:
                return loc
            continue  # 缓存未命中，试下一级
        try:
            result = await service.search_poi(city, kw)
        except AMapError:
            continue  # 限流/网络：不写缓存，让下一级或重试轮次再试
        _cache_set(cache_key, result)
        loc = _to_location(result)
        if loc is not None:
            return loc

    # 地理编码兜底：配额独立，对区域/地标类名称容错好
    try:
        coords = await service.geocode(f"{city}{cleaned}", city)
    except AMapError:
        return None
    if coords is None:
        return None
    return Location(
        name=keyword,
        longitude=coords[0],
        latitude=coords[1],
        resolved=True,
    )


def clear_cache() -> None:
    global _cache_loaded
    _cache.clear()
    _cache_loaded = False
