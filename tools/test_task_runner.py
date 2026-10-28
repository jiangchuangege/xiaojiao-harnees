# -*- coding: utf-8 -*-
"""任务级自主 · 自测（离线、确定性：用假 app 打桩，不真联网）

钉住五件事：
  ① **状态机 + 落盘**：创建即落盘，status 能读回，进程重启后 resume 能接着做；
  ② **拆解先规则后模型**：规则命中就绝不去问模型（省时间也更稳）；
  ③ **失败换路**：第一步的工具挂了自动换同族工具，换完还不行就**停在那一步并写清原因**；
  ④ **验收**：每步有判据；判据没过 → 标 partial（部分完成），**不许说成完成**；
  ⑤ 做成之后：技能库固化 + 经验库记录。
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


class FakeApp:
    """假载体：只为验证任务流程，不碰真工具、不联网。"""

    def __init__(self):
        self.calls = []
        self.fail_tools = set()
        self.all_tool_names = lambda: ["get", "fetch", "write_file", "get_weather", "net_ip"]

    def _build_tools(self):
        return []

    def _tool_result_str(self, x):
        return str(x)

    def _tool_fallback_for(self, name):
        return {"get": ["fetch"], "fetch": ["stealthy_fetch"]}.get(name, [])

    def _detect_scrape_intent(self, q):
        if "http" in str(q):
            return ("get", {"url": "https://example.com"})
        return None

    def _scrape_save_target(self, q):
        return "G:\\dzs" if "G:\\dzs" in str(q) else ""

    def _weather_intent(self, q):
        return "天气" in str(q)

    def _specialized_args(self, name, q):
        return {"city": "菏泽"} if "菏泽" in str(q) else {}

    def _ebook_intent(self, q):
        return None

    def run_tool(self, name, args, force=False):
        self.calls.append((name, dict(args or {})))
        if name in self.fail_tools:
            return "抓取失败：连接超时"
        if name == "write_file":
            p = str((args or {}).get("path") or "")
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                # 真落盘的量级：真实抓一页正文都是成千上万字，写 "ok" 不能验证大小判据
                io.open(p, "w", encoding="utf-8").write("页面正文" * 120)
            except Exception:      # noqa: silent-ok — 测试里写不了就算了
                pass
            return "已写入：%s" % p
        if name == "get_weather":
            return "菏泽天气：阴 +13°C"
        if name == "net_ip":
            return "公网 IP：1.2.3.4（山东济南）"
        return '{"status": 200, "url": "https://example.com", "content": "页面正文"}'


def main():
    print("=" * 80)
    print("  任务级自主 自测")
    print("=" * 80)
    from core import task_runner as TR
    from core import skill_memory as SK

    tmp = tempfile.mkdtemp()
    dir_backup, sk_backup = TR._DIR, SK._PATH
    fake = FakeApp()
    try:
        TR._DIR = os.path.join(tmp, "tasks")
        SK._PATH = os.path.join(tmp, "skills.jsonl")
        TR._need_app = lambda: fake

        # ---------------- 一、拆解：规则优先 ----------------
        print("\n[一] 拆解：能由规则定的，绝不去问模型")
        steps = TR.plan_by_rules("把 https://example.com 的内容都抓下来存到 G:\\dzs")
        ck("抓取+落盘 → 规则拆成两步（抓 + 存）", len(steps) == 2, [s["tool"] for s in steps])
        ck("第一步是抓取，第二步是落盘",
           steps[0]["tool"] == "get" and steps[1]["tool"] == "write_file",
           [s["tool"] for s in steps])
        ck("落盘步骤带 __BODY__ 占位（正文要到抓完才知道）",
           steps[1]["args"].get("content") == "__BODY__", steps[1]["args"])
        st2 = TR.plan_by_rules("帮我查下菏泽的天气，然后看适不适合出门")
        ck("天气类 → 一步取真数据", len(st2) == 1 and st2[0]["tool"] == "get_weather", st2)
        ck("规则拿不准的（画图）→ 返回空，交给模型拆", TR.plan_by_rules("画一张架构图") == [])

        # ---------------- 二、执行 + 验收 + 落盘 ----------------
        print("\n[二] 执行：真跑、验收、落盘、可查")
        tid, msg = TR.start("把 https://example.com 的内容都抓下来存到 G:\\dzs", background=False)
        ck("任务能开起来", bool(tid), msg)
        ck("同步跑完后状态是 done", (TR.status(tid) or {}).get("state") == "done",
           (TR.status(tid) or {}).get("state"))
        st = TR.status(tid)
        ck("两步都做了", st["progress"] == "2/2", st["progress"])
        ck("每步都有工具轨迹（含换路记录）",
           all(s.get("used") for s in st["steps"]), [(s["tool"], s.get("used")) for s in st["steps"]])
        ck("状态文件真的落盘了", os.path.isfile(TR._path(tid)), TR._path(tid))
        ck("列表能查到这条任务",
           any(t["id"] == tid for t in TR.list_tasks(limit=20)))
        # 验收：写文件那步应该真的落了个文件
        w = [s for s in st["steps"] if s["tool"] == "write_file"][0]
        ck("落盘步骤验收通过（文件真在）", w.get("verify_ok") is True, w.get("verify_note"))
        # 【2026-10-28 加】真机上存下来的文件开头是 `{"status": 200, "url": …}` —— 是返回外壳，
        #   不是正文。这两条钉住"存的是正文""名字看得懂"。
        _wt = ""
        _m = re.search(r"([A-Za-z]:\\[^\s（）]+\.md)", "%s %s" % (
            w.get("verify_note") or "", w.get("result_head") or ""))
        _wp = _m.group(1) if _m else ""
        try:
            _wt = io.open(_wp, encoding="utf-8").read() if _wp else ""
        except Exception:      # noqa: silent-ok — 读不到就按失败计
            pass
        ck("存进去的是正文，不是工具返回的 JSON 外壳",
           bool(_wt) and '"status"' not in _wt and "页面正文" in _wt, _wt[:80])
        ck("落盘文件名看得懂（不再是固定 _task_body.md）",
           not _wp.endswith("_task_body.md") and "example" in _wp, _wp)

        # ---------------- 三、失败换路 + 如实标失败 ----------------
        print("\n[三] 失败换路：换完还不行就停在那一步，写清原因")
        fake2 = FakeApp()
        fake2.fail_tools = {"get", "fetch", "write_file"}
        TR._need_app = lambda: fake2
        tid2, _m2 = TR.start("把 http://a.com 的东西都抓下来存到 G:\\dzs", background=False)
        st3 = TR.status(tid2)
        ck("失败任务状态是 failed", st3["state"] == "failed", st3["state"])
        ck("原因写清了「第几步、哪个工具」", "第 1 步" in str(st3.get("why")), st3.get("why"))
        ck("换路记录里出现过备用工具（get → fetch）",
           any(t in str((st3["steps"][0] or {}).get("used")) for t in ("get", "fetch")),
           st3["steps"][0].get("used"))
        ck("失败时**没有**说成完成", st3["state"] != "done")

        # ---------------- 四、验收没把握 → partial ----------------
        print("\n[四] 验收没把握 → 标「部分完成」，不许说成完成")

        class HalfApp(FakeApp):
            def run_tool(self, name, args, force=False):
                if name == "write_file":
                    return "已存清单：/nonexistent/dir/x.md"     # 说了个不存在的路径
                return super().run_tool(name, args, force)

        TR._need_app = lambda: HalfApp()
        tid3, _m3 = TR.start("把 https://example.com 的内容都抓下来存到 G:\\dzs", background=False)
        st4 = TR.status(tid3)
        ck("状态仍是 done（流程走完了）", st4["state"] == "done", st4["state"])
        ck("但标了 partial（部分完成）", st4["partial"] is True, st4["partial"])
        ck("并写明哪步没把握", any("验收没把握" in w for w in st4["warnings"]), st4["warnings"])

        # ---------------- 五、resume + 技能固化 ----------------
        print("\n[五] resume 与技能固化")
        fake3 = FakeApp()
        TR._need_app = lambda: fake3
        task = TR.load(tid2)
        ck("失败任务能从磁盘读回", task is not None and task["id"] == tid2)
        ok_r, msg_r = TR.resume(tid2)
        ck("resume 能接着跑（把 failed 步重置）", ok_r is True, msg_r)
        TR.start("把 https://example.com 的内容都抓下来存到 G:\\dzs", background=False)
        rows = SK.load()
        ck("做成之后固化了技能（多步、无失败痕迹）", len(rows) >= 1, len(rows))
        ck("技能里记的是工具序列",
           rows and [s["tool"] for s in rows[-1]["steps"]][:1] in (["get"], ["fetch"]),
           rows and [s["tool"] for s in rows[-1]["steps"]])
        ck("目标太短直接拒", TR.start("抓一下", background=False)[0] == "")
        ck("stats 能报出总数与状态分布",
           "total" in TR.stats() and "by_state" in TR.stats(), TR.stats())

        # ---------------- 六、做完主动播报（只播一次） ----------------
        print("\n[六] 做完要主动说：播报取走即失效，不重复念")
        time.sleep(0.4)                            # 等前面 resume 的后台线程落地，再清播报
        TR.take_notice_text()                      # 把前面几条的播报先清掉
        for _ in range(20):                        # 每次最多播 3 条，清到干净为止
            if not TR.take_notice_text():
                break
        fake4 = FakeApp()
        TR._need_app = lambda: fake4
        tid_ok, _m4 = TR.start("把 https://example.com 的内容都抓下来存到 G:\\dzs", background=False)
        _n1 = TR.take_notice_text()
        ck("做完了 → 播报里说得清是哪条任务、几步", bool(_n1) and tid_ok in _n1 and "2/2" in _n1, _n1)
        ck("这一次只播这一条（不夹带别的任务）",
           _n1.strip().count("\n") == 0 and _n1.count("你先前开的任务") == 1, _n1)
        ck("播报说的是「做完了」而不是含糊其辞", "✅" in _n1, _n1)
        ck("同一件事只播一次（第二次取不到）", TR.take_notice_text() == "", "第二次还有内容")

        fake5 = FakeApp()
        fake5.fail_tools = {"get", "fetch", "write_file"}
        TR._need_app = lambda: fake5
        tid_bad, _m5 = TR.start("把 http://a.com 的东西都抓下来存到 G:\\dzs", background=False)
        _n2 = TR.take_notice_text()
        ck("失败了也要说，并且说清卡在哪", bool(_n2) and "⚠️" in _n2 and "没做成" in _n2, _n2)
        ck("失败播报里带任务号", tid_bad in _n2, _n2)
        # ---------------- 七、外壳工具不入技能库 ----------------
        print("\n[七] task_start 是外壳，不是做法（实测被它污染过技能库）")
        ok_w, why_w = SK.remember_task(
            "把某页抓下来存好",
            [{"tool": "task_start", "args": {"goal": "x"}, "result": "🚀 任务已开"},
             {"tool": "write_file", "args": {"path": "G:\\dzs\\a.md"}, "result": "已写入"}], "", 1.0)
        ck("序列里有 task_start → 不固化成技能", ok_w is False, why_w)
        ck("并且说清原因（不是静默跳过）", "任务" in str(why_w) or "外壳" in str(why_w), why_w)
    finally:
        TR._DIR, SK._PATH = dir_backup, sk_backup
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
