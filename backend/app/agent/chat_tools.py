import json

from app.services.amap import AMapError, AMapService
from app.tools.poi import search_poi

MAX_TOOL_CALLS = 15  # 高德个人 key 日配额有限（百次级），单次对话内硬上限


def build_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_poi",
                "description": "在高德地图搜索一个地点（POI），返回规范名称、地址、经纬度。定位地点时优先用它。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名，如 杭州"},
                        "keyword": {"type": "string", "description": "地点名称，尽量用官方规范名"},
                    },
                    "required": ["city", "keyword"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "geocode",
                "description": "把地址或区域名转换为经纬度（地理编码兜底）。search_poi 搜不到时再用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "地址或地名"},
                        "city": {"type": "string", "description": "城市名"},
                    },
                    "required": ["address"],
                },
            },
        },
    ]


class ToolExecutor:
    """执行模型发起的工具调用，结果以 JSON 字符串回传给模型。

    失败不抛异常——一切错误都编码为 {"error": ...} 让模型自行决策（换关键词/换工具/放弃）。
    city 参数统一用目的地归一化后的标准城市名（坪山→深圳市），避免无效城市导致全国模糊搜索。"""

    def __init__(self, destination: str, amap: AMapService, max_calls: int = MAX_TOOL_CALLS):
        self.destination = destination
        self.amap = amap
        self.remaining = max_calls
        self._city: str | None = None

    async def _resolved_city(self) -> str:
        if self._city is None:
            try:
                self._city = await self.amap.resolve_city(self.destination)
            except Exception:  # noqa: BLE001 —— 辅助步骤失败不能拖垮定位，退回原名
                self._city = self.destination
        return self._city

    async def execute(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return json.dumps({"error": "工具参数不是合法 JSON 对象"}, ensure_ascii=False)

        if name == "search_poi":
            if self.remaining <= 0:
                return json.dumps({"error": "定位次数已达上限，请基于已有信息完成回答"}, ensure_ascii=False)
            self.remaining -= 1
            loc = await search_poi(await self._resolved_city(), str(args.get("keyword", "")), self.amap)
            if loc is None:
                return json.dumps({"error": "未找到该地点，可尝试更换关键词或改用 geocode"}, ensure_ascii=False)
            return loc.model_dump_json(by_alias=True)

        if name == "geocode":
            if self.remaining <= 0:
                return json.dumps({"error": "定位次数已达上限，请基于已有信息完成回答"}, ensure_ascii=False)
            self.remaining -= 1
            try:
                coords = await self.amap.geocode(str(args.get("address", "")), await self._resolved_city())
            except AMapError:
                return json.dumps({"error": "地理编码服务暂时不可用"}, ensure_ascii=False)
            if coords is None:
                return json.dumps({"error": "未能解析该地址"}, ensure_ascii=False)
            return json.dumps({"longitude": coords[0], "latitude": coords[1]}, ensure_ascii=False)

        return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
