# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 自进化入口（2026-10-27）

两个工具：
  · `evolve_report`   —— 读出"哪里弱、为什么、下一步改什么"（诊断，不改代码）
  · `experience_stats`—— 它自己踩过哪些坑、成功了多少次（经验库快照）

【为什么值得做成工具而不是只留在命令行】
  用户的问题是"它到底哪儿不行、下一步干嘛"，这句话必须能在**对话里**直接问出来。
  做成工具之后，说一句「现在哪里最弱」就能拿到按影响面排序的清单，
  而不是让人去翻 docs/ 里的两份 markdown。

【边界】`evolve_report` 只诊断、**不自动改源码**。唯一可自动的是「缺能力」那一类，
  由 `forge_plugin` 带静态检查 + 沙箱两道闸去落地 —— 诊断和执行分开放，才敢让它跑。
"""
import logging

LOG = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "evolve_report",
        "description": "看它现在最弱的是哪几处、下一步该改什么。什么时候用：想知道短板/怎么变强；输入 limit；输出 改进清单",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "列几项（默认 8，上限 20）"},
            },
            "required": [],
        },
    },
    {
        "name": "experience_stats",
        "description": "看它踩过哪些坑、能力自增长成功了多少次。什么时候用：想知道它学过什么；输入 无；输出 统计",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def _fmt_stats(st):
    lines = ["📚 **经验库**（它自己踩过的坑，落盘可查）", "",
             "- 记录：%d 条 ｜ 成功：%d 条 ｜ 成功率：%s"
             % (st.get("total", 0), st.get("ok", 0),
                ("%s%%" % st["rate"]) if st.get("rate") is not None else "还没有数据"),
             "- 文件：`%s`" % st.get("path", "")]
    by = st.get("by_kind") or {}
    if by:
        lines.append("- 分类：")
        for k, v in sorted(by.items()):
            lines.append("  - %s：%d 条（成功 %d）" % (k, v.get("n", 0), v.get("ok", 0)))
    else:
        lines.append("- 分类：（还空着 —— 做过一次能力自增长就会有记录）")
    return "\n".join(lines)


class EvolvePlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        try:
            if tool_name == "evolve_report":
                try:
                    limit = int(params.get("limit") or 8)
                except Exception:
                    limit = 8
                limit = max(1, min(limit, 20))
                from core import self_evolve as SE
                return SE.report(limit=limit)
            if tool_name == "experience_stats":
                from core import experience as EXP
                return _fmt_stats(EXP.stats())
            return ("自进化插件里没有「%s」这个工具（它只有 evolve_report、experience_stats）。"
                    % tool_name)
        except Exception as e:      # noqa: silent-ok — 插件内部异常必须转成中文
            LOG.warning("自进化插件异常：%s: %s", type(e).__name__, e)
            return ("自进化诊断这里出错了（%s: %s）。先确认 docs/ 下有评测和体检报告"
                    "（跑 `python tools/eval_xiaojiao.py --save`、"
                    "`python tools/health_capability.py --save` 各一次）。"
                    % (type(e).__name__, str(e)[:100]))


_PLUGIN = EvolvePlugin()


def get_plugin():
    return _PLUGIN
