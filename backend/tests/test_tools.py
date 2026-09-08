from app.schemas.trip import Activity, Day, Location, Trip
from app.services.amap import AMapService, PoiResult
from app.tools.budget import total_cost
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



class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")
        self.poi_calls = 0

    async def search_poi(self, city, keyword):
        self.poi_calls += 1
        if keyword == "雷峰塔":
            return PoiResult(name="雷峰塔", address="a", longitude=120.1, latitude=30.2, poi_id="P")
        return None

    async def geocode(self, addr, city=""):
        return None


async def test_poi_cache_roundtrip_and_negative_cache(tmp_path, monkeypatch):
    """落盘缓存：往返命中、未搜到也缓存（负缓存）、TTL 过期失效。"""
    import time as _time

    from app.tools import poi as poi_mod

    db = str(tmp_path / "poi.db")
    monkeypatch.setattr(poi_mod, "_cache_db_path", db)

    poi_mod.clear_cache()
    fake = FakeAMap()
    # 雷峰塔命中 clean 级(1次)；"不存在"走 clean+raw 两级(2次)后 geocode 兜底失败
    await poi_mod.search_poi("杭州", "雷峰塔", fake)
    await poi_mod.search_poi("杭州", "不存在的地方", fake)
    await poi_mod._flush_cache()
    assert fake.poi_calls == 3

    # 重新加载（模拟重启）：同关键词不再打 API
    poi_mod.clear_cache()
    loc1 = await poi_mod.search_poi("杭州", "雷峰塔", fake)
    loc2 = await poi_mod.search_poi("杭州", "不存在的地方", fake)
    assert fake.poi_calls == 3  # 零新增调用
    assert loc1 is not None and loc1.name == "雷峰塔"
    assert loc2 is None  # 负缓存保留

    # TTL 过期：把缓存时间改到 8 天前
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("UPDATE poi_cache SET cached_at = ?", (_time.time() - 8 * 86400,))
    conn.commit()
    conn.close()
    poi_mod.clear_cache()
    await poi_mod.search_poi("杭州", "雷峰塔", fake)
    assert fake.poi_calls == 4  # 过期后重新打 API
    await poi_mod._flush_cache()
