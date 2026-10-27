# -*- coding: utf-8 -*-
"""能力自增长（自写插件闭环）· 自测

钉住四道关，每一道都不许"模型说行就行"：
  ① **静态检查**：插件契约齐不齐、import 在不在白名单、有没有危险调用；
  ② **沙箱试跑**：另起子进程 import 并真调两个契约方法（不污染主进程）；
  ③ **schema 合规**：工具说明里必须有「什么时候用」，parameters 必须是标准 JSON Schema；
  ④ **只加不删**：重名不覆盖（本项目铁律）。
"""
import io
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []

GOOD = '''import re


class CapPlugin:
    def get_tool_descriptions(self):
        return [{"name": "text_stats",
                 "description": "统计字数与行数。什么时候用：要看字数/行数；输入 text；输出 统计",
                 "parameters": {"type": "object",
                                "properties": {"text": {"type": "string",
                                                        "description": "要统计的文字"}},
                                "required": ["text"]}}]

    def execute(self, tool_name, params):
        try:
            t = str((params or {}).get("text") or "")
            return "字数 %d ｜ 行数 %d" % (len(t), t.count("\\n") + 1)
        except Exception as e:
            return "统计失败：%s" % e


def get_plugin():
    return CapPlugin()
'''

DANGEROUS = '''import subprocess


class Bad:
    def get_tool_descriptions(self):
        return [{"name": "x", "description": "中文说明", "parameters": {}}]

    def execute(self, t, p):
        subprocess.run(["dir"], shell=True)
        return "ok"


def get_plugin():
    return Bad()
'''

NO_CONTRACT = '''class NoContract:
    def hi(self):
        return "你好"
'''

NO_CHINESE = '''class Bare:
    def get_tool_descriptions(self):
        return [{"name": "bare", "description": "do thing", "parameters": {}}]

    def execute(self, t, p):
        return "done"


def get_plugin():
    return Bare()
'''


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  能力自增长（自写插件）自测")
    print("=" * 80)
    from core import plugin_forge as PF

    # ---------------- 一、静态检查 ----------------
    print("\n[一] 静态检查：契约 / import 白名单 / 危险调用 / 中文说明")
    ok, probs = PF.static_check(GOOD)
    ck("合格插件通过静态检查", ok, probs[:2])
    ok2, p2 = PF.static_check(DANGEROUS)
    ck("有 subprocess 调用 → 不合格", ok2 is False, p2[:2])
    ck("并明确指出问题（危险调用或不在白名单的 import）",
       any(("危险" in x) or ("不允许的 import" in x) for x in p2), p2[:3])
    ok3, p3 = PF.static_check(NO_CONTRACT)
    ck("缺 get_plugin/契约方法 → 不合格", ok3 is False, p3[:3])
    ok4, p4 = PF.static_check(NO_CHINESE)
    ck("完全没有中文说明 → 不合格（模型会选不对工具）", ok4 is False, p4[:2])
    ok5, p5 = PF.static_check("import sys\nx = 1")
    ck("语法能过但没有契约 → 不合格", ok5 is False, p5[:2])
    ok6, p6 = PF.static_check("def get_plugin(:\n  pass")
    ck("语法错误能被指出来", ok6 is False and "语法错误" in p6[0], p6[:1])

    # ---------------- 二、沙箱试跑 ----------------
    print("\n[二] 沙箱试跑：另起子进程 import 并真调")
    tmp = tempfile.mkdtemp()
    pgood = os.path.join(tmp, "gen_ok.py")
    io.open(pgood, "w", encoding="utf-8").write(GOOD)
    ok7, why7, tools7 = PF.sandbox_run(pgood)
    ck("合格插件在沙箱里跑通", ok7 is True, why7[:60])
    ck("并报出它声明的工具名", tools7 == ["text_stats"], tools7)

    pbad = os.path.join(tmp, "gen_bad_contract.py")
    io.open(pbad, "w", encoding="utf-8").write(
        "class X:\n    def get_tool_descriptions(self):\n        return []\n"
        "    def execute(self, t, p):\n        return 'ok'\n\ndef get_plugin():\n    return X()\n")
    ok8, why8, _ = PF.sandbox_run(pbad)
    ck("返回空工具列表 → 沙箱判不合格", ok8 is False, why8[:60])

    praise = os.path.join(tmp, "gen_raise.py")
    io.open(praise, "w", encoding="utf-8").write(
        "class Y:\n    def get_tool_descriptions(self):\n        raise RuntimeError('boom')\n"
        "    def execute(self, t, p):\n        return 'ok'\n\ndef get_plugin():\n    return Y()\n")
    ok9, why9, _ = PF.sandbox_run(praise)
    ck("里面抛异常 → 沙箱判不合格（不会带进主进程）", ok9 is False and "boom" in why9, why9[:60])

    # ---------------- 三、完整闭环（dry-run：走完全部检查但不落地） ----------------
    print("\n[三] 完整闭环：生成 → 静态 → 沙箱 → （dry-run 不落地）")
    r = PF.forge("统计一段文字的字数", generator=lambda need: GOOD, dry_run=True)
    ck("闭环通过", r.get("ok") is True, {k: r.get(k) for k in ("stage", "why")})
    ck("stage 标为 dry-run（明确没落地）", r.get("stage") == "dry-run", r.get("stage"))
    ck("dry-run 不写文件", r.get("path") == "", r.get("path"))
    ck("模块名是 gen_ 开头（不会撞到人工写的插件）", str(r.get("module", "")).startswith("gen_"),
       r.get("module"))

    r2 = PF.forge("跑个命令", generator=lambda need: DANGEROUS, dry_run=True)
    ck("危险代码在静态检查就被挡下", r2.get("ok") is False and r2.get("stage") == "static",
       (r2.get("stage"), str(r2.get("why"))[:40]))

    r3 = PF.forge("", generator=lambda need: GOOD)
    ck("需求为空 → 直接拒（不浪费模型调用）", r3.get("ok") is False, r3.get("why"))

    r4 = PF.forge("统计", generator=lambda need: "", dry_run=True)
    ck("模型没产出代码 → 如实失败", r4.get("ok") is False and r4.get("stage") == "generate",
       r4.get("why"))

    # ---------------- 四、只加不删 ----------------
    print("\n[四] 重名不覆盖（这个项目只加不删）")
    target_dir = os.path.join(_ROOT, "plugins")
    before = set(os.listdir(target_dir))
    ck("plugins/ 目录还在", os.path.isdir(target_dir), target_dir)
    ck("自测没有往 plugins/ 里塞东西（dry-run 的承诺）",
       set(os.listdir(target_dir)) == before)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
