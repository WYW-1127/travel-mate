# TravelMate 后端 MVP 实施计划（Part 1 / 共 2 部分）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可独立测试运行的 FastAPI 后端——SSE 流式行程生成与自然语言重规划，GLM 出意图、高德出坐标、Pydantic/Validator 把关。

**Architecture:** 五层结构（API → Agent → Service → Tool → Schema）。Planner/Replanner 是 async generator，逐个产出 SSE 事件；GLM 与高德客户端通过构造参数注入以便测试替换；LLM 永远不产出坐标，POI 富化由高德 Web Service 完成。

**Tech Stack:** Python 3.11、FastAPI、httpx、Pydantic v2 + pydantic-settings、pytest + pytest-asyncio + respx。

**Spec:** `docs/superpowers/specs/2026-09-06-travel-assistant-design.md`（本计划从该 spec 出发，执行者需同时阅读 spec）

## Global Constraints

- Python >= 3.11；依赖版本下限见 `backend/pyproject.toml`（已存在于仓库）
- 测试**绝不发起真实网络调用**：GLM 用假对象注入，高德用 respx 拦截 httpx
- GLM API Key 只在服务端（`.env`），`.env` 已在 `.gitignore`，仓库只放 `.env.example`
- LLM 输出中不包含经纬度；所有坐标来自高德（GCJ-02）
- SSE 帧格式：`data: {json}\n\n`，事件类型 `progress` / `complete` / `error`，JSON 键 camelCase（与 spec §4/§5.2 逐字一致）
- 测试/运行命令以 `backend/` 为 cwd（Windows Git Bash 下 venv Python 路径为 `.venv/Scripts/python`）；**git 命令一律在仓库根目录执行**，add 路径带 `backend/` 前缀

---

### Task 1: 项目骨架——配置、应用工厂、health 端点

**Files:**
- Create: `backend/app/__init__.py`（空）
- Create: `backend/app/core/__init__.py`（空）
- Create: `backend/app/core/config.py`
- Create: `backend/app/api/__init__.py`（空）
- Create: `backend/app/api/health.py`
- Create: `backend/app/main.py`
- Create: `backend/backend/____init__` 不需要；Create: `backend/tests/__init__.py` 不需要
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`
- Create: `backend/.env.example`
- Exists: `backend/pyproject.toml`（无需改动）

**Interfaces:**
- Consumes: 无（首个任务）
- Produces:
  - `app.core.config.Settings` / `get_settings() -> Settings`（字段：`glm_api_key: str=""`、`glm_model: str="glm-5.3-flash"`、`glm_base_url: str="https://open.bigmodel.cn/api/paas/v4"`、`amap_web_key: str=""`、`cors_origins: str="http://localhost:5173"`；属性 `has_glm: bool`、`has_amap: bool`）
  - `app.main.app`（FastAPI 实例，挂载 `/api/health`，CORS 放行 `cors_origins` 逗号分隔列表）
  - `tests/conftest.py` 的 `client` fixture：`AsyncClient`（ASGITransport，base_url=`http://test`）——后续 API 任务复用

- [ ] **Step 1: 建虚拟环境并安装依赖**

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest --version
```
Expected: 显示 pytest 8.x 版本号

- [ ] **Step 2: 写失败测试**

`backend/tests/conftest.py`：
```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    # 空字符串环境变量优先级高于 .env 文件——保证开发机配了真实 Key 后测试仍离线确定
    monkeypatch.setenv("GLM_API_KEY", "")
    monkeypatch.setenv("AMAP_WEB_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

`backend/tests/test_health.py`：
```python
async def test_health_returns_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "glm_configured" in body
    assert "amap_configured" in body
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_health.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'app'`

- [ ] **Step 4: 最小实现**

`backend/app/core/config.py`：
```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    glm_api_key: str = ""
    glm_model: str = "glm-5.3-flash"
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    amap_web_key: str = ""
    cors_origins: str = "http://localhost:5173"

    @property
    def has_glm(self) -> bool:
        return bool(self.glm_api_key)

    @property
    def has_amap(self) -> bool:
        return bool(self.amap_web_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/api/health.py`：
```python
from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "glm_configured": s.has_glm,
        "amap_configured": s.has_amap,
    }
```

`backend/app/main.py`：
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="TravelMate API")
    s = get_settings()
    origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
```

（另建空文件：`app/__init__.py`、`app/core/__init__.py`、`app/api/__init__.py`）

`backend/.env.example`：
```bash
# 智谱 GLM（https://open.bigmodel.cn 控制台获取）
GLM_API_KEY=
GLM_MODEL=glm-5.3-flash
# 高德 Web Service Key（https://console.amap.com，「Web服务」类型）
AMAP_WEB_KEY=
# 前端 dev 地址，逗号分隔多个
CORS_ORIGINS=http://localhost:5173
```

- [ ] **Step 5: 跑测试确认通过 + 提交**

Run: `.venv/Scripts/python -m pytest -v`
Expected: 1 passed

```bash
git add backend/app backend/tests backend/.env.example
git commit -m "feat(backend): 应用骨架——配置/健康检查/CORS"
```

---

### Task 2: Trip 核心 Schema（camelCase 对齐 spec §4）

**Files:**
- Create: `backend/app/schemas/__init__.py`（空）
- Create: `backend/app/schemas/trip.py`
- Test: `backend/tests/test_schemas_trip.py`

**Interfaces:**
- Consumes: 无
- Produces（后续所有任务依赖，字段别名 camelCase，`populate_by_name=True`，`extra="ignore"`）:
  - `CamelModel`（基类：`model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")`）
  - `ActivityType(str, Enum)`：`attraction|meal|transport|hotel|shopping`
  - `Location(CamelModel)`：`name: str`、`address: str=""`、`longitude: float|None=None`、`latitude: float|None=None`、`amap_poi_id: str=""`、`resolved: bool=False`
  - `Activity(CamelModel)`：`id: str=""`、`name: str`、`type: ActivityType=attraction`、`start_time: str|None=None`、`end_time: str|None=None`、`cost: float|None=None`、`notes: str=""`、`location: Location|None=None`
  - `Day(CamelModel)`：`title: str=""`、`activities: list[Activity]=[]`
  - `Travelers(CamelModel)`：`adults: int=1`、`children: int=0`
  - `Trip(CamelModel)`：`id: str=""`、`title: str=""`、`destination: str`、`start_date: str|None=None`、`travelers: Travelers=Travelers()`、`budget_limit: float|None=None`、`days: list[Day]=[]`、`version: int=1`、`warnings: list[str]=[]`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_schemas_trip.py`：
```python
import pytest
from pydantic import ValidationError

from app.schemas.trip import Activity, Location, Trip


def _trip_data() -> dict:
    return {
        "destination": "重庆",
        "startDate": "2026-10-01",
        "travelers": {"adults": 2, "children": 1},
        "budgetLimit": 5000,
        "days": [
            {
                "title": "城市漫游",
                "activities": [
                    {
                        "name": "洪崖洞民俗风貌区",
                        "type": "attraction",
                        "startTime": "09:30",
                        "endTime": "12:00",
                        "cost": 0,
                        "location": {
                            "name": "洪崖洞民俗风貌区",
                            "longitude": 106.578,
                            "latitude": 29.562,
                            "resolved": True,
                        },
                    },
                    {"name": "午餐·山城小汤圆", "type": "meal", "cost": 30},
                ],
            }
        ],
    }


def test_trip_accepts_camel_case_and_aliases_back():
    trip = Trip.model_validate(_trip_data())
    assert trip.destination == "重庆"
    assert trip.start_date == "2026-10-01"
    assert trip.days[0].activities[0].location.resolved is True
    dumped = trip.model_dump(by_alias=True)
    assert dumped["budgetLimit"] == 5000
    assert dumped["days"][0]["activities"][0]["startTime"] == "09:30"


def test_trip_rejects_bad_time_format():
    data = _trip_data()
    data["days"][0]["activities"][0]["startTime"] = "9点半"
    with pytest.raises(ValidationError):
        Trip.model_validate(data)


def test_location_rejects_coords_outside_china():
    with pytest.raises(ValidationError):
        Location(name="x", longitude=139.69, latitude=35.69, resolved=True)


def test_extra_fields_ignored():
    data = _trip_data()
    data["llmSays"] = "trust me"
    trip = Trip.model_validate(data)
    assert trip.destination == "重庆"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_schemas_trip.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'app.schemas'`

- [ ] **Step 3: 最小实现**

`backend/app/schemas/trip.py`：
```python
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )


class ActivityType(str, Enum):
    attraction = "attraction"
    meal = "meal"
    transport = "transport"
    hotel = "hotel"
    shopping = "shopping"


def _check_hhmm(v: str | None) -> str | None:
    if v is None:
        return v
    parts = v.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"时间必须是 HH:MM，收到 {v!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围，收到 {v!r}")
    return v


class Location(CamelModel):
    name: str
    address: str = ""
    longitude: float | None = None
    latitude: float | None = None
    amap_poi_id: str = ""
    resolved: bool = False

    @field_validator("longitude")
    @classmethod
    def _lon_in_china(cls, v: float | None) -> float | None:
        if v is not None and not 73 <= v <= 136:
            raise ValueError("经纬度必须在中国范围内（GCJ-02）")
        return v

    @field_validator("latitude")
    @classmethod
    def _lat_in_china(cls, v: float | None) -> float | None:
        if v is not None and not 3 <= v <= 54:
            raise ValueError("纬度必须在中国范围内（GCJ-02）")
        return v


class Activity(CamelModel):
    id: str = ""
    name: str
    type: ActivityType = ActivityType.attraction
    start_time: str | None = None
    end_time: str | None = None
    cost: float | None = None
    notes: str = ""
    location: Location | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _time_ok(cls, v: str | None) -> str | None:
        return _check_hhmm(v)


class Day(CamelModel):
    title: str = ""
    activities: list[Activity] = Field(default_factory=list)


class Travelers(CamelModel):
    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)


class Trip(CamelModel):
    id: str = ""
    title: str = ""
    destination: str
    start_date: str | None = None
    travelers: Travelers = Travelers()
    budget_limit: float | None = None
    days: list[Day] = Field(default_factory=list)
    version: int = 1
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_schemas_trip.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/tests/test_schemas_trip.py
git commit -m "feat(backend): Trip/Day/Activity/Location schema（camelCase 对齐前端）"
```

---

### Task 3: 请求与 SSE 事件 Schema

**Files:**
- Create: `backend/app/schemas/generate.py`
- Create: `backend/app/schemas/replan.py`
- Create: `backend/app/schemas/events.py`
- Test: `backend/tests/test_schemas_requests_events.py`

**Interfaces:**
- Consumes: Task 2 的 `Trip`、`Travelers`、`CamelModel`
- Produces:
  - `GenerateRequest(CamelModel)`：`destination: str`（1..50 字符）、`days: int`（1..15）、`start_date: str|None=None`、`travelers: Travelers=Travelers()`、`budget_limit: float|None=None(ge=0)`、`preferences: str=""`
  - `ReplanRequest(CamelModel)`：`trip: Trip`、`request: str`（1..2000 字符）
  - `ProgressStage(str, Enum)`：`analyze|plan|enrich|validate`
  - `ProgressEvent`：`type: Literal["progress"]="progress"`、`stage: ProgressStage`、`message: str`
  - `CompleteEvent`：`type: Literal["complete"]="complete"`、`trip: Trip`
  - `ErrorEvent`：`type: Literal["error"]="error"`、`code: str`、`message: str`
  - `StreamEvent = ProgressEvent | CompleteEvent | ErrorEvent`
  - `encode_event(e: StreamEvent) -> str`：返回 `f"data: {e.model_dump_json(by_alias=True)}\n\n"`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_schemas_requests_events.py`：
```python
import pytest
from pydantic import ValidationError

from app.schemas.events import CompleteEvent, ErrorEvent, ProgressEvent, encode_event
from app.schemas.generate import GenerateRequest
from app.schemas.replan import ReplanRequest


def test_generate_request_defaults():
    req = GenerateRequest.model_validate({"destination": "重庆", "days": 3})
    assert req.travelers.adults == 1
    assert req.preferences == ""


def test_generate_request_rejects_zero_days():
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate({"destination": "重庆", "days": 0})


def test_replan_request_wraps_trip():
    req = ReplanRequest.model_validate(
        {"trip": {"destination": "重庆", "days": []}, "request": "别太赶"}
    )
    assert req.trip.destination == "重庆"


def test_encode_event_progress_frame():
    frame = encode_event(ProgressEvent(stage="plan", message="正在规划第 1 天"))
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert '"type":"progress"' in frame
    assert '"stage":"plan"' in frame


def test_encode_event_error_frame():
    frame = encode_event(ErrorEvent(code="GLM_ERROR", message="x"))
    assert '"type":"error"' in frame and '"code":"GLM_ERROR"' in frame


def test_encode_event_complete_contains_trip():
    frame = encode_event(
        CompleteEvent(trip={"destination": "重庆"})
    )
    assert '"type":"complete"' in frame
    assert '"destination":"重庆"' in frame
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_schemas_requests_events.py -v`
Expected: FAIL——`No module named 'app.schemas.generate'`

- [ ] **Step 3: 最小实现**

`backend/app/schemas/generate.py`：
```python
from pydantic import Field

from app.schemas.trip import CamelModel, Travelers


class GenerateRequest(CamelModel):
    destination: str = Field(min_length=1, max_length=50)
    days: int = Field(ge=1, le=15)
    start_date: str | None = None
    travelers: Travelers = Travelers()
    budget_limit: float | None = Field(default=None, ge=0)
    preferences: str = Field(default="", max_length=1000)
```

`backend/app/schemas/replan.py`：
```python
from pydantic import Field

from app.schemas.trip import CamelModel, Trip


class ReplanRequest(CamelModel):
    trip: Trip
    request: str = Field(min_length=1, max_length=2000)
```

`backend/app/schemas/events.py`：
```python
from enum import Enum
from typing import Literal

from app.schemas.trip import CamelModel, Trip


class ProgressStage(str, Enum):
    analyze = "analyze"
    plan = "plan"
    enrich = "enrich"
    validate = "validate"


class ProgressEvent(CamelModel):
    type: Literal["progress"] = "progress"
    stage: ProgressStage
    message: str


class CompleteEvent(CamelModel):
    type: Literal["complete"] = "complete"
    trip: Trip


class ErrorEvent(CamelModel):
    type: Literal["error"] = "error"
    code: str
    message: str


StreamEvent = ProgressEvent | CompleteEvent | ErrorEvent


def encode_event(event: StreamEvent) -> str:
    return f"data: {event.model_dump_json(by_alias=True)}\n\n"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_schemas_requests_events.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/tests/test_schemas_requests_events.py
git commit -m "feat(backend): generate/replan 请求与 SSE 事件 schema"
```

---

### Task 4: 高德 Web Service 客户端

**Files:**
- Create: `backend/app/services/__init__.py`（空）
- Create: `backend/app/services/amap.py`
- Test: `backend/tests/test_amap_service.py`

**Interfaces:**
- Consumes: Task 1 的 `get_settings`
- Produces:
  - `AMapError(RuntimeError)`
  - `PoiResult`（pydantic BaseModel，内部 DTO，不上 wire）：`name: str`、`address: str=""`、`longitude: float`、`latitude: float`、`poi_id: str=""`
  - `AMapService`：`__init__(self, key: str = "", client: httpx.AsyncClient | None = None)`；属性 `configured: bool`
    - `async search_poi(self, city: str, keyword: str) -> PoiResult | None`
    - `async geocode(self, address: str, city: str = "") -> tuple[float, float] | None`
    - `async driving_route_minutes(self, origin: tuple[float, float], destination: tuple[float, float]) -> int | None`
    - `async aclose(self) -> None`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_amap_service.py`：
```python
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
        return_value=httpx.Response(200, json={"status": "0", "infocode": "10001", "info": "INVALID_USER_KEY"})
    )
    with pytest.raises(AMapError):
        await _svc().search_poi("重庆", "洪崖洞")


@respx.mock
async def test_amap_rate_limit_retries_once(monkeypatch):
    route = respx.get(f"{BASE}/place/text").mock(
        side_effect=[
            httpx.Response(200, json={"status": "0", "infocode": "10021", "info": "DAILY_QUERY_OVER_LIMIT"}),
            httpx.Response(200, json={"status": "1", "pois": [{"name": "x", "location": "106.5,29.5", "id": "P"}]}),
        ]
    )
    monkeypatch.setattr("app.services.amap.asyncio.sleep", _fake_sleep)
    r = await _svc().search_poi("重庆", "洪崖洞")
    assert r is not None and route.call_count == 2


async def _fake_sleep(seconds: float) -> None:
    pass


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_amap_service.py -v`
Expected: FAIL——`No module named 'app.services'`

- [ ] **Step 3: 最小实现**

`backend/app/services/amap.py`（文件头部 `import asyncio`）：
```python
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
        for attempt in (1, 2):  # 限流退避：429 或并发超限 infocode 重试一次
            resp = await self._client.get(f"{AMAP_BASE}{path}", params=query)
            resp.raise_for_status()
            data = resp.json()
            rate_limited = (
                resp.status_code == 429 or data.get("infocode") in {"10019", "10020", "10021"}
            )
            if data.get("status") == "1":
                return data
            if rate_limited and attempt == 1:
                await asyncio.sleep(0.5)
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_amap_service.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services backend/tests/test_amap_service.py
git commit -m "feat(backend): 高德 Web Service 客户端（POI/地理编码/驾车路线）"
```

---

### Task 5: 工具层（geo / poi / route / budget 纯函数）

**Files:**
- Create: `backend/app/tools/__init__.py`（空）
- Create: `backend/app/tools/geo.py`
- Create: `backend/app/tools/poi.py`
- Create: `backend/app/tools/route.py`
- Create: `backend/app/tools/budget.py`
- Test: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: Task 4 的 `AMapService`/`AMapError`、Task 2 的 `Location`/`Trip`/`ActivityType`
- Produces:
  - `geo.haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float`
  - `poi.search_poi(city: str, keyword: str, service: AMapService) -> Location | None`（异常吞掉返回 None——工具失败不阻断 pipeline）
  - `route.driving_route_minutes(origin, destination, service) -> int | None`
  - `budget.total_cost(trip: Trip) -> float`（人均费用合计）
  - `budget.cost_by_type(trip: Trip) -> dict[str, float]`（键为 ActivityType 的 value）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_tools.py`：
```python
import httpx

from app.schemas.trip import Activity, Day, Location, Trip
from app.services.amap import AMapService
from app.tools.budget import cost_by_type, total_cost
from app.tools.geo import haversine_km


def _trip(costs: list[tuple[str, float]]) -> Trip:
    return Trip(
        destination="重庆",
        days=[
            Day(
                activities=[
                    Activity(name=n, cost=c)
                    for n, c in costs
                ]
            )
        ],
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


async def test_poi_tool_returns_resolved_location(monkeypatch):
    class FakeAMap:
        async def search_poi(self, city, keyword):
            from app.services.amap import PoiResult

            return PoiResult(
                name=keyword, address="addr", longitude=106.5, latitude=29.5, poi_id="P1"
            )

    from app.tools.poi import search_poi

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_tools.py -v`
Expected: FAIL——`No module named 'app.tools'`

- [ ] **Step 3: 最小实现**

`backend/app/tools/geo.py`：
```python
import math


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
```

`backend/app/tools/poi.py`：
```python
from app.schemas.trip import Location
from app.services.amap import AMapError, AMapService


async def search_poi(city: str, keyword: str, service: AMapService) -> Location | None:
    try:
        result = await service.search_poi(city, keyword)
    except AMapError:
        return None
    if result is None:
        return None
    return Location(
        name=result.name,
        address=result.address,
        longitude=result.longitude,
        latitude=result.latitude,
        amap_poi_id=result.poi_id,
        resolved=True,
    )
```

`backend/app/tools/route.py`：
```python
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
```

`backend/app/tools/budget.py`：
```python
from app.schemas.trip import ActivityType, Trip


def total_cost(trip: Trip) -> float:
    return sum(
        a.cost or 0.0 for day in trip.days for a in day.activities
    )


def cost_by_type(trip: Trip) -> dict[str, float]:
    result: dict[str, float] = {}
    for day in trip.days:
        for a in day.activities:
            key = ActivityType(a.type).value
            result[key] = result.get(key, 0.0) + (a.cost or 0.0)
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_tools.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools backend/tests/test_tools.py
git commit -m "feat(backend): 工具层——haversine/POI 包装/路线包装/预算汇总"
```

---

### Task 6: GLM 客户端（JSON 输出 + 降级提取）

**Files:**
- Create: `backend/app/services/glm.py`
- Test: `backend/tests/test_glm_service.py`

**Interfaces:**
- Consumes: Task 1 的 `get_settings`
- Produces:
  - `GLMError(RuntimeError)`
  - `extract_json(text: str) -> dict`（模块级纯函数：直接 loads → 剥 ```json 栅栏 → 首 `{` 到末 `}` 兜底）
  - `GLMService`：`__init__(self, api_key: str = "", model: str = "", base_url: str = "", client: httpx.AsyncClient | None = None)`；属性 `configured: bool`
    - `async chat_json(self, system: str, user: str, temperature: float = 0.3) -> dict`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_glm_service.py`：
```python
import httpx
import pytest
import respx

from app.services.glm import GLMError, GLMService, extract_json

BASE = "https://open.bigmodel.cn/api/paas/v4"


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = '好的，这是结果：\n```json\n{"a": [1, 2]}\n```\n希望有帮助'
    assert extract_json(text) == {"a": [1, 2]}


def test_extract_json_with_surrounding_text():
    assert extract_json('前缀 {"a": {"b": 2}} 后缀') == {"a": {"b": 2}}


def test_extract_json_garbage_raises():
    with pytest.raises(GLMError):
        extract_json("完全没有 JSON 的回答")


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}
    )


@respx.mock
async def test_chat_json_returns_parsed_dict():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=_chat_response('{"title": "重庆3日游"}')
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    assert await svc.chat_json("sys", "usr") == {"title": "重庆3日游"}


@respx.mock
async def test_chat_json_http_error_raises():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(429, text="rate limited")
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    with pytest.raises(GLMError, match="429"):
        await svc.chat_json("sys", "usr")


async def test_chat_json_without_key_raises():
    svc = GLMService(api_key="", client=httpx.AsyncClient())
    with pytest.raises(GLMError, match="GLM_API_KEY"):
        await svc.chat_json("sys", "usr")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_glm_service.py -v`
Expected: FAIL——`No module named 'app.services.glm'`

- [ ] **Step 3: 最小实现**

`backend/app/services/glm.py`：
```python
import json
import re

import httpx

from app.core.config import get_settings

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


class GLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise GLMError("GLM 返回内容中找不到合法 JSON")


class GLMService:
    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        s = get_settings()
        self._api_key = api_key or s.glm_api_key
        self._model = model or s.glm_model
        self._base_url = (base_url or s.glm_base_url).rstrip("/")
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def chat_json(self, system: str, user: str, temperature: float = 0.3) -> dict:
        if not self._api_key:
            raise GLMError("GLM_API_KEY 未配置（见 backend/.env.example）")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if resp.status_code != 200:
            raise GLMError(f"GLM HTTP {resp.status_code}: {resp.text[:200]}")
        content = resp.json()["choices"][0]["message"]["content"]
        return extract_json(content)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_glm_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/glm.py backend/tests/test_glm_service.py
git commit -m "feat(backend): GLM 客户端——JSON 模式 + 栅栏降级提取"
```

---

### Task 7: Validator（确定性规则，spec §5.5）

**Files:**
- Create: `backend/app/agent/__init__.py`（空）
- Create: `backend/app/agent/validator.py`
- Test: `backend/tests/test_validator.py`

**Interfaces:**
- Consumes: Task 2 的 `Trip`、Task 5 的 `haversine_km`/`total_cost`
- Produces:
  - `ValidationResult`（dataclass）：`failures: list[str]`、`warnings: list[str]`；属性 `ok: bool`（failures 为空）
  - `validate_trip(trip: Trip, check_poi: bool = True) -> ValidationResult`。规则：
    1. 单个活动 `end_time <= start_time` → failure
    2. 同天相邻时段重叠（按 start_time 排序后两两比较）→ failure
    3. `check_poi=True` 时：非 transport 活动中未解析（location 为 None 或 `resolved=False`）占比 > 30% → failure
    4. 同天相邻已解析活动直线距离 > 50km → warning
    5. `total_cost(trip) * (adults+children) > budget_limit` → warning（budget_limit 非 None 时）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_validator.py`：
```python
from app.agent.validator import validate_trip
from app.schemas.trip import Activity, Day, Location, Trip


def _loc(resolved: bool = True) -> Location:
    return Location(name="x", longitude=106.57, latitude=29.56, resolved=resolved)


def _trip(activities: list[Activity], budget: float | None = None) -> Trip:
    return Trip(
        destination="重庆",
        budget_limit=budget,
        travelers={"adults": 2, "children": 0},
        days=[Day(activities=activities)],
    )


def _act(name="A", start="09:00", end="10:00", cost=10.0, t="attraction", loc=None):
    return Activity(
        name=name, start_time=start, end_time=end, cost=cost, type=t, location=loc or _loc()
    )


def test_ok_trip_passes():
    trip = _trip([_act("A", "09:00", "10:00"), _act("B", "10:30", "11:30")])
    result = validate_trip(trip)
    assert result.ok and result.warnings == []


def test_end_before_start_fails():
    trip = _trip([_act("A", "10:00", "09:00")])
    result = validate_trip(trip)
    assert not result.ok
    assert any("结束" in f or "早于" in f for f in result.failures)


def test_overlap_fails():
    trip = _trip([_act("A", "09:00", "11:00"), _act("B", "10:00", "12:00")])
    result = validate_trip(trip)
    assert not result.ok
    assert any("重叠" in f for f in result.failures)


def test_unresolved_over_30pct_fails():
    acts = [_act("ok1"), _act("ok2"), _act("bad", loc=_loc(False))]
    result = validate_trip(_trip(acts))
    assert not result.ok
    assert any("未定位" in f or "定位" in f for f in result.failures)


def test_unresolved_20pct_passes():
    acts = [
        _act("ok1"), _act("ok2"), _act("ok3"),
        _act("ok4"), _act("ok5"), _act("bad", loc=_loc(False)),
    ]
    result = validate_trip(_trip(acts))
    assert result.ok


def test_check_poi_false_skips_ratio():
    acts = [_act("bad1", loc=_loc(False)), _act("bad2", loc=_loc(False))]
    assert validate_trip(_trip(acts), check_poi=False).ok


def test_far_distance_warns():
    far = Location(name="远", longitude=106.57, latitude=29.56, resolved=True)
    # 北京西站附近，距重庆 >1000km
    very_far = Location(name="更远", longitude=116.32, latitude=39.89, resolved=True)
    trip = _trip(
        [
            Activity(name="A", start_time="09:00", end_time="10:00", location=far),
            Activity(name="B", start_time="11:00", end_time="12:00", location=very_far),
        ]
    )
    result = validate_trip(trip)
    assert result.ok
    assert any("距离" in w for w in result.warnings)


def test_over_budget_warns():
    trip = _trip([_act("A", cost=3000.0), _act("B", cost=3000.0)], budget=5000.0)
    result = validate_trip(trip)
    assert result.ok
    assert any("预算" in w for w in result.warnings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_validator.py -v`
Expected: FAIL——`No module named 'app.agent'`

- [ ] **Step 3: 最小实现**

`backend/app/agent/validator.py`：
```python
from dataclasses import dataclass, field

from app.schemas.trip import Activity, ActivityType, Trip
from app.tools.budget import total_cost
from app.tools.geo import haversine_km


@dataclass
class ValidationResult:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _resolved(a: Activity) -> bool:
    return a.location is not None and a.location.resolved


def validate_trip(trip: Trip, check_poi: bool = True) -> ValidationResult:
    result = ValidationResult()

    for day_no, day in enumerate(trip.days, start=1):
        timed = [a for a in day.activities if a.start_time and a.end_time]
        for a in timed:
            if _minutes(a.end_time) <= _minutes(a.start_time):
                result.failures.append(
                    f"第{day_no}天「{a.name}」结束时间不晚于开始时间"
                )
        timed.sort(key=lambda a: a.start_time or "")
        for prev, cur in zip(timed, timed[1:]):
            if _minutes(cur.start_time or "00:00") < _minutes(prev.end_time or "00:00"):
                result.failures.append(
                    f"第{day_no}天「{prev.name}」与「{cur.name}」时段重叠"
                )

        for prev, cur in zip(day.activities, day.activities[1:]):
            if _resolved(prev) and _resolved(cur):
                assert prev.location and cur.location
                d = haversine_km(
                    prev.location.longitude or 0, prev.location.latitude or 0,
                    cur.location.longitude or 0, cur.location.latitude or 0,
                )
                if d > 50:
                    result.warnings.append(
                        f"第{day_no}天「{prev.name}」到「{cur.name}」直线距离 {d:.0f}km，较远"
                    )

    if check_poi:
        need_loc = [
            a for d in trip.days for a in d.activities
            if a.type != ActivityType.transport
        ]
        unresolved = [a for a in need_loc if not _resolved(a)]
        if need_loc and len(unresolved) / len(need_loc) > 0.3:
            result.failures.append(
                f"{len(unresolved)}/{len(need_loc)} 个地点未能在高德定位（超过 30%）"
            )

    if trip.budget_limit is not None:
        headcount = trip.travelers.adults + trip.travelers.children
        est = total_cost(trip) * headcount
        if est > trip.budget_limit:
            result.warnings.append(
                f"预估总费用 {est:.0f} 元（人均 {total_cost(trip):.0f} × {headcount} 人）"
                f"超出预算 {trip.budget_limit:.0f} 元"
            )

    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_validator.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent backend/tests/test_validator.py
git commit -m "feat(backend): 确定性校验器——时段/定位比例/距离/预算"
```

---

### Task 8: Prompt 模板（纯数据，随 Task 9 使用）

**Files:**
- Create: `backend/app/agent/prompts.py`

**Interfaces:**
- Consumes: Task 2 的 `Trip`/`GenerateRequest`（类型引用）
- Produces（全部返回 `(system, user)` 二元组）:
  - `trip_draft_messages(req: GenerateRequest, feedback: list[str]) -> tuple[str, str]`
  - `replan_scope_messages(trip: Trip, request: str) -> tuple[str, str]`
  - `day_regen_messages(trip: Trip, day_index: int, request: str, feedback: list[str]) -> tuple[str, str]`

说明：本任务无独立测试步骤——Prompt 是字符串模板，其行为在 Task 9/10 中通过假 GLM 捕获的入参与出参间接验证（假对象断言收到的 user 文本包含目的地等关键信息）。**右尺寸原则：纯数据文件折叠进第一个使用它的任务，不单列测试循环。**

- [ ] **Step 1: 实现**

`backend/app/agent/prompts.py`：
```python
import json

from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip

_DRAFT_SYSTEM = """你是资深国内旅行规划师。根据用户需求输出逐日行程 JSON。
规则：
1. 只输出 JSON，不要任何解释文字。
2. 严禁输出经纬度、地址等地理坐标——定位由地图系统完成。
3. 每天 3-6 个活动（含用餐），时段用 HH:MM，同一天内不得重叠，按时间排序。
4. cost 是人均预估费用（元），免费填 0。
5. type 取值：attraction | meal | transport | hotel | shopping。
6. 考虑地点之间的合理性（同一天活动集中在相邻区域）。
输出 JSON 结构：
{"title": "行程标题", "days": [{"title": "当天主题", "activities": [{"name": "地点或活动名（用高德可搜到的规范名称，如「洪崖洞民俗风貌区」而非「那个吊脚楼」）", "type": "attraction", "startTime": "09:30", "endTime": "12:00", "cost": 0, "notes": "提示，可空"}]}]}"""

_REPLAN_SCOPE_SYSTEM = """你是行程调整分析器。分析用户对现有行程的修改请求，找出需要重新规划的天。
只输出 JSON：{"affectedDayIndexes": [0, 2]}
dayIndex 从 0 开始。未被提及或不受影响的天不要包含。"""


def _feedback_block(feedback: list[str]) -> str:
    if not feedback:
        return ""
    return "\n\n上一版存在以下问题，必须修复：\n" + "\n".join(f"- {f}" for f in feedback)


def trip_draft_messages(req: GenerateRequest, feedback: list[str]) -> tuple[str, str]:
    head = req.travelers.adults + req.travelers.children
    user = (
        f"目的地：{req.destination}\n"
        f"天数：{req.days} 天\n"
        f"出发日期：{req.start_date or '未定'}\n"
        f"出行人数：成人 {req.travelers.adults}、儿童 {req.travelers.children}（共 {head} 人）\n"
        f"总预算：{f'{req.budget_limit:.0f} 元' if req.budget_limit else '未定'}\n"
        f"偏好与要求：{req.preferences or '无'}"
    )
    return _DRAFT_SYSTEM, user + _feedback_block(feedback)


def replan_scope_messages(trip: Trip, request: str) -> tuple[str, str]:
    days_summary = "\n".join(
        f"第{i}天（index={i}）「{d.title or '无主题'}」："
        + "、".join(a.name for a in d.activities)
        for i, d in enumerate(trip.days)
    )
    user = f"当前行程：\n{days_summary}\n\n用户调整请求：{request}"
    return _REPLAN_SCOPE_SYSTEM, user


def day_regen_messages(
    trip: Trip, day_index: int, request: str, feedback: list[str]
) -> tuple[str, str]:
    original = trip.days[day_index]
    others = "\n".join(
        f"第{i}天：{'、'.join(a.name for a in d.activities) if d.activities else d.title}"
        for i, d in enumerate(trip.days)
        if i != day_index
    )
    user = (
        f"目的地：{trip.destination}\n"
        f"其他天保持不变（供参考，避免重复安排）：\n{others or '（无）'}\n\n"
        f"需要重新规划：第 {day_index + 1} 天「{original.title}」，原内容：\n"
        f"{json.dumps([a.model_dump(by_alias=True) for a in original.activities], ensure_ascii=False)}\n\n"
        f"用户调整要求：{request}"
    )
    system = _DRAFT_SYSTEM.replace("根据用户需求输出逐日行程 JSON。", "重新规划单独一天。只输出该天的 JSON：{\"title\": \"...\", \"activities\": [...]}，字段规则不变。")
    return system, user + _feedback_block(feedback)
```

- [ ] **Step 2: 语法检查 + Commit**

Run: `.venv/Scripts/python -c "from app.agent.prompts import trip_draft_messages, replan_scope_messages, day_regen_messages; print('ok')"`
Expected: 输出 ok

```bash
git add backend/app/agent/prompts.py
git commit -m "feat(backend): 行程草稿/重规划作用域/单天重生成 Prompt 模板"
```

---

### Task 9: Planner（生成 pipeline + SSE 事件流）

**Files:**
- Create: `backend/app/agent/planner.py`
- Test: `backend/tests/test_planner.py`

**Interfaces:**
- Consumes: Task 2 `Trip/Day/Activity/Location/ActivityType`、Task 3 `GenerateRequest/ProgressEvent/CompleteEvent/ErrorEvent/ProgressStage`、Task 5 `poi.search_poi`、Task 6 `GLMService/GLMError`、Task 4 `AMapService`、Task 7 `validate_trip/ValidationResult`、Task 8 prompts
- Produces:
  - `enrich_activities(activities: list[Activity], destination: str, service: AMapService, put: Callable[[ProgressEvent], Awaitable[None]]) -> None`（async；并发 5；transport 跳过；命中→resolved Location，未命中→`Location(name=原名, resolved=False)`）
  - `draft_to_trip(draft: dict, req: GenerateRequest) -> Trip`（Pydantic 校验，失败抛 `ValidationError`）
  - `generate_trip(req: GenerateRequest, glm: GLMService | None = None, amap: AMapService | None = None) -> AsyncIterator[StreamEvent]`（async generator；默认参数内部构造真实服务；产出 progress 序列，成功结尾 `CompleteEvent`，失败结尾 `ErrorEvent`；含最多 2 次带反馈重试；`check_poi=amap.configured`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_planner.py`：
```python
import json

import pytest
from pydantic import ValidationError

from app.agent.planner import draft_to_trip, generate_trip
from app.schemas.events import ErrorEvent
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Activity, Location
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMError, GLMService

REQ = GenerateRequest.model_validate(
    {"destination": "重庆", "days": 2, "preferences": "带娃"}
)

GOOD_DRAFT = {
    "title": "重庆2日游",
    "days": [
        {
            "title": "D1",
            "activities": [
                {"name": "洪崖洞民俗风貌区", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0},
                {"name": "山城小汤圆", "type": "meal",
                 "startTime": "11:30", "endTime": "12:30", "cost": 30},
            ],
        },
        {
            "title": "D2",
            "activities": [
                {"name": "解放碑步行街", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0},
            ],
        },
    ],
}


class FakeGLM(GLMService):
    def __init__(self, drafts: list):
        super().__init__(api_key="fake")
        self.drafts = list(drafts)
        self.calls: list[tuple[str, str]] = []

    async def chat_json(self, system: str, user: str, temperature: float = 0.3):
        self.calls.append((system, user))
        d = self.drafts.pop(0)
        if isinstance(d, Exception):
            raise d
        return d


class FakeAMap(AMapService):
    def __init__(self, hits: set[str] | None = None, fail: bool = False):
        super().__init__(key="fake")
        self.hits = hits if hits is not None else {"洪崖洞民俗风貌区", "山城小汤圆", "解放碑步行街"}
        self.fail = fail

    async def search_poi(self, city: str, keyword: str):
        if self.fail:
            from app.services.amap import AMapError

            raise AMapError("amap down")
        if keyword in self.hits:
            return PoiResult(name=keyword, address="a", longitude=106.5, latitude=29.5, poi_id="P")
        return None


async def _collect(req=REQ, glm=None, amap=None):
    return [e async for e in generate_trip(req, glm=glm, amap=amap)]


def types(events):
    return [e.type for e in events]


async def test_happy_path_progress_then_complete():
    events = await _collect(glm=FakeGLM([GOOD_DRAFT]), amap=FakeAMap())
    assert types(events)[-1] == "complete"
    stages = [e.stage for e in events if e.type == "progress"]
    assert stages[0] == "analyze"
    assert "plan" in stages and "enrich" in stages
    trip = events[-1].trip
    assert trip.destination == "重庆"
    assert trip.title == "重庆2日游"
    assert trip.days[0].activities[0].location.resolved is True


async def test_unresolved_poi_kept_with_flag():
    amap = FakeAMap(hits={"洪崖洞民俗风貌区", "山城小汤圆", "解放碑步行街"} - {"山城小汤圆"})
    events = await _collect(glm=FakeGLM([GOOD_DRAFT]), amap=amap)
    complete = events[-1]
    act = complete.trip.days[0].activities[1]
    assert act.name == "山城小汤圆"
    assert act.location is not None and act.location.resolved is False


async def test_validation_failure_triggers_retry_with_feedback():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][1]["startTime"] = "09:30"  # 与第一个重叠
    glm = FakeGLM([bad, GOOD_DRAFT])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert types(events)[-1] == "complete"
    assert len(glm.calls) == 2
    assert "重叠" in glm.calls[1][1]  # 反馈进入第二次 prompt


async def test_exhausted_retries_yields_error_event():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][1]["startTime"] = "09:30"
    glm = FakeGLM([bad, bad, bad])
    events = await _collect(glm=glm, amap=FakeAMap())
    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert last.code == "VALIDATION_FAILED"
    assert len(glm.calls) == 3  # 首次 + 2 次重试


async def test_glm_error_yields_error_event():
    glm = FakeGLM([GLMError("GLM_API_KEY 未配置")])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "GLM_ERROR"


async def test_invalid_draft_shape_counts_as_failure_and_retries():
    glm = FakeGLM([{"days": "不是列表"}, GOOD_DRAFT])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert types(events)[-1] == "complete"
    assert len(glm.calls) == 2


def test_draft_to_trip_merges_request_fields():
    trip = draft_to_trip(GOOD_DRAFT, REQ)
    assert trip.destination == "重庆"
    assert trip.travelers.adults == 1
    assert trip.version == 1


def test_draft_to_trip_rejects_garbage():
    with pytest.raises(ValidationError):
        draft_to_trip({"days": "不是列表"}, REQ)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_planner.py -v`
Expected: FAIL——`No module named 'app.agent.planner'`

- [ ] **Step 3: 实现**

`backend/app/agent/planner.py`：
```python
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from pydantic import ValidationError

from app.agent.prompts import trip_draft_messages
from app.agent.validator import validate_trip
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
)
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Activity, ActivityType, Location, Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService
from app.tools.poi import search_poi

MAX_ATTEMPTS = 3  # 首次 + 2 次带反馈重试
CONCURRENCY = 5


async def enrich_activities(
    activities: list[Activity],
    destination: str,
    service: AMapService,
    put: Callable[[ProgressEvent], Awaitable[None]],
) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    total = len(activities)

    async def one(act: Activity) -> None:
        nonlocal done
        async with sem:
            if act.type != ActivityType.transport:
                loc = await search_poi(destination, act.name, service)
                act.location = loc or Location(name=act.name, resolved=False)
            done += 1
            await put(
                ProgressEvent(
                    stage=ProgressStage.enrich,
                    message=f"正在定位地点（{done}/{total}）",
                )
            )

    await asyncio.gather(*(one(a) for a in activities))


def draft_to_trip(draft: dict, req: GenerateRequest) -> Trip:
    data = {
        **draft,
        "destination": req.destination,
        "startDate": req.start_date,
        "travelers": req.travelers.model_dump(by_alias=True),
        "budgetLimit": req.budget_limit,
        "version": 1,
    }
    return Trip.model_validate(data)


async def generate_trip(
    req: GenerateRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService()
    amap = amap or AMapService()
    feedback: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if attempt == 1:
                yield ProgressEvent(
                    stage=ProgressStage.analyze, message="正在分析旅行需求"
                )
            else:
                yield ProgressEvent(
                    stage=ProgressStage.validate,
                    message=f"发现 {len(feedback)} 个问题，正在修正（第 {attempt - 1} 次重试）",
                )
            yield ProgressEvent(
                stage=ProgressStage.plan,
                message=f"正在规划 {req.destination} {req.days} 天行程",
            )
            system, user = trip_draft_messages(req, feedback)
            try:
                draft = await glm.chat_json(system, user)
            except GLMError as e:
                yield ErrorEvent(code="GLM_ERROR", message=str(e))
                return

            try:
                trip = draft_to_trip(draft, req)
            except ValidationError as e:
                feedback = [f"行程 JSON 结构不合法：{e.errors()[:3]}"]
                continue

            yield ProgressEvent(stage=ProgressStage.enrich, message="正在定位行程中的地点")
            queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
            enrich_task = asyncio.create_task(
                enrich_activities(
                    [a for d in trip.days for a in d.activities],
                    req.destination,
                    amap,
                    queue.put,
                )
            )
            # 轮询转发富化进度（事件 <100 个，10ms 开销可忽略）
            while not enrich_task.done() or not queue.empty():
                if queue.empty() and not enrich_task.done():
                    await asyncio.sleep(0.01)
                    continue
                while not queue.empty():
                    yield queue.get_nowait()
            await enrich_task

            yield ProgressEvent(stage=ProgressStage.validate, message="正在检查行程合理性")
            result = validate_trip(trip, check_poi=amap.configured)
            if result.ok:
                trip.warnings = result.warnings
                yield CompleteEvent(trip=trip)
                return
            feedback = result.failures

    yield ErrorEvent(
        code="VALIDATION_FAILED",
        message="多次尝试后行程仍未通过校验：" + "；".join(feedback),
    )
```

（`queue.put` 是协程方法，天然满足 `Callable[[ProgressEvent], Awaitable[None]]` 签名。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_planner.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/planner.py backend/tests/test_planner.py
git commit -m "feat(backend): Planner——草稿/POI富化/校验/带反馈重试 pipeline"
```

---

### Task 10: Replanner（自然语言重规划，spec §5.4）

**Files:**
- Create: `backend/app/agent/replanner.py`
- Test: `backend/tests/test_replanner.py`

**Interfaces:**
- Consumes: Task 9 的 `enrich_activities`、Task 8 `replan_scope_messages/day_regen_messages`、Task 3 `ReplanRequest`、Task 2 `Day`、其余同 Task 9
- Produces:
  - `replan_trip(req: ReplanRequest, glm: GLMService | None = None, amap: AMapService | None = None) -> AsyncIterator[StreamEvent]`：作用域解析（`affectedDayIndexes` 越界/非法值过滤，空→`ErrorEvent(code="SCOPE_EMPTY")`）→ 逐天重生成（ValidationError/校验失败计入 feedback，对**所有受影响天**整体最多重试 1 次）→ `version+1` → `CompleteEvent`（完整 Trip，未受影响的天原样保留）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_replanner.py`：
```python
from app.agent.replanner import replan_trip
from app.schemas.replan import ReplanRequest
from app.schemas.trip import Trip
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMService

TRIP_DATA = {
    "id": "t1",
    "title": "重庆2日游",
    "destination": "重庆",
    "version": 1,
    "travelers": {"adults": 2, "children": 1},
    "budgetLimit": 5000,
    "days": [
        {
            "title": "D1",
            "activities": [
                {"id": "a1", "name": "长江索道", "type": "attraction",
                 "startTime": "09:00", "endTime": "10:00", "cost": 20,
                 "location": {"name": "长江索道", "resolved": True,
                              "longitude": 106.58, "latitude": 29.56}},
                {"id": "a2", "name": "洪崖洞", "type": "attraction",
                 "startTime": "11:00", "endTime": "13:00", "cost": 0,
                 "location": {"name": "洪崖洞", "resolved": True,
                              "longitude": 106.58, "latitude": 29.56}},
            ],
        },
        {
            "title": "D2",
            "activities": [
                {"id": "a3", "name": "解放碑", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0,
                 "location": {"name": "解放碑", "resolved": True,
                              "longitude": 106.577, "latitude": 29.558}},
            ],
        },
    ],
}


class FakeGLM(GLMService):
    def __init__(self, responses: list):
        super().__init__(api_key="fake")
        self.responses = list(responses)
        self.users: list[str] = []

    async def chat_json(self, system, user, temperature=0.3):
        self.users.append(user)
        return self.responses.pop(0)


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")

    async def search_poi(self, city, keyword):
        return PoiResult(name=keyword, address="", longitude=106.5, latitude=29.5, poi_id="P")


NEW_DAY = {
    "title": "D1-悠闲",
    "activities": [
        {"name": "山城步道", "type": "attraction", "startTime": "10:00", "endTime": "12:00", "cost": 0},
        {"name": "午餐·小面", "type": "meal", "startTime": "12:30", "endTime": "13:30", "cost": 25},
    ],
}


def _req() -> ReplanRequest:
    return ReplanRequest.model_validate(
        {"trip": TRIP_DATA, "request": "第一天别太赶，不要长江索道"}
    )


async def test_replan_replaces_only_affected_day():
    glm = FakeGLM([{"affectedDayIndexes": [0]}, NEW_DAY])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    complete = events[-1]
    assert complete.type == "complete"
    trip = complete.trip
    assert trip.version == 2
    assert trip.days[0].title == "D1-悠闲"
    assert trip.days[1].title == "D2"          # 未受影响
    assert trip.days[1].activities[0].id == "a3"  # 原 activity 原样保留
    assert trip.id == "t1"
    assert trip.days[0].activities[0].location.resolved is True


async def test_scope_prompt_contains_trip_and_request():
    glm = FakeGLM([{"affectedDayIndexes": [0]}, NEW_DAY])
    _ = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert "长江索道" in glm.users[0]
    assert "别太赶" in glm.users[0]


async def test_empty_scope_yields_error():
    glm = FakeGLM([{"affectedDayIndexes": []}])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "error"
    assert events[-1].code == "SCOPE_EMPTY"


async def test_out_of_range_indexes_filtered():
    glm = FakeGLM([{"affectedDayIndexes": [0, 7, -1]}, NEW_DAY])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "complete"


async def test_bad_day_retried_once_then_error():
    bad_day = {"title": "bad", "activities": [{"name": "x", "startTime": "10:00", "endTime": "09:00", "cost": 0}]}
    glm = FakeGLM([{"affectedDayIndexes": [0]}, bad_day, bad_day])
    events = [e async for e in replan_trip(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "error"
    assert events[-1].code == "VALIDATION_FAILED"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_replanner.py -v`
Expected: FAIL——`No module named 'app.agent.replanner'`

- [ ] **Step 3: 实现**

`backend/app/agent/replanner.py`：
```python
from collections.abc import AsyncIterator

from pydantic import ValidationError

from app.agent.planner import enrich_activities
from app.agent.prompts import day_regen_messages, replan_scope_messages
from app.agent.validator import validate_trip
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
)
from app.schemas.replan import ReplanRequest
from app.schemas.trip import Day, Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService

MAX_REGEN_ATTEMPTS = 2  # 首次 + 1 次重试


async def replan_trip(
    req: ReplanRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService()
    amap = amap or AMapService()
    trip = req.trip.model_copy(deep=True)

    yield ProgressEvent(stage=ProgressStage.analyze, message="正在理解你的调整需求")
    try:
        scope = await glm.chat_json(*replan_scope_messages(trip, req.request))
    except GLMError as e:
        yield ErrorEvent(code="GLM_ERROR", message=str(e))
        return

    raw = scope.get("affectedDayIndexes", [])
    indexes = sorted(
        {i for i in raw if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(trip.days)}
    )
    if not indexes:
        yield ErrorEvent(
            code="SCOPE_EMPTY",
            message="没有识别出需要调整的行程，请描述得更具体一些（如「第一天别太赶」）",
        )
        return

    feedback: list[str] = []
    for attempt in range(1, MAX_REGEN_ATTEMPTS + 1):
        ok = True
        for idx in indexes:
            yield ProgressEvent(
                stage=ProgressStage.plan,
                message=f"正在重新规划第 {idx + 1} 天"
                + (f"（{attempt - 1} 次重试）" if attempt > 1 else ""),
            )
            try:
                system, user = day_regen_messages(trip, idx, req.request, feedback)
                day_draft = await glm.chat_json(system, user)
                new_day = Day.model_validate(day_draft)
            except (GLMError, ValidationError) as e:
                feedback = [f"第 {idx + 1} 天重新生成失败：{e}"]
                ok = False
                break

            yield ProgressEvent(
                stage=ProgressStage.enrich, message=f"正在定位第 {idx + 1} 天的地点"
            )

            async def put(ev: ProgressEvent) -> None:
                pass  # replan 场景逐天进度已足够，不再细粒度透传

            await enrich_activities(new_day.activities, trip.destination, amap, put)
            trip.days[idx] = new_day

        if not ok:
            continue

        yield ProgressEvent(stage=ProgressStage.validate, message="正在检查调整后的行程")
        result = validate_trip(trip, check_poi=amap.configured)
        if result.ok:
            trip.version += 1
            trip.warnings = result.warnings
            yield CompleteEvent(trip=trip)
            return
        feedback = result.failures

    yield ErrorEvent(
        code="VALIDATION_FAILED",
        message="重新规划未能通过校验：" + "；".join(feedback),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_replanner.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/replanner.py backend/tests/test_replanner.py
git commit -m "feat(backend): Replanner——作用域分析/单天重生成/版本递增"
```

---

### Task 11: SSE 端点——POST /api/trips/generate

**Files:**
- Create: `backend/app/api/trips.py`
- Modify: `backend/app/main.py`（挂载 trips router）
- Test: `backend/tests/test_api_trips.py`

**Interfaces:**
- Consumes: Task 9 `generate_trip`、Task 3 `encode_event`/`GenerateRequest`、Task 1 `app`
- Produces:
  - `router`（`POST /trips/generate` → `StreamingResponse`，media_type=`text/event-stream`，headers：`Cache-Control: no-cache`、`X-Accel-Buffering: no`）
  - 依赖项 `get_glm() -> GLMService`、`get_amap() -> AMapService`（测试用 `app.dependency_overrides` 替换）
  - 未知异常兜底：`yield ErrorEvent(code="INTERNAL", ...)`，不让连接裸断

- [ ] **Step 1: 写失败测试**

`backend/tests/test_api_trips.py`：
```python
from collections.abc import AsyncIterator

import pytest

from app.api.trips import get_amap, get_glm
from app.main import app
from app.schemas.events import CompleteEvent, ErrorEvent, ProgressEvent, StreamEvent
from app.schemas.trip import Trip
from app.services.amap import AMapService
from app.services.glm import GLMService


class StubGLM(GLMService):
    pass


class StubAMap(AMapService):
    pass


def _install(events: list[StreamEvent]) -> None:
    async def fake_generate(req, glm=None, amap=None):
        for e in events:
            yield e

    import app.api.trips as trips_api

    trips_api.generate_trip = fake_generate
    app.dependency_overrides[get_glm] = lambda: StubGLM(api_key="x")
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()
    import app.api.trips as trips_api

    trips_api.generate_trip = __import__(
        "app.agent.planner", fromlist=["generate_trip"]
    ).generate_trip


async def test_generate_streams_sse_frames(client):
    _install(
        [
            ProgressEvent(stage="analyze", message="hi"),
            CompleteEvent(trip={"destination": "重庆"}),
        ]
    )
    resp = await client.post(
        "/api/trips/generate", json={"destination": "重庆", "days": 2}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    frames = [ln for ln in resp.text.split("\n\n") if ln]
    assert frames[0].startswith("data: ")
    assert '"type":"progress"' in frames[0]
    assert '"type":"complete"' in frames[-1]


async def test_generate_wraps_internal_error(client):
    async def boom(req, glm=None, amap=None):
        yield ProgressEvent(stage="analyze", message="start")
        raise RuntimeError("意外崩溃")

    import app.api.trips as trips_api

    trips_api.generate_trip = boom
    app.dependency_overrides[get_glm] = lambda: StubGLM(api_key="x")
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")

    resp = await client.post(
        "/api/trips/generate", json={"destination": "重庆", "days": 2}
    )
    assert resp.status_code == 200
    assert '"type":"error"' in resp.text
    assert '"code":"INTERNAL"' in resp.text


async def test_generate_validates_request(client):
    resp = await client.post("/api/trips/generate", json={"destination": "", "days": 0})
    assert resp.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_trips.py -v`
Expected: FAIL——`No module named 'app.api.trips'`

- [ ] **Step 3: 实现**

`backend/app/api/trips.py`：
```python
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.planner import generate_trip
from app.schemas.events import ErrorEvent, StreamEvent, encode_event
from app.schemas.generate import GenerateRequest
from app.services.amap import AMapService
from app.services.glm import GLMService

router = APIRouter(prefix="/trips", tags=["trips"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def get_glm() -> GLMService:
    return GLMService()


def get_amap() -> AMapService:
    return AMapService()


def _sse(events: AsyncIterator[StreamEvent]) -> AsyncIterator[str]:
    async def wrapper():
        try:
            async for ev in events:
                yield encode_event(ev)
        except Exception as e:  # noqa: BLE001 —— SSE 连接不能裸断
            yield encode_event(ErrorEvent(code="INTERNAL", message=f"服务内部错误：{e}"))

    return wrapper()


@router.post("/generate")
async def generate(
    req: GenerateRequest,
    glm: GLMService = Depends(get_glm),
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(generate_trip(req, glm=glm, amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
```

`backend/app/main.py` 追加（在 `include_router(health.router...)` 之后）：
```python
from app.api import health, trips  # 修改 import 行
    app.include_router(trips.router, prefix="/api")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_trips.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api_trips.py
git commit -m "feat(backend): POST /api/trips/generate SSE 流式端点"
```

---

### Task 12: SSE 端点——POST /api/trips/replan + 全量回归 + 冒烟

**Files:**
- Modify: `backend/app/api/trips.py`（追加 replan 端点）
- Test: `backend/tests/test_api_replan.py`
- Create: `backend/README.md`

**Interfaces:**
- Consumes: Task 10 `replan_trip`、Task 11 的 `_sse`/`SSE_HEADERS`/依赖项
- Produces:
  - `POST /trips/replan`（请求体 `ReplanRequest`，SSE 响应，语义同 generate）
  - `backend/README.md`（本地启动说明——密钥申请、venv、启动、curl 冒烟命令）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_api_replan.py`：
```python
import pytest

from app.api.trips import get_amap, get_glm
from app.main import app
from app.schemas.events import CompleteEvent
from app.schemas.trip import Trip
from app.services.amap import AMapService
from app.services.glm import GLMService


class StubGLM(GLMService):
    pass


class StubAMap(AMapService):
    pass


@pytest.fixture(autouse=True)
def _install():
    async def fake_replan(req, glm=None, amap=None):
        yield CompleteEvent(trip=req.trip.model_copy(update={"version": 2}))

    import app.api.trips as trips_api

    trips_api.replan_trip = fake_replan
    app.dependency_overrides[get_glm] = lambda: StubGLM(api_key="x")
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")
    yield
    app.dependency_overrides.clear()
    import app.agent.replanner

    trips_api.replan_trip = app.agent.replanner.replan_trip


async def test_replan_streams_complete(client):
    resp = await client.post(
        "/api/trips/replan",
        json={
            "trip": {"destination": "重庆", "days": [], "version": 1},
            "request": "别太赶",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type":"complete"' in resp.text
    assert '"version":2' in resp.text


async def test_replan_validates_body(client):
    resp = await client.post("/api/trips/replan", json={"request": ""})
    assert resp.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_replan.py -v`
Expected: FAIL——replan 端点尚未注册（404 断言失败），teardown 亦会报 `app.agent.replanner` 模块缺失

- [ ] **Step 3: 实现**

`backend/app/api/trips.py` 追加：
```python
from app.agent.replanner import replan_trip  # 加入文件头部 import
from app.schemas.replan import ReplanRequest


@router.post("/replan")
async def replan(
    req: ReplanRequest,
    glm: GLMService = Depends(get_glm),
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(replan_trip(req, glm=glm, amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
```

`backend/README.md`：
```markdown
# TravelMate 后端

FastAPI + 智谱 GLM + 高德 Web Service。详见 `../docs/superpowers/specs/2026-09-06-travel-assistant-design.md`。

## 本地启动

1. 申请密钥：GLM（open.bigmodel.cn）、高德 Web 服务 Key（console.amap.com，类型选「Web服务」）
2. `cp .env.example .env` 并填入两个 Key
3. `python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
4. `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000`

## 测试

`.venv/Scripts/python -m pytest -v`（全部离线，无真实外部调用）

## SSE 冒烟（配置好 Key 后）

curl -N -X POST http://localhost:8000/api/trips/generate \
  -H "Content-Type: application/json" \
  -d '{"destination":"重庆","days":2,"preferences":"带5岁孩子，不想太赶"}'
```

- [ ] **Step 4: 全量回归**

Run: `.venv/Scripts/python -m pytest -v`
Expected: 全部 passed（全套 56 项）

- [ ] **Step 5: 冒烟（可选，有 Key 时）+ Commit**

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000 &
sleep 3
curl -s http://localhost:8000/api/health
```
Expected: `{"status":"ok",...}`

```bash
git add backend/app/api backend/tests/test_api_replan.py backend/README.md
git commit -m "feat(backend): POST /api/trips/replan + 回归 + 冒烟文档"
```

---

## 任务依赖图

```
T1 骨架 ──▶ T4 高德 ──▶ T5 工具 ──▶ T7 校验器 ──▶ T9 Planner ──▶ T11 generate API ──▶ T12 replan API
   │           │                     ▲    ▲                            ▲
   └──▶ T2 Trip schema ──▶ T3 请求/事件 ┘    │                            │
                │                           └── T8 Prompts ──▶ T10 Replanner ┘
                └──▶ T6 GLM ──────────────────────┘
```

## 完成定义（对照 spec）

- spec §5.1 分层结构：api/agent/services/tools/schemas 全部落位 ✅（T1-T12）
- spec §5.2 API 契约：generate/replan SSE 事件序列一致 ✅（T11/T12）
- spec §5.3 生成 pipeline：analyze→enrich→validate→retry ✅（T9）
- spec §5.4 重规划 pipeline：scope→逐天重生成→enrich→validate→version+1 ✅（T10）
- spec §5.5 Validator 四条规则 ✅（T7）
- spec §3.1 坐标只来自高德、Key 只在服务端 ✅（T4/T6 + .env.example）
- spec §9 测试策略后端部分 ✅（各任务 Step 1）
