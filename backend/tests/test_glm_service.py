import httpx
import json
import pytest
import respx

from app.services.glm import GLMError, GLMService, ToolCall, extract_json

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


def _stream_body() -> str:
    return (
        'data: {"choices":[{"delta":{"reasoning_content":"用户想去重庆，"}}]}\n'
        'data: {"choices":[{"delta":{"reasoning_content":"节奏要放慢"}}]}\n'
        'data: {"choices":[{"delta":{"content":"{\\"title\\": "}}]}\n'
        'data: {"choices":[{"delta":{"content":"\\"重庆一日游\\"}"}}]}\n'
        "data: [DONE]\n\n"
    )


@respx.mock
async def test_chat_json_stream_forwards_thinking_and_parses_content():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, content=_stream_body().encode("utf-8"))
    )
    thoughts: list[str] = []
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    result = await svc.chat_json_stream("sys", "usr", on_thinking=thoughts.append)
    assert thoughts == ["用户想去重庆，", "节奏要放慢"]
    assert result == {"title": "重庆一日游"}


@respx.mock
async def test_chat_json_stream_http_error_raises():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    with pytest.raises(GLMError, match="500"):
        await svc.chat_json_stream("sys", "usr", on_thinking=lambda s: None)


@respx.mock
async def test_thinking_effort_controls_payload():
    captured: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}]}
        )

    respx.post(f"{BASE}/chat/completions").mock(side_effect=capture)

    await GLMService(api_key="k", thinking_effort="high", client=httpx.AsyncClient()).chat_json("s", "u")
    await GLMService(api_key="k", thinking_effort="low", client=httpx.AsyncClient()).chat_json("s", "u")

    assert captured[0]["thinking"] == {"type": "enabled", "effort": "high"}
    assert captured[1]["thinking"] == {"type": "enabled", "effort": "low"}


def _tools_stream_body() -> str:
    # tool_calls 的 arguments 分两个 delta 片段，验证按 index 拼接
    return (
        'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"需要定位地点"}}]}\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function",'
        '"function":{"name":"search_poi","arguments":"{\\"city\\": "}}]}}]}\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"杭州\\"}"}}]}}]}\n'
        'data: {"choices":[{"delta":{"content":""}}]}\n'
        'data: {"choices":[{"finish_reason":"tool_calls"}]}\n'
        "data: [DONE]\n\n"
    )


@respx.mock
async def test_chat_with_tools_assembles_tool_calls_and_thinking():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, content=_tools_stream_body().encode("utf-8"))
    )
    thoughts: list[str] = []
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    round = await svc.chat_with_tools(
        [{"role": "user", "content": "定位雷峰塔"}],
        tools=[{"type": "function", "function": {"name": "search_poi"}}],
        on_thinking=thoughts.append,
    )
    assert thoughts == ["需要定位地点"]
    assert round.content == ""
    assert round.tool_calls == [
        ToolCall(id="call_1", name="search_poi", arguments='{"city": "杭州"}')
    ]


@respx.mock
async def test_chat_with_tools_returns_content_when_no_tool_calls():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, content=_stream_body().encode("utf-8"))
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    round = await svc.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert round.tool_calls == []
    assert round.content == '{"title": "重庆一日游"}'


@respx.mock
async def test_chat_with_tools_http_error_raises():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    with pytest.raises(GLMError, match="500"):
        await svc.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])


@respx.mock
async def test_chat_with_tools_payload_contains_tools_json_mode_and_thinking():
    captured: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=_tools_stream_body().encode("utf-8"))

    respx.post(f"{BASE}/chat/completions").mock(side_effect=capture)
    svc = GLMService(api_key="k", thinking_effort="high", client=httpx.AsyncClient())
    await svc.chat_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search_poi"}}],
    )
    p = captured[0]
    assert p["tool_choice"] == "auto"
    assert p["response_format"] == {"type": "json_object"}
    assert p["thinking"] == {"type": "enabled", "effort": "high"}
    assert p["stream"] is True
    assert p["tools"][0]["function"]["name"] == "search_poi"


@respx.mock
async def test_effort_off_switches_fast_model_and_drops_thinking():
    """极速档：不带 thinking 字段，且切换到非思考快速模型。"""
    captured: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=_tools_stream_body().encode("utf-8"))

    respx.post(f"{BASE}/chat/completions").mock(side_effect=capture)
    svc = GLMService(api_key="k", thinking_effort="off", client=httpx.AsyncClient())
    await svc.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])
    p = captured[0]
    assert "thinking" not in p
    assert p["model"] == "glm-4-air"
