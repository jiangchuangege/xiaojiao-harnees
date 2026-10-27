# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 自动生成的能力 · 中文数字转阿拉伯数字（2026-10-27 由 forge 闭环生成）

【来历】用户说「把中文数字转成阿拉伯数字」→ 小焦自己写、自己验、自己落地。
  生成的初版有两个毛病，都被下游检查抓出来并修掉了：
    ① 工具名用了中文（`中文数字转阿拉伯数字`）→ 契约自测不通过（工具名要能被准确调用）；
    ② 载体补「什么时候用」的正则过宽，把参数说明也补了一遍 → 读起来是噪声。
  现在工具名是 `cn_num_to_int`，说明只在工具级，参数说明干净。
  转换逻辑本身也重写过：原版把「三千零二十」算成 3020 是巧合正确，
  遇到「一百零五」「两千一百」就错了（它把每个字当数字按十进制拼），
  所以这里按"单位位值"重算，并支持「两」。
"""
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(text):
    """把中文数字转成整数。支持「零/〇/两」、十/百/千/万/亿。返回 (数字 或 None, 原因)。"""
    s = str(text or "").strip()
    if not s:
        return None, "没给要转换的文字"
    s = s.replace("负", "-").replace("点", ".") if ("点" in s) else s
    # 小数：按「点」切开分别转
    if "." in s:
        head, _, tail = s.partition(".")
        hi, why = _cn_to_int(head)
        if hi is None:
            return None, why
        decimals = ""
        for ch in tail:
            if ch not in _DIGITS:
                return None, "小数位里有不认识的字：%s" % ch
            decimals += str(_DIGITS[ch])
        return float("%d.%s" % (hi, decimals or "0")), ""
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _DIGITS:
            num = _DIGITS[ch]
        elif ch in _UNITS:
            u = _UNITS[ch]
            if u >= 10000:
                section = (section + num) * u
                total += section
                section, num = 0, 0
            else:
                if num == 0 and u == 10:
                    num = 1                       # 「十五」= 15
                section += (num or 1) * u
                num = 0
        else:
            return None, "有不认识的字：%s（只支持中文数字）" % ch
    result = total + section + num
    return (-result if neg else result), ""


_TOOLS = [
    {
        "name": "cn_num_to_int",
        "description": "把中文数字（一百零五、两千三百、十五）转成阿拉伯数字。"
                       "什么时候用：文本里的中文数字要参与计算；输入 text；输出 数字",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "中文数字，例如 三千零二十"},
            },
            "required": ["text"],
        },
    },
]


class CnNumberPlugin:
    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        try:
            if tool_name != "cn_num_to_int":
                return "这个插件只有 cn_num_to_int（把中文数字转成阿拉伯数字）。"
            val, why = _cn_to_int((params or {}).get("text"))
            if val is None:
                return "转换失败：%s" % why
            return "%s = %s" % (str((params or {}).get("text")).strip(), val)
        except Exception as e:      # noqa: silent-ok — 插件异常一律转成中文
            return "转换时出错：%s" % str(e)[:100]


_PLUGIN = CnNumberPlugin()


def get_plugin():
    return _PLUGIN
