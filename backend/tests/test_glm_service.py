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
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


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
