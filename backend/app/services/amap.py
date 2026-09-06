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
            self._client = httpx.AsyncClient(timeout=10.0)
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
        return PoiResult(
            name=p.get("name", ""),
            address=p.get("address") or "",
            longitude=float(loc[0]),
            latitude=float(loc[1]),
            poi_id=p.get("id", ""),
        )

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

    async def driving_route_minutes(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> int | None:
        data = await self._get(
            "/direction/driving",
            {
                "origin": f"{origin[0]},{origin[1]}",
                "destination": f"{destination[0]},{destination[1]}",
                "strategy": 0,
            },
        )
        paths = (data.get("route") or {}).get("paths") or []
        if not paths:
            return None
        return int(float(paths[0].get("duration", 0))) // 60

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
