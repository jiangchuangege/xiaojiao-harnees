# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 任务级入口（2026-10-28）

三个工具，让人能把"一件复杂的事"交给它，并且**随时能查它做到哪了**：
  · `task_start`  —— 给目标，它自己拆解、执行、验收（后台跑，长任务不阻塞）
  · `task_status` —— 查某个任务的每步结果与验收结论（哪步没做成会写清原因）
  · `task_list`   —— 看最近开过哪些任务、各自什么状态

【为什么必须能查状态】多步任务跑起来是几秒到几分钟。不能查状态的话，
用户只能干等、或者以为它死了。而"每步的验收结论"是关键：竞品普遍只报"完成/失败"，
这里连"第 2 步没把握"都写出来 —— 这才是可核查。
"""
import logging

LOG = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "task_start",
        "description": "给一个目标，它自己拆步骤并做完（后台跑）。什么时候用：一件事要好几步；输入 goal；输出 任务号",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "要做成什么，例如 把某站的书目抓下来存到 G:\\dzs"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "task_status",
        "description": "查任务做到哪了、每步结果和验收结论。什么时候用：开了长任务要跟进；输入 task_id；输出 进度与每步详情",
        "parameters": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "task_start 返回的任务号"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_list",
        "description": "看最近开过哪些任务。什么时候用：忘了任务号；输入 limit；输出 任务清单",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "列几条（默认 8，上限 20）"}},
            "required": [],
        },
    },
]

_STATE_ZH = {"planning": "规划中", "running": "执行中", "done": "完成",
             "failed": "失败", "pending": "待做"}


def _fmt_status(st):
    if not st:
        return "没有这个任务（任务号可能写错了，用 task_list 看看）。"
    head = "📋 **任务 %s** ｜ %s ｜ 进度 %s ｜ %s 拆解" % (
        st["id"], _STATE_ZH.get(st["state"], st["state"]), st["progress"], st["plan_from"])
    lines = [head, "", "目标：%s" % st["goal"], ""]
    for s in st["steps"]:
        mark = "✅" if s["state"] == "done" else ("❌" if s["state"] == "failed" else "⏳")
        v = ""
        if s.get("verify_ok") is True:
            v = "（验收过：%s）" % (s.get("verify_note") or "")
        elif s.get("verify_ok") is False:
            v = "（验收没把握：%s）" % (s.get("verify_note") or "")
        used = ("→ %s" % s["used"]) if s.get("used") and s["used"] != s["tool"] else ""
        lines.append("%s 第 %d 步 `%s`%s %s" % (mark, s["i"], s["tool"], used, v))
        if s.get("result_head"):
            lines.append("   结果：%s" % s["result_head"])
        if s.get("note"):
            lines.append("   说明：%s" % s["note"])
    if st.get("why"):
        lines += ["", "⚠️ 卡在这：%s" % st["why"]]
    if st.get("warnings"):
        lines += ["", "🟡 没把握的地方："] + ["- %s" % w for w in st["warnings"]]
    if st["state"] == "done":
        lines += ["", "（说「接着做」会把没做完的补上；这条路径已固化进技能库，下次同类目标可直接照抄。）"]
    lines += ["", "—— 说明：只有每步验收都通过才算「完成」；有一项没把握会标出来，不会说成完成。"]
    return "\n".join(lines)


def _fmt_list(rows):
    if not rows:
        return "还没有任务。给个目标试试：`task_start` 说清要做成什么。"
    lines = ["📋 **最近的任务（%d 条）**" % len(rows), ""]
    for r in rows:
        lines.append("- `%s` ｜ %s ｜ %s/%s 步 ｜ %s" % (
            r["id"], _STATE_ZH.get(r["state"], r["state"]),
            r["done_steps"], r["steps"], str(r.get("goal") or "")[:40]))
    return "\n".join(lines)


class TaskPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        try:
            from core import task_runner as TR
            if tool_name == "task_start":
                goal = str(params.get("goal") or "").strip()
                tid, msg = TR.start(goal, background=True)
                if not tid:
                    return "没开成：%s" % msg
                return ("🚀 **任务已开**（`%s`）\n\n%s\n\n"
                        "它会自己一步步做；想看做到哪了就说「查一下任务 %s」。"
                        % (tid, msg, tid))
            if tool_name == "task_status":
                tid = str(params.get("task_id") or "").strip()
                if not tid:
                    return "要给任务号（task_start 返回的那个）。"
                return _fmt_status(TR.status(tid))
            if tool_name == "task_list":
                try:
                    limit = int(params.get("limit") or 8)
                except Exception:
                    limit = 8
                return _fmt_list(TR.list_tasks(limit=max(1, min(limit, 20))))
            return ("任务插件里没有「%s」这个工具（它只有 task_start、task_status、task_list）。"
                    % tool_name)
        except Exception as e:      # noqa: silent-ok — 插件内部异常必须转成中文
            LOG.warning("任务插件异常：%s: %s", type(e).__name__, e)
            return "任务这里出错了（%s: %s）。先说清要做成什么再试一次。" \
                   % (type(e).__name__, str(e)[:100])


_PLUGIN = TaskPlugin()


def get_plugin():
    return _PLUGIN
