from app.schemas.trip import Location
from app.services.amap import AMapError, AMapService


async def search_poi(city: str, keyword: str, service: AMapService) -> Location | None:
    try:
        result = await service.search_poi(city, keyword)
    except AMapError:
        return None
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
