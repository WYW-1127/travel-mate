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


async def test_poi_tool_cleans_keyword_and_resolves():
    from app.services.amap import PoiResult
    from app.tools.poi import clear_cache, search_poi

    clear_cache()
    seen = []

    class FakeAMap:
        async def search_poi(self, city, kw):
            seen.append(kw)
            if kw == "张老二凉粉":
                return PoiResult(name=kw, address="addr", longitude=106.5, latitude=29.5, poi_id="P1")
            return None

        async def geocode(self, addr, city):
            return None

    loc = await search_poi("重庆", "午餐·张老二凉粉（文殊院店）", FakeAMap())  # type: ignore[arg-type]
    assert loc is not None and loc.resolved is True
    assert loc.amap_poi_id == "P1"
    assert seen == ["张老二凉粉"]  # 清洗名命中，无需再试原名


async def test_poi_tool_geocode_fallback_when_poi_misses():
    from app.tools.poi import clear_cache, search_poi

    clear_cache()

    class FakeAMap:
        async def search_poi(self, city, kw):
            return None

        async def geocode(self, addr, city):
            return (106.5, 29.5)

    loc = await search_poi("重庆", "某无名观景台", FakeAMap())  # type: ignore[arg-type]
    assert loc is not None and loc.resolved is True
    assert (loc.longitude, loc.latitude) == (106.5, 29.5)


async def test_poi_tool_all_levels_miss_returns_none():
    from app.tools.poi import clear_cache, search_poi

    clear_cache()

    class FakeAMap:
        async def search_poi(self, city, kw):
            return None

        async def geocode(self, addr, city):
            return None

    assert await search_poi("重庆", "完全不存在", FakeAMap()) is None  # type: ignore[arg-type]


async def test_poi_tool_swallows_amap_error():
    from app.services.amap import AMapError
    from app.tools.poi import clear_cache, search_poi

    clear_cache()

    class BrokenAMap:
        async def search_poi(self, city, keyword):
            raise AMapError("boom")

        async def geocode(self, addr, city):
            raise AMapError("boom")

    assert await search_poi("重庆", "x", BrokenAMap()) is None  # type: ignore[arg-type]


async def test_poi_tool_caches_hits():
    from app.services.amap import PoiResult
    from app.tools.poi import clear_cache, search_poi

    clear_cache()
    calls = []

    class FakeAMap:
        async def search_poi(self, city, kw):
            calls.append(kw)
            return PoiResult(name=kw, address="", longitude=106.5, latitude=29.5, poi_id="P")

        async def geocode(self, addr, city):
            return None

    svc = FakeAMap()
    await search_poi("重庆", "洪崖洞", svc)  # type: ignore[arg-type]
    await search_poi("重庆", "洪崖洞", svc)  # type: ignore[arg-type]
    assert calls == ["洪崖洞"]  # 第二次走缓存
