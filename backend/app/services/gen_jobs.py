"""生成任务的后台运行与事件缓冲（修"刷新丢行程"）。

图运行与 SSE 连接解耦：任务在后台 asyncio 任务里跑完，事件缓存在 GenJob 中；
SSE 端点只是任务事件流的一个订阅者。客户端断线后凭 request_id 重连即可全量重放。"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.agent.generation_graph import generate_trip
from app.schemas.events import ErrorEvent, StreamEvent
from app.schemas.generate import GenerateRequest
from app.services.amap import AMapService
from app.services.glm import GLMService

MAX_JOBS = 30  # 内存任务注册表容量，超出淘汰最旧（单 worker，重启即清）


@dataclass
class GenJob:
    thread_id: str
    status: str = "running"  # running | done | error | cancelled
    events: list[StreamEvent] = field(default_factory=list)
    _subs: list[asyncio.Queue] = field(default_factory=list)
    _task: asyncio.Task | None = None

    def publish(self, ev: StreamEvent) -> None:
        self.events.append(ev)
        for q in list(self._subs):
            q.put_nowait(ev)

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        """订阅事件流：先全量重放缓冲（断线重连语义），再实时跟随至 complete/error。"""
        for ev in list(self.events):
            yield ev
        if self.status != "running":
            return
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append(q)
        try:
            while True:
                ev = await q.get()
                yield ev
                if ev.type in ("complete", "error"):
                    return
        finally:
            if q in self._subs:
                self._subs.remove(q)


class GenJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, GenJob] = {}

    def start(
        self, req: GenerateRequest, glm: GLMService, amap: AMapService
    ) -> GenJob:
        while len(self._jobs) >= MAX_JOBS:
            self._jobs.pop(next(iter(self._jobs)))
        thread_id = f"gen:{req.request_id or uuid.uuid4().hex}"
        job = GenJob(thread_id=thread_id)
        self._jobs[thread_id] = job
        job._task = asyncio.create_task(self._run(job, req, glm, amap))
        return job

    def get(self, request_id: str) -> GenJob | None:
        return self._jobs.get(f"gen:{request_id}")

    def cancel(self, request_id: str) -> bool:
        job = self.get(request_id)
        if job is None:
            return False
        if job._task is not None and not job._task.done():
            job._task.cancel()
        job.status = "cancelled"
        job.publish(ErrorEvent(code="CANCELLED", message="已取消生成"))
        return True

    async def _run(
        self, job: GenJob, req: GenerateRequest, glm: GLMService, amap: AMapService
    ) -> None:
        try:
            # 检查点不启用：内存事件缓冲即重连通道；多任务并发写同一 sqlite 会锁冲突
            async for ev in generate_trip(req, glm=glm, amap=amap):
                job.publish(ev)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 —— 任务内意外错误统一转 error 事件
            job.publish(ErrorEvent(code="INTERNAL", message=f"生成失败：{e}"))
        last = job.events[-1] if job.events else None
        job.status = "done" if last is not None and last.type == "complete" else "error"


gen_jobs = GenJobManager()
