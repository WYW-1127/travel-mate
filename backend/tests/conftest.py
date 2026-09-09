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


@pytest.fixture(autouse=True)
def _clear_poi_cache(monkeypatch):
    from app.tools import poi as poi_mod

    # 禁落盘：测试的 POI 缓存不写生产库（trip/POI 缓存均以 "" 表示禁用）
    monkeypatch.setattr(poi_mod, "_cache_db_path", "")
    poi_mod.clear_cache()
    yield
    poi_mod.clear_cache()


@pytest.fixture(autouse=True)
def _trip_cache_disabled(monkeypatch):
    """测试禁用行程缓存（不读也不写生产库），避免污染/命中历史生成。"""
    from app.services import trip_cache as tc

    monkeypatch.setattr(tc, "_db_path", "")
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
