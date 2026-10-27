# 小焦 · 模板化生成的能力（2026-10-27，契约由载体写死、业务由模型填写）
"""小焦 · 自动生成的能力 · x

【需求】x
【怎么来的】`core/plugin_forge.py` 的模板优先路径：契约（类/两个方法/get_plugin）
  由载体按仓库规范写死，模型只负责填 `transform()` 的业务实现 ——
  这样"契约写错/漏「什么时候用」/工具名用中文"这类失败从源头上就不存在了。
"""


def transform(text):
    try:
        if not text:
            return "输入为空"
        # 假设输入是日期字符串，格式为 "YYYY-MM-DD"
        date_str = text.strip()
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        # 计算该日期是当年的第几天
        ordinal = dt.timetuple().tm_yday
        return f"该日期是当年的第 {ordinal} 天"
    except ValueError:
        return "日期格式错误，请使用 YYYY-MM-DD 格式"
    except Exception:
        return "发生未知错误"


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
