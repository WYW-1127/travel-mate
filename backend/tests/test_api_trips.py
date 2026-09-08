import json

import httpx
import pytest
import respx

from app.api.trips import get_amap
from app.main import app
from app.schemas.events import CompleteEvent, ProgressEvent
from app.services.amap import AMapService, PoiResult

JOBS = "app.services.gen_jobs.gen_jobs"


class StubAMap(AMapService):
    pass


class FakeJob:
    """假任务：subscribe 重放 events。"""

    def __init__(self, events):
        self.events = events
        self.status = "done"

    async def subscribe(self):
        for e in self.events:
            yield e


@pytest.fixture(autouse=True)
def _restore():
    yield
    import app.services.gen_jobs as jobs_mod
    import app.api.trips as trips_api

    trips_api.gen_jobs = jobs_mod.gen_jobs
    app.dependency_overrides.clear()


def _install_fake_jobs(monkeypatch, fake):
    import app.api.trips as trips_api

    monkeypatch.setattr(trips_api, "gen_jobs", fake)


async def test_generate_streams_sse_frames(client, monkeypatch):
    class FakeManager:
        def start(self, req, glm=None, amap=None):
            return FakeJob([ProgressEvent(stage="analyze", message="hi"),
                            CompleteEvent(trip={"destination": "重庆"})])

    _install_fake_jobs(monkeypatch, FakeManager())
    app.dependency_overrides[get_amap] = lambda: StubAMap(key="x")

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


async def test_generate_wraps_internal_error(client, monkeypatch):
    class BoomJob:
        async def subscribe(self):
            raise RuntimeError("意外崩溃")
            yield

    class FakeManager:
        def start(self, req, glm=None, amap=None):
            return BoomJob()

    _install_fake_jobs(monkeypatch, FakeManager())
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


async def test_generate_respects_request_thinking_effort(client, monkeypatch, tmp_path):
    """防回归：请求级 thinking 必须生效（曾被 get_glm 单例依赖掩盖）。"""
    import app.core.config as config_mod

    monkeypatch.setenv("GLM_API_KEY", "test-key")
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "ckpt.db"))  # 测试不污染生产检查点库
    config_mod.get_settings.cache_clear()

    captured: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        draft = {
            "title": "t",
            "days": [
                {
                    "title": "d1",
                    "activities": [
                        {"name": "x", "type": "attraction", "startTime": "09:00", "endTime": "10:00", "cost": 0,
                         "location": {"name": "x", "resolved": True, "longitude": 106.5, "latitude": 29.5}}
                    ],
                }
            ],
        }
        frame = json.dumps(
            {"choices": [{"delta": {"content": json.dumps(draft, ensure_ascii=False)}}]}
        )
        body = "data: " + frame + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=body.encode("utf-8"))

    with respx.mock:
        respx.post("https://open.bigmodel.cn/api/paas/v4/chat/completions").mock(side_effect=capture)

        class LocalAMap(StubAMap):
            async def search_poi(self, city, keyword):
                return PoiResult(name=keyword, address="", longitude=106.5, latitude=29.5, poi_id="P")

        app.dependency_overrides[get_amap] = lambda: LocalAMap(key="x")
        resp = await client.post(
            "/api/trips/generate", json={"destination": "重庆", "days": 1, "thinking_effort": "low"}
        )
        assert resp.status_code == 200
        assert '"type":"complete"' in resp.text
        assert captured[0]["thinking"] == {"type": "enabled", "effort": "low"}

        resp2 = await client.post(
            "/api/trips/generate", json={"destination": "重庆", "days": 1, "thinking_effort": "high"}
        )
        assert captured[-1]["thinking"] == {"type": "enabled", "effort": "high"}
        assert '"type":"complete"' in resp2.text
    config_mod.get_settings.cache_clear()


async def test_gen_job_replay_streams_complete(client, monkeypatch):
    class FakeManager:
        def get(self, rid):
            if rid == "rid-1":
                return FakeJob([CompleteEvent(trip={"destination": "重庆", "version": 2})])
            return None

    _install_fake_jobs(monkeypatch, FakeManager())
    resp = await client.post("/api/trips/gen-jobs/rid-1/replay")
    assert resp.status_code == 200
    assert '"type":"complete"' in resp.text
    assert '"version":2' in resp.text


async def test_gen_job_replay_unknown_returns_404(client, monkeypatch):
    class FakeManager:
        def get(self, rid):
            return None

    _install_fake_jobs(monkeypatch, FakeManager())
    resp = await client.post("/api/trips/gen-jobs/nope/replay")
    assert resp.status_code == 404


async def test_gen_job_cancel_is_idempotent(client, monkeypatch):
    cancelled = []

    class FakeManager:
        def cancel(self, rid):
            cancelled.append(rid)
            return True

    _install_fake_jobs(monkeypatch, FakeManager())
    resp = await client.post("/api/trips/gen-jobs/rid-1/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert cancelled == ["rid-1"]
