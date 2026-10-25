"""
搜索插件 - 示例
"""

import webbrowser
from urllib.parse import quote_plus


class SearchPlugin:
    """搜索插件"""
    
    def get_tool_descriptions(self):
        return [
            {"name": "web_search", "description": "上网搜资料(百度)。什么时候用：查新闻/百科/资料这类**网页信息**（问天气用 get_weather，问本机 IP 用 net_ip）；输入 query(只写内容关键词，别把「帮我搜」这类功能字放进去)；输出 搜索结果列表", "parameters": {"query": "搜索关键词"}}
        ]
    
    def execute(self, tool_name, params):
        if tool_name != "web_search":
            return f"搜索插件里没有「{tool_name}」这个工具（它只有 web_search）。"
        query = params.get("query", "")
        if not query:
            return "请告诉我你想搜索什么"
        url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
        webbrowser.open(url)
        return f"已打开百度搜索：{query}"