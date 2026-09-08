import json

from app.agent.chat_tools import MAX_TOOL_CALLS, ToolExecutor, build_tools
from app.services.amap import AMapService, PoiResult


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")
        self.poi_calls = 0

    async def resolve_city(self, name):
        return name

    async def search_poi(self, city, keyword):
        self.poi_calls += 1
        return PoiResult(name=keyword, address="a", longitude=120.1, latitude=30.2, poi_id="P")

    async def geocode(self, address, city=""):
        return (120.1, 30.2)


def test_build_tools_defines_search_poi_and_geocode():
    tools = build_tools()
    names = [t["function"]["name"] for t in tools]
    assert names == ["search_poi", "geocode"]
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
    assert "error" in json.loads(await ex.execute("weather", "{}"))
    assert "error" in json.loads(await ex.execute("search_poi", "不是json"))


async def test_quota_cap_blocks_after_max_calls():
    ex = ToolExecutor("杭州", FakeAMap(), max_calls=1)
    first = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "a"}'))
    assert "error" not in first
    second = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "b"}'))
    assert "上限" in second["error"]
    assert MAX_TOOL_CALLS == 15
