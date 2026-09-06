import json
import re
from collections.abc import Callable

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
        thinking_effort: str | None = None,
    ):
        s = get_settings()
        self._api_key = api_key or s.glm_api_key
        self._model = model or s.glm_model
        self._base_url = (base_url or s.glm_base_url).rstrip("/")
        self._thinking_effort = (
            s.glm_thinking_effort if thinking_effort is None else thinking_effort
        )
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
        # glm-5.3 系始终思考，effort 控制思考深度（low=快速，high=深度）
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
