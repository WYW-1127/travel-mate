import re

from app.schemas.trip import Location
from app.services.amap import AMapError, AMapService, PoiResult

# 高德限制：进程级缓存，重试轮次/同城市重复查询不重复消耗配额
_CACHE: dict[tuple[str, str, str], PoiResult | None] = {}


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
    全部落空返回 None（resolved=false，前端降级展示）。"""
    cleaned = clean_keyword(keyword)

    for kind, kw in (("clean", cleaned), ("raw", keyword)):
        cache_key = (city, kw, kind)
        if cache_key in _CACHE:
            loc = _to_location(_CACHE[cache_key])
            if loc is not None:
                return loc
            continue  # 缓存未命中，试下一级
        try:
            result = await service.search_poi(city, kw)
        except AMapError:
            continue  # 限流/网络：不写缓存，让下一级或重试轮次再试
        _CACHE[cache_key] = result
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
    _CACHE.clear()
