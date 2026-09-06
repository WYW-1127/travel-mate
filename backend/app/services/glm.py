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
