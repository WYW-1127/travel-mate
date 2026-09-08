import asyncio

import httpx
from pydantic import BaseModel

from app.core.config import get_settings

AMAP_BASE = "https://restapi.amap.com/v3"


class AMapError(RuntimeError):
    pass


class PoiResult(BaseModel):
    name: str
    address: str = ""
    longitude: float
    latitude: float
    poi_id: str = ""
    cityname: str = ""  # 结果归属城市（如 深圳市），用于城市归属校验
    distance_km: float | None = None  # 周边搜索时与中心点的距离


def _city_ok(result_city: str, wanted: str) -> bool:
    """POI 结果城市归属校验：任一为空视为通过，否则剥掉行政后缀后要求互相包含。"""
    if not result_city or not wanted:
        return True

    def strip(name: str) -> str:
        for suffix in ("特别行政区", "自治区", "省", "市", "区", "县", "地区", "盟"):
            name = name.removesuffix(suffix)
        return name

    a, b = strip(result_city), strip(wanted)
    return not a or not b or a in b or b in a


class AMapService:
    def __init__(self, key: str = "", client: httpx.AsyncClient | None = None):
        self._key = key or get_settings().amap_web_key
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _get(self, path: str, params: dict) -> dict:
        if not self._key:
            raise AMapError("AMAP_WEB_KEY 未配置（见 backend/.env.example）")
        if self._client is None:
            # trust_env=False：高德是国内服务，直连；否则 Windows 系统代理会把请求
            # 路由进本地代理（127.0.0.1:7897），代理对 restapi.amap.com 连接失败
            self._client = httpx.AsyncClient(timeout=10.0, trust_env=False)
        query = {**params, "key": self._key}
        # 个人 key QPS=3：限流退避两次（1s/2s），覆盖 QPS 与日配额两类 infocode
        rate_codes = {"10014", "10019", "10020", "10021", "10022", "10044"}
        for attempt, delay in enumerate((1.0, 2.0), start=1):
            resp = await self._client.get(f"{AMAP_BASE}{path}", params=query)
            resp.raise_for_status()
            data = resp.json()
            rate_limited = resp.status_code == 429 or data.get("infocode") in rate_codes
            if data.get("status") == "1":
                return data
            if rate_limited and attempt <= 2:
                await asyncio.sleep(delay)
                continue
            raise AMapError(
                f"高德接口错误 infocode={data.get('infocode')} info={data.get('info')}"
            )
        raise AMapError("高德接口重试后仍失败")  # 不可达，类型检查需要

    async def search_poi(self, city: str, keyword: str) -> PoiResult | None:
        data = await self._get(
            "/place/text",
            {"keywords": keyword, "city": city, "citylimit": "true", "offset": 1},
        )
        pois = data.get("pois") or []
        if not pois:
            return None
        p = pois[0]
        loc = str(p.get("location", "")).split(",")
        if len(loc) != 2:
            return None
        result = PoiResult(
            name=p.get("name", ""),
            address=p.get("address") or "",
            longitude=float(loc[0]),
            latitude=float(loc[1]),
            poi_id=p.get("id", ""),
            cityname=p.get("cityname") or "",
        )
        # 高德对无效 city 参数会退化为全国模糊搜索（坪山→搜出唐山图书馆），
        # 这里按请求城市做归属校验，不匹配视为"该城市没搜到"
        if not _city_ok(result.cityname, city):
            return None
        return result

    async def geocode(self, address: str, city: str = "") -> tuple[float, float] | None:
        params: dict = {"address": address}
        if city:
            params["city"] = city
        data = await self._get("/geocode/geo", params)
        geocodes = data.get("geocodes") or []
        if not geocodes:
            return None
        loc = str(geocodes[0].get("location", "")).split(",")
        if len(loc) != 2:
            return None
        return float(loc[0]), float(loc[1])

    async def resolve_admin(self, name: str) -> dict:
        """目的地 → 标准城市名 + adcode（天气接口需要行政区划码）。

        解析失败/非城市地域一律回退 {city: 原名, adcode: ""}，调用方无需处理异常。"""
        try:
            data = await self._get("/geocode/geo", {"address": name})
        except Exception:  # noqa: BLE001 —— HTTP/API 错误一律回退，辅助步骤不能拖垮定位
            return {"city": name, "adcode": ""}
        geocodes = data.get("geocodes") or []
        if not geocodes:
            return {"city": name, "adcode": ""}
        g = geocodes[0]
        city = g.get("city") or name
        if isinstance(city, list):  # 直辖市等场景 city 可能为空列表
            city = name
        return {"city": str(city) or name, "adcode": str(g.get("adcode") or "")}

    async def resolve_city(self, name: str) -> str:
        return (await self.resolve_admin(name))["city"]

    async def poi_detail(self, poi_id: str) -> dict | None:
        """POI 深度信息（营业时间/评分/人均/电话），字段可能缺失（空串），查不到返回 None。

        深度字段在高德返回的 biz_ext 里，且值可能是字符串或列表（cost 未填时为空列表）。"""
        try:
            data = await self._get("/place/detail", {"id": poi_id})
        except Exception:  # noqa: BLE001 —— 详情失败由调用方编码回传模型
            return None
        pois = data.get("pois") or []
        if not pois:
            return None
        p = pois[0]
        biz = p.get("biz_ext") or {}

        def _first(v) -> str:
            if isinstance(v, list):
                return str(v[0]).strip() if v else ""
            return str(v).strip() if v else ""

        ptype = (p.get("type") or "").split(";")[0]
        return {
            "name": p.get("name", ""),
            "type": ptype,
            "address": p.get("address") or "",
            "opentime": _first(biz.get("opentime2")) or _first(biz.get("open_time")) or (p.get("opentime") or ""),
            "rating": _first(biz.get("rating")),
            "cost": _first(biz.get("cost")),
            "tel": p.get("tel") or "",
        }

    async def weather_forecast(self, adcode: str) -> list[dict]:
        """目的地未来 3 天预报（extensions=all），独立免费配额，不占 POI 日配额。

        高德返回结构：{"forecasts": [{"city": …, "casts": [{date, dayweather, …}]}]}。
        区级 adcode（如坪山 440310）同样受支持。"""
        data = await self._get(
            "/weather/weatherInfo", {"city": adcode, "extensions": "all"}
        )
        forecasts = data.get("forecasts") or []
        if not forecasts:
            return []
        casts = forecasts[0].get("casts") or []
        return [
            {
                "date": c.get("date", ""),
                "dayweather": c.get("dayweather", ""),
                "nightweather": c.get("nightweather", ""),
                "daytemp": c.get("daytemp", ""),
                "nighttemp": c.get("nighttemp", ""),
            }
            for c in casts
        ]

    async def search_nearby(
        self, longitude: float, latitude: float, radius: int = 1000, keywords: str = ""
    ) -> list[PoiResult]:
        """周边搜索：中心坐标 radius 米内的 POI（可按关键词过滤），按距离升序。"""
        params: dict = {
            "location": f"{longitude},{latitude}",
            "radius": radius,
            "offset": 5,
            "sortrule": "distance",
        }
        if keywords:
            params["keywords"] = keywords
        data = await self._get("/place/around", params)
        results: list[PoiResult] = []
        for p in data.get("pois") or []:
            loc = str(p.get("location", "")).split(",")
            if len(loc) != 2:
                continue
            try:
                dist_km = round(int(p.get("distance") or 0) / 1000, 2)
            except (ValueError, TypeError):
                dist_km = None
            results.append(PoiResult(
                name=p.get("name", ""),
                address=p.get("address") or "",
                longitude=float(loc[0]),
                latitude=float(loc[1]),
                poi_id=p.get("id", ""),
                cityname=p.get("cityname") or "",
                distance_km=dist_km,
            ))
        return results

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
