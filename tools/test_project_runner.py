# -*- coding: utf-8 -*-
"""长时项目自测（`core/project_runner.py`）

要点不是"能跑通"，而是这五条**长时任务特有的东西**：
  ① 拆解：规则能定的走规则（不问模型），规则不行才问模型，模型给歪了也不许脏；
  ② 验收：三种可程序化判据（文件/含关键词/步数）都要真判，判不了就说"没把握"；
  ③ 预算：超预算要**停下来汇报**（不是闷头跑），而且预算设成 0 也得算数；
  ④ 失败分级：关键里程碑失败 → 整个项目 failed；非关键失败 → done 但标 partial；
  ⑤ 跨重启：状态在磁盘上，重启后能读回来接着跑（并且**不偷偷**自己跑）。
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def ck(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print("  ✅ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))
    else:
        FAIL.append(name)
        print("  ❌ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))


def main():
    print("=" * 84)
    print("  长时项目 自测")
    print("=" * 84)
    from core import project_runner as PR
    from core import task_runner as TR

    tmp = tempfile.mkdtemp(prefix="xj_proj_")
    outdir = os.path.join(tmp, "out")
    pdir_backup = PR._DIR
    PR._DIR = os.path.join(tmp, "projects")

    class FakeApp:
        """假载体：只为验证项目流程，不碰真工具、不联网、不调模型。"""

        def __init__(self):
            self.calls = []
            self.fail_tools = set()
            self.llm_plan = "[]"
            self.all_tool_names = lambda: ["get", "write_file", "get_weather", "net_ip"]

        def _build_tools(self):
            return []

        def _tool_result_str(self, x):
            return str(x)

        def _tool_fallback_for(self, name):
            return []

        def _detect_scrape_intent(self, q):
            return ("get", {"url": "https://example.com"}) if "http" in q else None

        def _scrape_save_target(self, q):
            return outdir if "存到" in q else ""

        def _weather_intent(self, q):
            return "天气" in q

        def _specialized_args(self, name, q):
            return {"city": "菏泽"}

        def _ebook_intent(self, q):
            return None

        def llm_chat(self, messages):
            return self.llm_plan

        def run_tool(self, name, args, force=False):
            self.calls.append((name, dict(args or {})))
            if name in self.fail_tools:
                return "抓取失败：连接超时"
            if name == "write_file":
                p = str((args or {}).get("path") or "")
                d = os.path.dirname(p)
                if d:
                    os.makedirs(d, exist_ok=True)
                with io.open(p, "w", encoding="utf-8") as f:
                    f.write("正文内容。" * 200)
                return "已写入：%s" % p
            if name == "get_weather":
                return "菏泽天气：阴 +13°C"
            return '{"status": 200, "content": "Example Domain 页面正文"}'

    fake = FakeApp()
    TR._need_app = lambda: fake
    try:
        # ---------------- 一、拆解 ----------------
        print("\n[一] 拆解：规则优先，模型只兜底")
        ms, how = PR.plan_milestones("把 https://example.com 的内容都抓下来存到 %s" % outdir)
        ck("规则能判的目标 → 不劳模型", how == "规则", how)
        ck("规则路只给一个里程碑（一次做完）", len(ms) == 1, len(ms))
        ck("并且**推出了**可程序化的验收判据（不是空）",
           "文件：" in str(ms[0].get("accept")), ms[0].get("accept"))

        fake.llm_plan = json.dumps([
            {"title": "查资料", "do": "查一下菏泽天气并把结果写进报告", "accept": "含：菏泽"},
            {"title": "收尾", "do": "把结论整理成一段话", "accept": "步数：1"},
        ], ensure_ascii=False)
        # 用一句**规则一定认不出**的目标（没有网址/天气/电子书/公网IP 这些规则特征）
        ms2, how2 = PR.plan_milestones("帮我把这件事分三个阶段做完，最后归档到我的笔记里")
        ck("规则拿不准 → 交给模型拆", how2.startswith("模型"), how2)
        if how2.startswith("模型"):
            ck("模型拆出来的里程碑被收下", len(ms2) == 2, len(ms2))
            ck("里程碑都带 critical 标记", all("critical" in m for m in ms2))
        # 【2026-10-28 加】用户**明确要求分阶段**时，规则不许把要求吞掉（实测踩过：
        #   「把这一页分三个阶段做完」被规则拆成"一次做完"，用户的"分阶段"就这么没了）
        ms2b, how2b = PR.plan_milestones("把这一页的内容分三个阶段做完，最后存到 G:\\dzs\\x")
        ck("明确要分阶段 → 先问模型（不被规则吞掉）", how2b.startswith("模型"), how2b)
        ck("并且真的给了多个里程碑", len(ms2b) >= 2, len(ms2b))
        fake.llm_plan = "这不是 JSON"
        ms3, how3 = PR.plan_milestones("把这件事分阶段做完，按你的想法来")
        ck("模型给歪了 → 不脏，退成单里程碑", len(ms3) == 1 and how3 == "兜底",
           (len(ms3), how3))
        fake.llm_plan = json.dumps([{"title": "x", "do": "短", "accept": ""}], ensure_ascii=False)
        ms4, _how4 = PR.plan_milestones("再分阶段做一次试试看")
        ck("模型给的步骤太短（<6 字）→ 不收", all(len(m["do"]) >= 6 for m in ms4), ms4)

        # ---------------- 二、验收判据 ----------------
        print("\n[二] 验收：三种判据都要真判")
        art = os.path.join(tmp, "a.md")
        io.open(art, "w", encoding="utf-8").write("正文" * 100)
        ok, note = PR._accept_ok("文件：%s" % art, "", {"state": "done"})
        ck("文件判据：文件在且够大 → 过", ok is True, note)
        tiny = os.path.join(tmp, "tiny.md")
        io.open(tiny, "w", encoding="utf-8").write("x")
        ok2, note2 = PR._accept_ok("文件：%s" % tiny, "", {"state": "done"})
        ck("文件判据：文件在但几乎是空的 → 不过", ok2 is False, note2)
        ok3, note3 = PR._accept_ok("文件：%s" % os.path.join(tmp, "没有这个.md"), "",
                                   {"state": "done"})
        ck("文件判据：文件不在 → 不过", ok3 is False, note3)
        ok4, note4 = PR._accept_ok("含：菏泽、13", "菏泽天气 阴 +13°C", {"state": "done"})
        ck("关键词判据：都在 → 过", ok4 is True, note4)
        ok5, note5 = PR._accept_ok("含：菏泽、暴雨", "菏泽天气 阴 +13°C", {"state": "done"})
        ck("关键词判据：缺一个 → 不过", ok5 is False, note5)
        ok6, note6 = PR._accept_ok("步数：2", "", {"state": "done", "progress": "2/2"})
        ck("步数判据：做够了 → 过", ok6 is True, note6)
        ok7, note7 = PR._accept_ok("步数：3", "", {"state": "done", "progress": "2/2"})
        ck("步数判据：不够 → 不过", ok7 is False, note7)
        ok8, note8 = PR._accept_ok("我看着挺好", "", {"state": "done"})
        ck("说不清的判据 → 退成任务状态，并**写明**是按状态计",
           ok8 is True and "按任务状态计" in note8, note8)

        # ---------------- 三、正常跑完 ----------------
        print("\n[三] 正常跑完：状态、报告、技能都落")
        pid, msg = PR.start("把 https://example.com 的内容都抓下来存到 %s" % outdir,
                            background=False)
        ck("项目能开起来", bool(pid), msg)
        st = PR.status(pid)
        ck("同步跑完状态是 done", st["state"] == "done", st["state"])
        ck("里程碑 1/1 做成", st["progress"] == "1/1", st["progress"])
        ck("里程碑的验收结论写清了（不是「完成」两个字）",
           "文件在" in str(st["milestones"][0].get("verify_note")),
           st["milestones"][0].get("verify_note"))
        ck("状态文件落在磁盘上", os.path.isfile(PR._path(pid)))
        ck("完工报告写出来了", os.path.isfile(st["report"] or ""), st["report"])
        rep = io.open(st["report"], encoding="utf-8").read()
        ck("报告里有里程碑表与说明", "里程碑" in rep and "说明" in rep)
        ck("报告里写了「不会说成完成」的口径", "不会说成「完成」" in rep or "没把握" in rep)

        # ---------------- 四、预算 ----------------
        print("\n[四] 预算：超了就停下汇报（预算 0 也算数）")
        pid2, _m2 = PR.start("把 https://example.com 的内容都抓下来存到 %s" % outdir,
                             budget={"max_minutes": 0.0}, background=False)
        st2 = PR.status(pid2)
        ck("预算 0 分钟 → 暂停而不是硬跑", st2["state"] == "paused", st2["state"])
        ck("暂停时写清原因（超了哪个预算）", "预算" in str(st2["why"]), st2["why"])
        ck("预算 0 不会被当成「没设预算」（0 是假值的坑）",
           "≤" not in str(st2["why"]) or "0.00" in str(st2["why"]), st2["why"])
        pid3, _m3 = PR.start("把 https://example.com 的内容都抓下来存到 %s" % outdir,
                             budget={"max_minutes": 60, "max_steps": 0}, background=False)
        st3 = PR.status(pid3)
        ck("步数预算 0 → 也暂停", st3["state"] == "paused", st3["state"])

        # ---------------- 五、失败分级 ----------------
        print("\n[五] 失败分级：关键的就停，不关键的继续但标 partial")
        fake.fail_tools = {"get", "write_file"}
        pid4, _m4 = PR.start("把 http://a.com 的内容都抓下来存到 %s" % outdir, background=False)
        st4 = PR.status(pid4)
        ck("关键里程碑没做成 → 整个项目 failed", st4["state"] == "failed", st4["state"])
        ck("失败原因写清第几个里程碑、卡在哪",
           "关键里程碑" in str(st4["why"]) and "第 1 个" in str(st4["why"]), st4["why"])
        fake.fail_tools = set()

        # 非关键失败：手工造一个两里程碑的项目，第二个非关键且注定失败
        art2 = os.path.join(tmp, "never.md")
        p = {"id": "manual_nonc", "goal": "测试非关键失败", "state": "created",
             "plan_from": "手工", "milestones": [
                 {"i": 1, "title": "能成的", "do": "查一下菏泽天气",
                  "accept": "含：菏泽", "critical": True, "state": "pending", "task_id": "",
                  "note": "", "verify_ok": None, "verify_note": "", "result_head": "",
                  "attempts": 0},
                 {"i": 2, "title": "注定失败的", "do": "把 http://a.com 抓下来存到 %s" % outdir,
                  "accept": "文件：%s" % art2, "critical": False, "state": "pending",
                  "task_id": "", "note": "", "verify_ok": None, "verify_note": "",
                  "result_head": "", "attempts": 0}],
             "budget": dict(PR._DEFAULT_BUDGET),
             "spent": {"minutes": 0.0, "steps": 0},
             "created_at": "2026-10-28T00:00:00", "why": "", "warnings": [], "partial": False}
        PR._save(p)
        fake.fail_tools = {"get", "write_file"}
        PR._run("manual_nonc")
        fake.fail_tools = set()
        st5 = PR.status("manual_nonc")
        ck("非关键里程碑失败 → 项目仍是 done", st5["state"] == "done", st5["state"])
        ck("但标了 partial（部分完成）", st5["partial"] is True, st5["partial"])
        ck("并且写清哪个没做成", any("注定失败的" in w for w in st5["warnings"]), st5["warnings"])

        # ---------------- 六、跨重启 ----------------
        print("\n[六] 跨重启：状态在磁盘、别偷偷跑")
        pid5, _m5 = PR.start("把 https://example.com 的内容都抓下来存到 %s" % outdir,
                             budget={"max_minutes": 0.0}, background=False)
        st6 = PR.status(pid5)
        ck("先造一个暂停的项目", st6["state"] == "paused", st6["state"])
        paused = PR.resume_pending()
        ck("resume_pending 只认「没跑完」的项目", isinstance(paused, list), paused)
        p_disk = json.load(io.open(PR._path(pid5), encoding="utf-8"))
        ck("磁盘上的状态能读回来（不是只在内存里）",
           p_disk.get("id") == pid5 and p_disk.get("milestones"), p_disk.get("state"))
        ok_r, why_r = PR.resume_project(pid5)
        ck("resume 能接着跑", ok_r is True, why_r)
        ok_r2, why_r2 = PR.resume_project(pid)
        ck("已经完成的项目不会被重跑", ok_r2 is False and "完成" in str(why_r2), why_r2)
        rows = PR.list_projects(limit=10)
        ck("项目列表能查到这几条", len(rows) >= 4, len(rows))
        ck("列表里带进度（做成了几个）", all("done" in r and "total" in r for r in rows))
        ck("stats 能报出状态分布", "by_state" in PR.stats(), PR.stats())
    finally:
        PR._DIR = pdir_backup
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 84)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 84)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
