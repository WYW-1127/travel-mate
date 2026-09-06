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
