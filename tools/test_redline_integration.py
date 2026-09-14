# -*- coding: utf-8 -*-
"""删除红线「接线」自测：走**真实的工具入口** `run_tool`，不直接调安全模块。

运行：python tools/test_redline_integration.py
为什么必须走 run_tool：`core/security/no_delete.py` 自己有单测（tools/test_no_delete.py），
但那只能证明"判定函数是对的"。用户要的是**载体层真的拦得住** —— 也就是说，
模型无论从哪个工具进来（run_command / write_file / edit_file / background），
都必须撞上这道闸门。这个脚本证明的就是"接线"本身没漏。

判据：
  · 直接/间接删除 → 被拒，且给出**可读中文提示**（不是栈、不是正则）
  · 新建 / 追加 / 读 → 允许（红线只禁删除与覆盖，不是把工具废掉）
  · **不依赖 full_access**：把 full_access 打开，删除照样拦
  · 所有文件操作入口都覆盖到（逐个工具名验一遍）
"""
import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []
TMP = tempfile.mkdtemp(prefix="redline_")


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


def is_denied(res):
    """被红线拦下的返回长什么样（可读中文 + 🚫）。"""
    s = str(res or "")
    return ("🚫" in s) and ("禁区" in s or "拦下" in s)


def main():
    print("=" * 62)
    print("  删除红线 · 接线自测（走真实工具入口 run_tool）")
    print("=" * 62)

    # ===== A 直接删除：每个入口都要拦 =====
    print("\n[A] 直接删除（逐个入口）")
    # A1 run_command
    r = X.run_tool("run_command", {"command": "del /f /q C:\\Windows\\win.ini"}, force=True)
    ck("A", "run_command + del 被拦", is_denied(r), str(r)[:70])
    ck("A", "提示可读（含原因与替代建议）",
       "为什么" in str(r) or "不可逆" in str(r), str(r)[:120].replace("\n", " "))
    ck("A", "提示里不出现栈/异常名/正则", not any(k in str(r) for k in
                                          ("Traceback", "re.error", "Exception", r"\b")), str(r)[:80])
    # A2 各种删除写法
    for cmd, tag in [("rm -rf build", "rm -rf"),
                     ("Remove-Item -Recurse -Force C:\\tmp", "Remove-Item"),
                     ("rd /s /q C:\\tmp", "rd /s /q"),
                     ("unlink /tmp/a", "unlink"),
                     ("git clean -fdx", "git clean"),
                     ("format D:", "format")]:
        rr = X.run_tool("run_command", {"command": cmd}, force=True)
        ck("A", "run_command + %s 被拦" % tag, is_denied(rr), str(rr)[:50])
    # A3 background（后台执行也是执行）
    rb = X.run_tool("background", {"command": "del a.txt", "timeout": 5}, force=True)
    ck("A", "background + del 被拦", is_denied(rb), str(rb)[:60])

    # ===== B 间接删除 =====
    print("\n[B] 间接删除（拼接 / 内联代码 / 脚本执行 / 脚本正文）")
    for cmd, tag in [("echo hi ; del a.txt", "分号拼接"),
                     ("echo hi && del a.txt", "&& 拼接"),
                     ("echo hi | Remove-Item a", "管道拼接"),
                     ('python -c "import os;os.remove(\'a\')"', "python -c os.remove"),
                     ('python -c "import shutil;shutil.rmtree(\'d\')"', "python -c rmtree"),
                     ("powershell -Command \"rm a\"", "powershell -Command"),
                     ("cmd /c del a.txt", "cmd /c"),
                     ("[System.IO.File]::Delete('a')", ".NET Delete")]:
        rr = X.run_tool("run_command", {"command": cmd}, force=True)
        ck("B", "间接删除 · %s 被拦" % tag, is_denied(rr), str(rr)[:50])
    # B 脚本正文：写一个含删除命令的脚本 → 写的时候就该被拦
    script = os.path.join(TMP, "cleanup.ps1")
    rw = X.run_tool("write_file", {"path": script, "content": "Remove-Item -Recurse -Force C:\\tmp\n"},
                    force=True)
    ck("B", "写「含删除命令的脚本」被拦", is_denied(rw), str(rw)[:60])
    ck("B", "被拦后脚本文件没有被创建", not os.path.exists(script))
    # B 执行一个已存在的脚本（内容含删除）→ 拦
    #    （先绕开红线把脚本放在那儿：用 Python 直接写，不走工具层）
    script2 = os.path.join(TMP, "cleanup2.bat")
    with open(script2, "w", encoding="utf-8") as f:
        f.write("@echo off\r\ndel /f /q C:\\important.txt\r\n")
    r2 = X.run_tool("run_command", {"command": 'powershell -File "%s"' % script2}, force=True)
    ck("B", "执行「内容含删除的脚本」被拦（读了脚本正文）", is_denied(r2), str(r2)[:60])

    # ===== C 覆盖与清空（红线 7、8）=====
    print("\n[C] 覆盖已有文件 / 清空内容")
    keep = os.path.join(TMP, "user_data.txt")
    with open(keep, "w", encoding="utf-8") as f:
        f.write("用户自己的数据，不许被覆盖\n")
    rc = X.run_tool("write_file", {"path": keep, "content": "被小焦覆盖了"}, force=True)
    ck("C", "覆盖已有文件被拦", is_denied(rc), str(rc)[:60])
    with open(keep, encoding="utf-8") as f:
        ck("C", "用户原文件一个字都没变", "用户自己的数据" in f.read())
    # 清空 = Set-Content $null / Clear-Content
    for cmd, tag in [("Clear-Content a.txt", "Clear-Content"),
                     ("Set-Content a.txt $null", "Set-Content $null"),
                     ("git reset --hard", "git reset --hard")]:
        rr = X.run_tool("run_command", {"command": cmd}, force=True)
        ck("C", "清空/重置 · %s 被拦" % tag, is_denied(rr), str(rr)[:50])

    # ===== D 新建 / 追加 / 读 —— 必须放行（红线不是把工具废掉）=====
    print("\n[D] 新建 / 追加 / 读 —— 一律放行")
    new_f = os.path.join(TMP, "brand_new.txt")
    r1 = X.run_tool("write_file", {"path": new_f, "content": "新文件"}, force=True)
    ck("D", "新建文件放行", "已写入" in str(r1) and not is_denied(r1), str(r1)[:50])
    ck("D", "文件真的建出来了", os.path.exists(new_f))
    # 追加：用 run_command 的 Add-Content（不是删除，是追加）→ 放行
    r2b = X.run_tool("run_command", {"command": 'Add-Content -Path "%s" -Value "追加一行"' % new_f},
                     force=True)
    ck("D", "追加内容放行", not is_denied(r2b), str(r2b)[:50])
    r3 = X.run_tool("read_file", {"path": new_f}, force=True)
    ck("D", "读文件放行", "新文件" in str(r3) and not is_denied(r3), str(r3)[:30])
    for cmd, tag in [("dir", "dir"), ("echo hello", "echo"),
                     ('Select-String -Path xiaojiao_app.py -Pattern "delete"', "读式搜索 delete"),
                     ('python -c "print(1+1)"', "python -c print")]:
        rr = X.run_tool("run_command", {"command": cmd}, force=True)
        ck("D", "正常命令放行 · %s" % tag, not is_denied(rr), str(rr)[:40])

    # ===== E 不依赖 full_access（红线 4）=====
    print("\n[E] 开了全权限，删除照样拦")
    old = X.FULL_ACCESS
    try:
        X.FULL_ACCESS = True
        re_ = X.run_tool("run_command", {"command": "del a.txt"}, force=True)
        ck("E", "full_access=True 下删除仍被拦", is_denied(re_), str(re_)[:50])
        re2 = X.run_tool("write_file", {"path": keep, "content": "覆盖"}, force=True)
        ck("E", "full_access=True 下覆盖仍被拦", is_denied(re2), str(re2)[:50])
    finally:
        X.FULL_ACCESS = old
    src = open(os.path.join(_ROOT, "core", "security", "no_delete.py"), encoding="utf-8").read()
    ck("E", "安全模块源码里没有任何 full_access 分支", "full_access" not in src)

    # ===== F 入口覆盖度：登记表里的每个工具都真的被拦 =====
    print("\n[F] 入口覆盖度（登记表 vs 实际拦截）")
    from core.security import no_delete as N  # noqa: E402
    ck("F", "红线登记的入口含命令与写文件类",
       set(X._DELETE_GUARD_TOOLS) >= {"run_command", "background", "write_file", "edit_file"},
       sorted(X._DELETE_GUARD_TOOLS))
    # 登记表改坏了要能被发现：给一个不在表里的工具名，确认它**不**经过红线
    # （这正是"以后加了新工具要照着补"的风险点，用断言把风险显式化）
    unknown = X.run_tool("list_files", {"path": "."}, force=True)
    ck("F", "非文件/命令类工具不走红线（不是所有工具都拦）", not is_denied(unknown))
    ck("F", "安全模块可单独审计（explain 有中文说明）", len(N.explain()) > 100)

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
