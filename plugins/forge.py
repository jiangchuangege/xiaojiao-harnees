# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 能力自增长入口（2026-10-17）

把 `core/plugin_forge.py` 的闭环暴露成一个工具 `forge_plugin`：
  说清"我想要一个能 XX 的能力" → 生成插件 → 静态检查 → 沙箱试跑 → 通过才落地到 `plugins/`。

【为什么它值得单独一个插件】用户的诉求是"越用越强"。别的 AI 加能力要靠厂商发版，
  这套东西加能力靠**自己写给自己**。但正因为它能长能力，闸门必须更硬：
  · 只写 `plugins/gen_*.py`（不碰 core/、不碰主程序）；
  · 危险调用/非白名单 import 一律判死（静态检查）；
  · 必须能在**子进程沙箱**里 import 并真调两个契约方法；
  · 只加不删：同名不覆盖。
  没过的插件不会落地 —— 宁可不加，也不往仓库里塞坏东西。

【落地之后是否立刻可用】**不会立刻可用**，需要重启或热注册。这一条在返回里写清楚，
  不假装"已经能用了"（这是本项目最容易犯的错：把"写进去了"说成"能用了"）。
"""
import logging

LOG = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "forge_plugin",
        "description": "你说要什么能力，它自己写插件补上。什么时候用：现有工具做不到的新能力；输入 need；输出 校验结果",
        "parameters": {
            "type": "object",
            "properties": {
                "need": {"type": "string", "description": "要什么能力，一句话说清（越具体越好）"},
                "dry_run": {"type": "boolean",
                            "description": "只跑检查不落地（想看它写得对不对时用）"},
            },
            "required": ["need"],
        },
    },
]


def _fmt(r):
    """把 forge 的结果转成用户能读的中文（成功/失败口径分开写，不混）。"""
    stage = str(r.get("stage") or "")
    if r.get("ok"):
        tools = "、".join(r.get("tools") or []) or "（未报工具名）"
        if stage == "dry-run":
            return ("✅ **检查全过（未落地）**\n\n"
                    "- 工具：%s\n- 模块名：`%s`\n\n"
                    "要真装上，把 dry_run 去掉再说一次。" % (tools, r.get("module")))
        return ("✅ **新能力已生成并落地**\n\n"
                "- 工具：%s\n- 文件：`%s`\n\n"
                "⚠️ **现在还不能用**：插件要**重启小焦**（或热注册）之后才会被扫描进工具表。"
                "重启后你可以直接说「用 %s …」来调它。"
                % (tools, r.get("path"), (r.get("tools") or ["它"])[0]))
    where = {"input": "需求没说清", "generate": "生成阶段", "static": "静态检查",
             "sandbox": "沙箱试跑", "write": "落地"}.get(stage, stage or "未知阶段")
    return ("❌ **这次没做成**（卡在：%s）\n\n原因：%s\n\n"
            "说明：没通过就不落地 —— 我不会把一个没验过的插件塞进你的仓库。"
            % (where, r.get("why") or "没说原因"))


class ForgePlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        if tool_name != "forge_plugin":
            return ("能力自增长插件里没有「%s」这个工具（它只有 forge_plugin）。" % tool_name)
        need = str(params.get("need") or "").strip()
        dry = bool(params.get("dry_run"))
        if not need:
            return "要给一句话说清想要什么能力（例如「把中文数字转成阿拉伯数字」）。"
        try:
            from core import plugin_forge as PF
            r = PF.forge(need, dry_run=dry)
            LOG.info("能力自增长：need=%r → ok=%s stage=%s",
                     need[:40], r.get("ok"), r.get("stage"))
            return _fmt(r)
        except Exception as e:      # noqa: silent-ok — 插件内部异常必须转成中文
            LOG.warning("能力自增长插件异常：%s: %s", type(e).__name__, e)
            return ("能力自增长这里出错了（%s: %s）。先确认本机模型服务在跑（端口 9292），"
                    "再试一次。" % (type(e).__name__, str(e)[:100]))


_PLUGIN = ForgePlugin()


def get_plugin():
    return _PLUGIN
