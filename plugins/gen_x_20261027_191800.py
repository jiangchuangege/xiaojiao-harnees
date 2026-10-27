# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 自动生成的能力 · 整数转中文数字（2026-10-27 由 forge 闭环生成后校正）

【来历，如实记】这是自增长生成的第二份插件。初版有两个真问题，都在下游被抓住：
  ① **工具名和已有插件撞车**（声明了 `cn_num_to_int` —— 那是另一份插件的名字）→
     调用会被别人的插件接住，报"这里没有这个工具"；
  ② **execute 里分派的名字和声明的名字不一致**，即使不撞名也调不通。
  修法：能力改成互补方向（整数 → 中文数字），工具名取 `int_to_cn_num`；
  并给 `core/plugin_forge.py` 加了**落地前的撞名检查**，同类问题不再长出来。
"""
_DIGITS = "零一二三四五六七八九"
_UNITS4 = ("", "十", "百", "千")


def _section(n):
    """0 < n < 10000 的一段：处理「零」的省略与「十」的习惯写法。"""
    out, zero_pending = "", False
    s = str(int(n)).zfill(4)
    for i, ch in enumerate(s):
        d = int(ch)
        unit = _UNITS4[3 - i]
        if d == 0:
            zero_pending = bool(out)
            continue
        if zero_pending:
            out += "零"
            zero_pending = False
        out += _DIGITS[d] + unit
    return out


def _int_to_cn(n):
    """整数转中文数字（到亿级；负数加「负」）。"""
    n = int(n)
    if n == 0:
        return "零"
    neg = n < 0
    n = abs(n)
    parts = []
    for unit, base in (("亿", 100000000), ("万", 10000)):
        if n >= base:
            q, n = divmod(n, base)
            parts.append(_int_to_cn(q) + unit)
            if 0 < n < base // 10:
                parts.append("零")
    if n:
        parts.append(_section(n) if n >= 100 else _section(n).lstrip("零"))
    s = "".join(parts)
    if s.startswith("一十"):
        s = s[1:]
    return ("负" if neg else "") + s


_TOOLS = [
    {
        "name": "int_to_cn_num",
        "description": "把阿拉伯数字（3020、105）转成中文数字（三千零二十）。"
                       "什么时候用：要按中文习惯念数字；输入 text；输出 中文数字",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "阿拉伯数字，例如 3020"},
            },
            "required": ["text"],
        },
    },
]


class IntToCnPlugin:
    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        try:
            if tool_name != "int_to_cn_num":
                return "这个插件只有 int_to_cn_num（把阿拉伯数字转成中文数字）。"
            raw = str((params or {}).get("text") or "").strip().replace(",", "")
            if not raw:
                return "没给要转换的数字"
            try:
                n = int(raw)
            except Exception:
                return "请给纯阿拉伯数字（例如 3020），收到的是：%s" % raw[:20]
            return "%s = %s" % (raw, _int_to_cn(n))
        except Exception as e:      # noqa: silent-ok — 插件异常一律转成中文
            return "转换时出错：%s" % str(e)[:100]


_PLUGIN = IntToCnPlugin()


def get_plugin():
    return _PLUGIN
