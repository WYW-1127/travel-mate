import json

from app.agent.chat_tools import MAX_TOOL_CALLS, ToolExecutor, build_tools
from app.services.amap import AMapService, PoiResult


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")
        self.poi_calls = 0
        self.searched_city: str | None = None
        self.admin = {"city": "深圳市", "adcode": "440300"}
        self.detail: dict | None = {"name": "大万世居", "type": "风景名胜", "address": "坪山大道",
                                    "opentime": "09:00-17:30", "rating": "", "cost": ""}
        self.forecast = [{"date": "2026-09-08", "dayweather": "晴", "nightweather": "多云",
                          "daytemp": "30", "nighttemp": "25"}]
        self.nearby = []

    async def resolve_admin(self, name):
        return self.admin

    async def search_poi(self, city, keyword):
        self.poi_calls += 1
        self.searched_city = city
        return PoiResult(name=keyword, address="a", longitude=120.1, latitude=30.2, poi_id="P")

    async def geocode(self, address, city=""):
        return (120.1, 30.2)

    async def poi_detail(self, poi_id):
        return self.detail

    async def weather_forecast(self, adcode):
        return self.forecast

    async def search_nearby(self, longitude, latitude, radius=1000, keywords=""):
        return self.nearby


def test_build_tools_defines_four_tools():
    tools = build_tools()
    names = [t["function"]["name"] for t in tools]
    assert names == ["search_poi", "geocode", "poi_detail", "search_around", "weather"]
    for t in tools:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


async def test_search_poi_tool_returns_location_json():
    ex = ToolExecutor("杭州", FakeAMap())
    out = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "雷峰塔"}'))
    assert out["name"] == "雷峰塔"
    assert out["longitude"] == 120.1 and out["resolved"] is True


async def test_geocode_tool_returns_coords():
    ex = ToolExecutor("杭州", FakeAMap())
    out = json.loads(await ex.execute("geocode", '{"address": "西湖区南山路", "city": "杭州"}'))
    assert out == {"longitude": 120.1, "latitude": 30.2}


async def test_unknown_tool_and_bad_args_return_error_json():
    ex = ToolExecutor("杭州", FakeAMap())
    assert "error" in json.loads(await ex.execute("travel_meta", "{}"))
    assert "error" in json.loads(await ex.execute("search_poi", "不是json"))


async def test_quota_cap_blocks_after_max_calls():
    ex = ToolExecutor("杭州", FakeAMap(), max_calls=1)
    first = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "a"}'))
    assert "error" not in first
    second = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "b"}'))
    assert "上限" in second["error"]
    assert MAX_TOOL_CALLS == 15


async def test_search_poi_uses_normalized_city():
    fake = FakeAMap()
    ex = ToolExecutor("坪山", fake)
    await ex.execute("search_poi", '{"city": "坪山", "keyword": "图书馆"}')
    assert fake.searched_city == "深圳市"  # 归一化后再搜索


async def test_poi_detail_tool_strips_empty_fields_and_counts_quota():
    fake = FakeAMap()
    ex = ToolExecutor("坪山", fake, max_calls=5)
    out = json.loads(await ex.execute("poi_detail", '{"poi_id": "B0FFF"}'))
    assert out["opentime"] == "09:00-17:30"
    assert "rating" not in out and "cost" not in out  # 空字段剔除，不诱导编造
    assert ex.remaining == 4  # 详情计入定位配额


async def test_poi_detail_missing_returns_error():
    fake = FakeAMap()
    fake.detail = None
    out = json.loads(await ex_execute(fake, "poi_detail", '{"poi_id": "X"}'))
    assert "error" in out


async def test_weather_tool_returns_forecast_without_consuming_quota():
    ex = ToolExecutor("坪山", FakeAMap(), max_calls=3)
    out = json.loads(await ex.execute("weather", "{}"))
    assert out["destination"] == "深圳市"
    assert out["forecast"][0]["dayweather"] == "晴"
    assert ex.remaining == 3  # 天气免费配额，不扣定位次数


async def test_weather_without_adcode_returns_error():
    fake = FakeAMap()
    fake.admin = {"city": "某地", "adcode": ""}
    out = json.loads(await ex_execute(fake, "weather", "{}"))
    assert "error" in out


async def ex_execute(fake, name, arguments):
    from app.agent.chat_tools import ToolExecutor as TE

    return await TE("坪山", fake).execute(name, arguments)


async def test_search_poi_caches_location_by_poi_id():
    fake = FakeAMap()
    ex = ToolExecutor("杭州", fake)
    await ex.execute("search_poi", '{"city": "杭州", "keyword": "雷峰塔"}')
    assert "P" in ex.poi_cache  # 工具结果按 poi_id 缓存，供最终 JSON 回填
    assert ex.poi_cache["P"]["longitude"] == 120.1


async def test_around_tool_returns_nearby_pois():
    fake = FakeAMap()
    fake.nearby = [
        PoiResult(name="静心莲素食", address="隆福寺街", longitude=116.41, latitude=39.93, poi_id="B1"),
    ]
    ex = ToolExecutor("北京", fake)
    out = json.loads(await ex.execute(
        "search_around", '{"longitude": 116.41, "latitude": 39.93, "keywords": "素食"}'))
    assert out["pois"][0]["name"] == "静心莲素食"
    assert "distance_km" in out["pois"][0]


async def test_around_tool_requires_coords():
    out = json.loads(await ToolExecutor("北京", FakeAMap()).execute("search_around", '{"keywords": "素食"}'))
    assert "error" in out


async def test_execute_records_call_trace():
    ex = ToolExecutor("杭州", FakeAMap())
    await ex.execute("search_poi", '{"city": "杭州", "keyword": "雷峰塔"}')
    await ex.execute("weather", "{}")
    await ex.execute("nope", "{}")
    assert [c["tool"] for c in ex.calls] == ["search_poi", "weather", "nope"]
    assert ex.calls[0]["is_error"] is False
    assert (120.1, 30.2) in ex.calls[0]["coords"]  # 幻觉检测数据源
    assert ex.calls[2]["is_error"] is True
    assert all(c["elapsed_ms"] >= 0 for c in ex.calls)
