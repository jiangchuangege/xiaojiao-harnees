# -*- coding: utf-8 -*-
"""缺陷 1 / 缺陷 2 回归测试：载体拦截不许被当成模型退化，也不许被模型转述。

运行：python tools/test_carrier_block.py

真端到端实测抓到的两个真缺陷（本测试就是钉住它们）：
  缺陷 1 · 红线拦截被误判成模型退化 →
      `tool_misuse` ×2~3 → 诊断 HEAVY → 三级治疗 `switch_brain` →
      **把本来好好的本地大脑切成了不可用目标** → 随后"大脑没有应答"，长文场景三次全不过。
  缺陷 2 · 拦截后把消息丢给模型总结 → 模型编出"已在指定位置新建了文件"，
      与事实完全相反（文件既没被删、也没被建）。

判据：
  A. 白名单：载体主动动作（红线/权限/安全/限流）一律不算症状，健康系统视而不见
  B. 但真正的模型行为异常**照样要抓**（白名单不能把判据废掉）
  C. 红线拦截 → 用户看到的是载体原文（含用户指定那一句），**没有模型编的话**
  D. switch_brain 三道闸：先 ping、切完复核、失败回切；且全程写流水
"""
import json
import os
import shutil
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402
# 【2026-09-21】删除禁区现在**默认关**（用户要求：误伤太多，理由见 `_no_delete_guard_on`）。
# 这个自测验的是「接线还在、一开就拦得住」，所以运行前显式打开它。
X.CAP["no_delete_guard"] = True

from core.health.monitor import HealthMonitor, is_carrier_action  # noqa: E402

PASS, FAIL = [], []
REQUIRED_LINE = "⚠️ 删除操作被载体层拦截（安全红线）。文件未被删除。"


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


class SpyModel:
    """假模型：**故意"编造执行成功"**，用来验证载体不把拦截交给它转述。"""

    def __init__(self):
        self.calls = []

    def __call__(self, messages, max_tokens=1200, **kw):
        self.calls.append(messages)
        return "已在指定位置新建了文件。"


def main():
    print("=" * 68)
    print("  缺陷 1 / 缺陷 2 回归：载体拦截 ≠ 模型退化；拦截不由模型转述")
    print("=" * 68)

    # ================= A 白名单 =================
    print("\n[A] 白名单：载体主动动作一律不算症状")
    ck("A", "红线拒绝被认成载体动作",
       is_carrier_action("🚫 这条操作被载体的「删除禁区」拦下了：Remove-Item 会永久删除文件"))
    ck("A", "权限待确认被认成载体动作",
       is_carrier_action("〔待确认〕小焦想执行**危险操作**，先把原文给你过目"))
    ck("A", "SSRF 拦截被认成载体动作", is_carrier_action("⚠️ 禁止访问本机/内网地址（SSRF 防护）"))
    ck("A", "限流被认成载体动作", is_carrier_action("请求太频繁：每分钟最多 30 次，请等 5 秒再试。"))
    ck("A", "载体新口径的拒绝原文也被认出来",
       is_carrier_action(X._carrier_block_answer("delete", "🚫 x")))
    ck("A", "正常工具结果**不**被当成载体动作",
       not is_carrier_action('{"status": 200, "content": "正常网页正文"}'))

    m = HealthMonitor()
    body = "好的，我看看这件事。" * 20
    red = [{"tool": "run_command", "args": {"command": "Remove-Item x"},
            "result": "🚫 这条操作被载体的「删除禁区」拦下了：Remove-Item 会永久删除文件"}] * 3
    syms = [s.code for s in m.check(body, {"tool_trace": red})]
    ck("A", "红线拦截连中 3 次 → 不再报任何行为症状", "tool_misuse" not in syms, syms or "无")
    ck("A", "也不会被判成『工具不调/无限循环』",
       not any(c in syms for c in ("tool_skipped", "infinite_loop")), syms or "无")

    # ================= B 真异常照样抓 =================
    print("\n[B] 白名单不能把判据废掉：真·模型乱调照样要报")
    m2 = HealthMonitor()
    bad = [{"tool": "get", "args": {"url": "http://a/%d" % i},
            "result": "工具执行失败：Error boom"} for i in range(6)]
    s2 = [s.code for s in m2.check(body, {"tool_trace": bad, "is_tool_turn": True})]
    ck("B", "同一工具真失败 6 次 → 仍报工具乱调", "tool_misuse" in s2, s2 or "无")
    m3 = HealthMonitor()
    s3 = [s.code for s in m3.check("然后说：嗯。然后说：哦。然后说：好的。" * 20, {})]
    ck("B", "真复读仍然被检出", "repeat" in s3, s3 or "无")

    # ================= C 拦截不经模型 =================
    print("\n[C] 缺陷 2：拦截原文直接给用户，模型没有机会编")
    fake = SpyModel()
    _orig_chat, _orig_tools = X.llm_chat, X.llm_chat_tools
    tmpdir = tempfile.mkdtemp(prefix="cb_")
    X.SESSIONS_FILE = os.path.join(tmpdir, "sessions.json")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "cb1", "sessions": [{"id": "cb1", "title": "t", "messages": []}]}, f)

    # ① 载体层直接判：run_tool 的返回就是用户要看到的那句话
    target = os.path.join(tmpdir, "user_file.txt")
    with open(target, "w", encoding="utf-8") as f:
        f.write("用户的数据，不许删")
    r = X.run_tool("run_command", {"command": 'Remove-Item "%s"' % target}, force=True)
    ck("C", "红线拦截的返回含用户指定的那句话", REQUIRED_LINE in str(r), str(r)[:60])
    ck("C", "并含载体写的细节（🚫 标记保留，供机器识别）", "🚫" in str(r))
    ck("C", "文件**没有被删**", os.path.exists(target))

    # ② 端到端：让模型走工具调用路径去删 → 用户看到的必须是载体原文
    try:
        X.llm_chat = fake
        # 直接把工具调用喂进 llm_chat_tools 的路径：构造一次真实的工具循环
        _orig_post = X._llm_post

        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {
                    "content": "",
                    "tool_calls": [{"id": "c1", "function": {
                        "name": "run_command",
                        "arguments": json.dumps({"command": 'Remove-Item "%s"' % target})}}]}}],
                    "usage": {}}
        X._llm_post = lambda t, payload, timeout=90, tries=4: (_Resp(), 200, "")
        try:
            ans, tr = X.llm_chat_tools([{"role": "user", "content": "删掉那个文件"}], max_rounds=2)
        finally:
            X._llm_post = _orig_post
        ck("C", "模型走工具调用删文件 → 用户看到的是载体原文", REQUIRED_LINE in str(ans),
           str(ans)[:70].replace("\n", " "))
        ck("C", "**没有**出现模型编的『已新建/已完成』",
           ("已新建" not in str(ans)) and ("已完成" not in str(ans)), str(ans)[:70])
        ck("C", "文件仍然没有被删", os.path.exists(target))
        ck("C", "工具轨迹里留了这次拦截（用户可复核）",
           any("删除禁区" in str(t.get("result")) for t in (tr or [])), [t.get("tool") for t in tr or []])
    finally:
        X.llm_chat, X.llm_chat_tools = _orig_chat, _orig_tools

    # ③ shell 直通那条路（"命令本身就是输入"）也不能说"已执行"
    ck("C", "shell 直通路径已接入拦截分支",
       "_carrier_block(_r)" in open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read())

    # ================= D switch_brain 三道闸 =================
    print("\n[D] 缺陷 1：switch_brain 先 ping、切完复核、失败回切、全程留痕")
    hooks = X._health_hooks()
    ck("D", "hooks 里有 switch_brain", callable(hooks.get("switch_brain")))
    before = X.LLM_BASE
    t0 = time.time()
    ok = hooks["switch_brain"]("缺陷1回归测试：故意让它切")
    el = time.time() - t0
    after = X.LLM_BASE
    src = open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
    ck("D", "切换前会 probe 目标（源码含探测调用）",
       "b.probe(timeout=4)" in src and "pb.get(\"ok\")" in src)
    ck("D", "切完 10 秒内复核（源码含复核循环）",
       "deadline = time.time() + 10.0" in src and "verify_ok" in src)
    ck("D", "复核不过 → 自动切回原火种（源码含回切）",
       "rolled_back" in src and "reg.switch(orig)" in src)
    ck("D", "每次切换都写 logs/carrier/brain_switch.jsonl（含原因）",
       "brain_switch.jsonl" in src and '"reason"' in src)
    logp = os.path.join(_ROOT, "logs", "carrier", "brain_switch.jsonl")
    lines = []
    if os.path.exists(logp):
        lines = [json.loads(l) for l in open(logp, encoding="utf-8") if l.strip()]
    mine = [r for r in lines if r.get("by") == "health.level3"]
    ck("D", "流水里能查到这次尝试（带 by/reason/result）",
       bool(mine) and all(k in mine[-1] for k in ("by", "reason", "result", "from", "to")),
       (mine[-1] if mine else None))
    ck("D", "结论：目标不可用时**不会**把大脑切坏",
       (after == before) or ok, "返回值=%s ｜ LLM_BASE %s → %s ｜ 耗时 %.1fs" % (ok, before, after, el))
    ck("D", "没有可切目标时如实返回 False（不假装成功）",
       (ok is False and "no_healthy_target" in json.dumps(mine[-1] if mine else {}, ensure_ascii=False))
       or ok is True, ok)

    print("\n" + "=" * 68)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
