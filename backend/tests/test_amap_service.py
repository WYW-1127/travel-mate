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
async def test_geocode_returns_coords():
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "geocodes": [{"location": "106.55,29.56"}]},
        )
    )
    svc = _svc()
    assert await svc.geocode("解放碑", "重庆") == (106.55, 29.56)


def _poi_payload(cityname: str) -> dict:
    return {
        "status": "1",
        "pois": [
            {
                "name": "坪山文化聚落",
                "address": "坪山区",
                "location": "114.33,22.69",
                "id": "B0FFF",
                "cityname": cityname,
            }
        ],
    }


@respx.mock
async def test_search_poi_rejects_result_from_wrong_city():
    """无效 city 参数会让高德全国模糊搜索（坪山→搜出唐山），结果城市不匹配必须拒绝。"""
    respx.get(f"{BASE}/place/text").mock(
        return_value=httpx.Response(200, json=_poi_payload("唐山市"))
    )
    assert await _svc().search_poi("坪山", "图书馆") is None


@respx.mock
async def test_search_poi_accepts_matching_city():
    respx.get(f"{BASE}/place/text").mock(
        return_value=httpx.Response(200, json=_poi_payload("深圳市"))
    )
    r = await _svc().search_poi("深圳市", "坪山文化聚落")
    assert r is not None and r.cityname == "深圳市"


@respx.mock
async def test_resolve_city_normalizes_district_to_city():
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "geocodes": [{"city": "深圳市"}]},
        )
    )
    assert await _svc().resolve_city("坪山") == "深圳市"


@respx.mock
async def test_resolve_city_falls_back_to_name_on_failure():
    respx.get(f"{BASE}/geocode/geo").mock(return_value=httpx.Response(500, text="boom"))
    assert await _svc().resolve_city("坪山") == "坪山"


@respx.mock
async def test_resolve_city_empty_geocodes_falls_back():
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(200, json={"status": "1", "geocodes": []})
    )
    assert await _svc().resolve_city("不存在的地方") == "不存在的地方"


@respx.mock
async def test_poi_detail_parses_fields():
    respx.get(f"{BASE}/place/detail").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "name": "深圳欢乐谷",
                        "type": "风景名胜;公园;游乐场",
                        "address": "华侨城",
                        "biz_ext": {
                            "opentime2": "10:00-22:00",
                            "rating": "4.7",
                            "cost": [],
                        },
                        "tel": "0755-26949184",
                    }
                ],
            },
        )
    )
    d = await _svc().poi_detail("B0FFF")
    assert d == {
        "name": "深圳欢乐谷",
        "type": "风景名胜",
        "address": "华侨城",
        "opentime": "10:00-22:00",
        "rating": "4.7",
        "cost": "",
        "tel": "0755-26949184",
    }


@respx.mock
async def test_poi_detail_empty_returns_none():
    respx.get(f"{BASE}/place/detail").mock(
        return_value=httpx.Response(200, json={"status": "1", "pois": []})
    )
    assert await _svc().poi_detail("B0FFF") is None


@respx.mock
async def test_weather_forecast_parses_days():
    respx.get(f"{BASE}/weather/weatherInfo").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "1",
                "forecasts": [
                    {"city": "深圳市", "adcode": "440300", "province": "广东",
                     "reporttime": "2026-09-08 16:00:00",
                     "casts": [
                         {"date": "2026-09-08", "dayweather": "晴", "nightweather": "多云",
                          "daytemp": "30", "nighttemp": "25"}
                     ]},
                ],
            },
        )
    )
    days = await _svc().weather_forecast("440300")
    assert days == [
        {"date": "2026-09-08", "dayweather": "晴", "nightweather": "多云",
         "daytemp": "30", "nighttemp": "25"}
    ]


@respx.mock
async def test_weather_bad_adcode_raises():
    respx.get(f"{BASE}/weather/weatherInfo").mock(
        return_value=httpx.Response(200, json={"status": "0", "info": "INVALID"})
    )
    import pytest as _pytest
    from app.services.amap import AMapError as _AMapError

    with _pytest.raises(_AMapError):
        await _svc().weather_forecast("bad")


@respx.mock
async def test_resolve_admin_returns_city_and_adcode():
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "geocodes": [{"city": "深圳市", "adcode": "440300"}]},
        )
    )
    assert await _svc().resolve_admin("坪山") == {"city": "深圳市", "adcode": "440300"}


@respx.mock
async def test_search_nearby_returns_sorted_pois():
    respx.get(f"{BASE}/place/around").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {"name": "静心莲素食", "address": "隆福寺街", "location": "116.41,39.93",
                     "id": "B1", "cityname": "北京市", "distance": "150"},
                    {"name": "叙香斋素食", "address": "前门大街", "location": "116.40,39.90",
                     "id": "B2", "cityname": "北京市", "distance": "900"},
                ],
            },
        )
    )
    pois = await _svc().search_nearby(116.41, 39.93, radius=1000, keywords="素食")
    assert pois[0].name == "静心莲素食"
    assert pois[0].distance_km == 0.15
    assert respx.calls[0].request.url.params["radius"] == "1000"


@respx.mock
async def test_search_nearby_empty_returns_list():
    respx.get(f"{BASE}/place/around").mock(
        return_value=httpx.Response(200, json={"status": "1", "pois": []})
    )
    assert await _svc().search_nearby(116.41, 39.93) == []
