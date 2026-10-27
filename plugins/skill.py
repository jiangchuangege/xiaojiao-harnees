# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 技能库入口（2026-10-27）

两个工具，让人能看见「它到底学到了什么」：
  · `skill_list`   —— 最近固化下来的技能（同类问题只留最近一条）
  · `skill_recall` —— 问一句"这类事它以前怎么做的"，返回当时的工具序列

【为什么值得做成工具】技能库如果只在后台默默积累，用户永远不知道它学到了什么、
学得对不对。做成工具之后，一句「你都会哪些成套的本事」就能看到清单；
问「上次爬书你是怎么做的」就能看到那条工具序列 —— 可核查，才敢信。
"""
import logging

LOG = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "skill_list",
        "description": "看它固化了哪些成套做法（多步任务的工具序列）。什么时候用：想知道它学会了什么；输入 limit；输出 技能清单",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer",
                                     "description": "列几条（默认 8，上限 20）"}},
            "required": [],
        },
    },
    {
        "name": "skill_recall",
        "description": "问「这类事以前怎么做的」，返回当时的工具序列。什么时候用：想复用或核验旧路径；输入 question；输出 序列与耗时",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string",
                                        "description": "要查的那类问题，例如 帮我查下菏泽天气"}},
            "required": ["question"],
        },
    },
]


def _fmt_list(rows):
    if not rows:
        return ("📚 技能库还空着。\n\n"
                "说明：只有**用了 2 个以上工具、且没有失败痕迹**的任务才会被固化；"
                "单工具调用不算技能。以后做成一次多步任务，这里就会长出一条。")
    lines = ["📚 **它固化下来的做法（%d 条）**" % len(rows), ""]
    for i, r in enumerate(rows, 1):
        seq = " → ".join(x.get("tool") or "?" for x in (r.get("steps") or []))
        lines.append("%d. **%s**" % (i, str(r.get("question") or "")[:44]))
        lines.append("   序列：%s（%s 步，%.1f 秒）"
                     % (seq, r.get("n_steps"), float(r.get("sec") or 0)))
        if r.get("answer_head"):
            lines.append("   结果要点：%s" % str(r.get("answer_head"))[:80])
    return "\n".join(lines)


def _fmt_one(q, row):
    if not row:
        return ("没查到同类技能：`%s`。\n\n说明：判据是「2 字词覆盖率 ≥0.5」，"
                "宁可召不回也不拿错技能去套 —— 套错的代价比重新试错大。" % str(q)[:40])
    seq = " → ".join(x.get("tool") or "?" for x in (row.get("steps") or []))
    lines = ["🔁 **同类问题的旧做法**（相似度 %.2f）" % float(row.get("score") or 0), "",
             "- 当时问的是：%s" % str(row.get("question") or "")[:60],
             "- 工具序列：`%s`" % seq,
             "- 步数 / 耗时：%s 步 ｜ %.1f 秒" % (row.get("n_steps"), float(row.get("sec") or 0)),
             "- 固化时间：%s" % row.get("at")]
    if row.get("answer_head"):
        lines.append("- 当时的结果：%s" % str(row.get("answer_head"))[:100])
    lines += ["", "（这条可以照着做；如果发现它错了，直接说「这样不对」——我会重新试一遍。）"]
    return "\n".join(lines)


class SkillPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        try:
            from core import skill_memory as SK
            if tool_name == "skill_list":
                try:
                    limit = int(params.get("limit") or 8)
                except Exception:
                    limit = 8
                return _fmt_list(SK.list_skills(limit=max(1, min(limit, 20))))
            if tool_name == "skill_recall":
                q = str(params.get("question") or "").strip()
                if not q:
                    return "要给一个问句，例如「上次查天气你是怎么做的」。"
                return _fmt_one(q, SK.recall(q))
            return ("技能库插件里没有「%s」这个工具（它只有 skill_list、skill_recall）。"
                    % tool_name)
        except Exception as e:      # noqa: silent-ok — 插件内部异常必须转成中文
            LOG.warning("技能库插件异常：%s: %s", type(e).__name__, e)
            return "技能库这里出错了（%s: %s）。先做一次成功的多步任务再看。" \
                   % (type(e).__name__, str(e)[:80])


_PLUGIN = SkillPlugin()


def get_plugin():
    return _PLUGIN
