# 小焦 · 模板化生成的能力（2026-10-27，契约由载体写死、业务由模型填写）
"""小焦 · 自动生成的能力 · x

【需求】x
【怎么来的】`core/plugin_forge.py` 的模板优先路径：契约（类/两个方法/get_plugin）
  由载体按仓库规范写死，模型只负责填 `transform()` 的业务实现 ——
  这样"契约写错/漏「什么时候用」/工具名用中文"这类失败从源头上就不存在了。
"""


def transform(text):
    try:
        if not isinstance(text, str):
            text = str(text)
        if len(text) > 10000:
            return "输入文本过长，请缩短后重试"
        words = text.split()
        if not words:
            return "输入为空"
        result = []
        for word in words:
            if len(word) > 20:
                result.append(word[:10] + "..." + word[-10:])
            else:
                result.append(word)
        return " ".join(result)
    except Exception:
        return "处理过程中发生未知错误"


_TOOLS = [
    {
        "name": "gen_9dd4e461",
        "description": "x。什么时候用：x",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "参数 text"}
            },
            "required": ["text"],
        },
    },
]


class GenPlugin:
    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        try:
            if tool_name != "gen_9dd4e461":
                return "这个插件只有 gen_9dd4e461（x）。"
            return transform((params or {}).get("text"))
        except Exception as e:      # noqa: silent-ok — 插件异常一律转成中文
            return "执行时出错：%s" % str(e)[:100]


_PLUGIN = GenPlugin()


def get_plugin():
    return _PLUGIN
