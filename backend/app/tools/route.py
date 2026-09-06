from app.services.amap import AMapError, AMapService


async def driving_route_minutes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    service: AMapService,
) -> int | None:
    try:
        return await service.driving_route_minutes(origin, destination)
    except AMapError:
        return None
