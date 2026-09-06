from app.schemas.trip import Activity, Day, Location, Trip
from app.tools.budget import cost_by_type, total_cost
from app.tools.geo import haversine_km


def _trip(costs: list[tuple[str, float]]) -> Trip:
    return Trip(
        destination="重庆",
        days=[Day(activities=[Activity(name=n, cost=c) for n, c in costs])],
    )


def test_haversine_jiefangbei_to_hongyadong_about_1km():
    # 解放碑(106.5772,29.5580) -> 洪崖洞(106.5784,29.5626) 约 0.6km
    d = haversine_km(106.5772, 29.5580, 106.5784, 29.5626)
    assert 0.3 < d < 1.0


def test_haversine_zero_distance():
    assert haversine_km(106.0, 29.0, 106.0, 29.0) == 0.0


def test_total_cost_sums_all_days():
    trip = _trip([("A", 100.0), ("B", 50.5), ("C", None)])
    assert total_cost(trip) == 150.5


def test_cost_by_type_buckets():
    trip = Trip(
        destination="重庆",
        days=[
            Day(
                activities=[
                    Activity(name="a", type="attraction", cost=100),
                    Activity(name="m", type="meal", cost=50),
                    Activity(name="m2", type="meal", cost=25),
                ]
            )
        ],
    )
    assert cost_by_type(trip) == {"attraction": 100.0, "meal": 75.0}


async def test_poi_tool_returns_resolved_location():
    from app.services.amap import PoiResult
    from app.tools.poi import search_poi

    class FakeAMap:
        async def search_poi(self, city, keyword):
            return PoiResult(
                name=keyword, address="addr", longitude=106.5, latitude=29.5, poi_id="P1"
            )

    loc = await search_poi("重庆", "洪崖洞", FakeAMap())  # type: ignore[arg-type]
    assert loc is not None and loc.resolved is True
    assert loc.amap_poi_id == "P1"


async def test_poi_tool_swallows_amap_error():
    from app.services.amap import AMapError
    from app.tools.poi import search_poi

    class BrokenAMap:
        async def search_poi(self, city, keyword):
            raise AMapError("boom")

    assert await search_poi("重庆", "x", BrokenAMap()) is None  # type: ignore[arg-type]
