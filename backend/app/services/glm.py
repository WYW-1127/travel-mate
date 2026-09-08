import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


class GLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # 原样 JSON 字符串，由调用方解析


@dataclass
class ToolRound:
    """工具模式一轮响应：模型要么发起 tool_calls，要么给出最终 content。"""

    content: str
    tool_calls: list[ToolCall]
    reasoning: str = ""


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
        thinking_effort: str | None = None,
    ):
        s = get_settings()
        self._api_key = api_key or s.glm_api_key
        self._base_url = (base_url or s.glm_base_url).rstrip("/")
        self._thinking_effort = (
            s.glm_thinking_effort if thinking_effort is None else thinking_effort
        )
        # 极速档：glm-5.3 系无法关闭思考（1210），off = 切换到非思考快速模型
        if self._thinking_effort == "off":
            self._model = model or s.glm_fast_model
        else:
            self._model = model or s.glm_model
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _payload(self, system: str, user: str, temperature: float, stream: bool) -> dict:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": stream,
        }
        # glm-5.3 系始终思考，effort 控制思考深度（low=快速，high=深度）；
        # off=极速档（非思考模型），不发送 thinking 字段
        if self._thinking_effort != "off":
            payload["thinking"] = {"type": "enabled", "effort": self._thinking_effort}
        return payload

    async def chat_json(self, system: str, user: str, temperature: float = 0.3) -> dict:
        if not self._api_key:
            raise GLMError("GLM_API_KEY 未配置（见 backend/.env.example）")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=self._payload(system, user, temperature, stream=False),
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if resp.status_code != 200:
            raise GLMError(f"GLM HTTP {resp.status_code}: {resp.text[:200]}")
        content = resp.json()["choices"][0]["message"]["content"]
        return extract_json(content)

    async def chat_json_stream(
        self,
        system: str,
        user: str,
        on_thinking: Callable[[str], None],
        temperature: float = 0.3,
    ) -> dict:
        """流式调用：推理增量实时回调 on_thinking，结束后解析最终 JSON 内容。"""
        if not self._api_key:
            raise GLMError("GLM_API_KEY 未配置（见 backend/.env.example）")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=self._payload(system, user, temperature, stream=True),
            headers={"Authorization": f"Bearer {self._api_key}"},
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise GLMError(f"GLM HTTP {resp.status_code}: {body[:200]}")

            content_parts: list[str] = []
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    on_thinking(reasoning)
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
        return extract_json("".join(content_parts))

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        on_thinking: Callable[[str], None] | None = None,
        temperature: float = 0.3,
    ) -> ToolRound:
        """工具模式流式调用。messages 为完整消息历史（含 system/assistant/tool 角色），由调用方维护。

        reasoning 增量经 on_thinking 回调；tool_calls 分片按 index 聚合。"""
        if not self._api_key:
            raise GLMError("GLM_API_KEY 未配置（见 backend/.env.example）")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=180.0)
        payload = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": True,
        }
        # glm-5.3 系始终思考（effort low/high）；off=极速档（非思考模型）不发 thinking
        if self._thinking_effort != "off":
            payload["thinking"] = {"type": "enabled", "effort": self._thinking_effort}
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise GLMError(f"GLM HTTP {resp.status_code}: {body[:200]}")

            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            calls: dict[int, dict] = {}
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning_parts.append(delta["reasoning_content"])
                    if on_thinking:
                        on_thinking(delta["reasoning_content"])
                if delta.get("content"):
                    content_parts.append(delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

            tool_calls = [
                ToolCall(id=s["id"], name=s["name"], arguments=s["arguments"])
                for _, s in sorted(calls.items())
            ]
            return ToolRound(
                content="".join(content_parts),
                tool_calls=tool_calls,
                reasoning="".join(reasoning_parts),
            )
