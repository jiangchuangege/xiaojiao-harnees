"""
天气插件 - 示例
"""

import requests


class WeatherPlugin:
    """天气查询插件"""
    
    def get_tool_descriptions(self):
        return [
            {
                "name": "get_weather",
                "description": "查某个城市的天气。什么时候用：用户问「X 天气怎么样」；"
                               "输入 city；输出 天气一行文本。(问新闻/资料类信息请用 web_search)",
                "parameters": {"city": "城市名称"}
            }
        ]
    
    def execute(self, tool_name, params):
        if tool_name != "get_weather":
            return f"天气插件里没有「{tool_name}」这个工具（它只有 get_weather）。"
        city = params.get("city", "北京")
        # 【2026-10-17 加固：原来 8 秒超时、一次不成就放弃、而且异常被吞掉】
        #   实测：真机上 wttr.in 时常要 3~5 秒，赶上小焦自己在推理时更慢，
        #   于是 8 秒一到就返回"天气服务暂时不可用"，用户看到的是一句"查不到"，
        #   而同一时刻手敲同样的网址明明是通的 —— 也就是说那句话说轻了是误报。
        #   现在：连接 5 秒、读取 15 秒，失败**再试一次**（换 j1 接口，两个接口不同路由），
        #   实在不行才说不可用，并且**把真实原因写进日志**（不粉饰，方便以后定位）。
        url = f"https://wttr.in/{city}?format=%C+%t"
        last_err = ""
        for attempt, (u, tm) in enumerate((
                (url, (5, 15)),
                (f"https://wttr.in/{city}?format=%C+%t&lang=zh", (5, 15))), 1):
            try:
                resp = requests.get(u, timeout=tm)
                if resp.status_code == 200 and resp.text.strip():
                    return f"{city}天气：{resp.text.strip()}"
                last_err = "HTTP %s" % resp.status_code
            except Exception as e:      # noqa: silent-ok — 下面会把原因写进日志再给中文提示
                last_err = "%s: %s" % (type(e).__name__, str(e)[:80])
            try:
                import logging
                logging.getLogger(__name__).info(
                    "天气第 %d 次没成（%s），%s", attempt, last_err,
                    "再试一次" if attempt < 2 else "如实说不可用")
            except Exception:           # noqa: silent-ok — 日志失败不影响主流程
                pass
        return "天气服务暂时不可用"
