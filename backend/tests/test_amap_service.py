import httpx
import pytest
import respx

from app.services.amap import AMapError, AMapService

BASE = "https://restapi.amap.com/v3"


def _svc() -> AMapService:
    return AMapService(key="test-key", client=httpx.AsyncClient())


@respx.mock
async def test_search_poi_returns_first_poi():
    respx.get(f"{BASE}/place/text").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "name": "洪崖洞民俗风貌区",
                        "address": "渝中区嘉陵江滨江路88号",
                        "location": "106.578427,29.562647",
                        "id": "B00156LOL2",
                    }
                ],
            },
        )
    )
    r = await _svc().search_poi("重庆", "洪崖洞")
    assert r is not None
    assert r.name == "洪崖洞民俗风貌区"
    assert r.longitude == pytest.approx(106.578427)
    assert r.poi_id == "B00156LOL2"


@respx.mock
async def test_search_poi_empty_returns_none():
    respx.get(f"{BASE}/place/text").mock(
        return_value=httpx.Response(200, json={"status": "1", "pois": []})
    )
    assert await _svc().search_poi("重庆", "不存在的地方") is None


@respx.mock
async def test_amap_api_error_raises():
    respx.get(f"{BASE}/place/text").mock(
        return_value=httpx.Response(
            200, json={"status": "0", "infocode": "10001", "info": "INVALID_USER_KEY"}
        )
    )
    with pytest.raises(AMapError):
        await _svc().search_poi("重庆", "洪崖洞")


@respx.mock
async def test_amap_rate_limit_retries_once(monkeypatch):
    route = respx.get(f"{BASE}/place/text").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"status": "0", "infocode": "10021", "info": "DAILY_QUERY_OVER_LIMIT"},
            ),
            httpx.Response(
                200,
                json={"status": "1", "pois": [{"name": "x", "location": "106.5,29.5", "id": "P"}]},
            ),
        ]
    )

    async def _fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.services.amap.asyncio.sleep", _fake_sleep)
    r = await _svc().search_poi("重庆", "洪崖洞")
    assert r is not None and route.call_count == 2


async def test_missing_key_raises_without_network():
    svc = AMapService(key="", client=httpx.AsyncClient())
    with pytest.raises(AMapError, match="AMAP_WEB_KEY"):
        await svc.search_poi("重庆", "洪崖洞")


@respx.mock
async def test_geocode_and_route():
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "geocodes": [{"location": "106.55,29.56"}]},
        )
    )
    respx.get(f"{BASE}/direction/driving").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "1",
                "route": {"paths": [{"duration": "1500"}]},  # 秒
            },
        )
    )
    svc = _svc()
    assert await svc.geocode("解放碑", "重庆") == (106.55, 29.56)
    minutes = await svc.driving_route_minutes((106.55, 29.56), (106.58, 29.56))
    assert minutes == 25  # 1500s = 25min
