# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""删除禁区自测（core/security/no_delete.py）

用法：
    python tools/test_no_delete.py

它验的是"载体层的硬约束"到底硬不硬，一共七组：
    [A] 直接删除      各种删文件 / 删目录 / 删磁盘的写法        → 必须拦（24 条）
    [B] 间接删除      拼接 / 内联代码 / 脚本正文 / 写脚本内容   → 必须拦（红线第 6 条）
    [C] 清空与重置    清空和删除同罪                           → 必须拦（红线第 8 条）
    [D] 必须放行      正常读 / 查 / 新建 / 追加                 → 一条都不许误杀
    [E] 覆盖红线      不覆盖用户文件，只能新建或追加            → 红线第 7 条
    [F] 不靠开关      **源码级断言**：判断里没有任何"权限开关"分支
    [G] 接口形状      主线按这套接口接入，签名/别名/异常都要对得上

本脚本自己的规矩（很重要，不守规矩这份自测就没有说服力）：
  · **从不删除任何文件**：临时脚本只新建在 `logs/security/_test_tmp/<本次运行号>/` 下
    （`logs/` 已经在 .gitignore 里）。跑一百次就是多一百个小目录，绝不动你已有的东西。
    为什么坚持只新建：一个测"删除禁区"的脚本要是自己会删东西，那就成了笑话 ——
    测的东西和做的东西必须是同一套价值观。
  · 测试里的危险命令**全是字符串字面量，永远不会被真的执行**，它们只是喂给守卫的输入。
  · 失败时该改的是 `core/security/no_delete.py`，不是这里。
    把判据放宽来迁就测试，等于把闸门拆了再宣布门锁很好用。
  · 用例表放在模块级、每组一个函数：一是每段都短到能一眼看完，
    二是"哪一组挂了"直接看得见，不用在几百行里翻。

退出码：全绿 0，有失败 1（可以直接挂进 CI）。
"""
import os
import sys
import uuid

# 仓库根入 sys.path：这样从任意目录（CI、tools/、别的脚本里）跑都能 import 到 core.security。
# 去掉它 → 只有站在仓库根才能跑，CI 里换个工作目录就 ImportError。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Windows 控制台默认不是 UTF-8，不设一下 ✅/❌ 会变成乱码（只影响显示，不影响判定）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: silent-ok — 老环境没有 reconfigure 也不该让自测跑不起来
    pass

from core.security import no_delete as nd      # noqa: E402 — 必须在 sys.path 之后导入

# 本次运行的临时目录：用随机号，保证每次只"新建"，永远不覆盖上一次的东西。
_TMP = os.path.join(_ROOT, "logs", "security", "_test_tmp", "run_" + uuid.uuid4().hex[:8])
_COUNT = {"pass": 0, "total": 0}
_FAILED = []

# 反引号（命令行替换的老写法）。为什么不直接写字面量：
# 守卫会把"反引号包起来的内容"当命令替换挖出来递归判，文件里直接写一对反引号，
# 这个自测脚本自身就会看起来含一段命令替换 —— 自己把自己拦下，那就说不清了。
_BT = chr(96)


# ------------------------------------------------------------------ 用例表
# [A] 直接删除：删文件 / 删目录 / 删磁盘。**每一种写法都必须被拦**。
# 为什么连 format/mkfs/diskpart 这些也测：磁盘级动作一次就是灾难，不留口子。
_CASES_A = (
    "rm a.txt",
    "del a.txt",
    "erase a.txt",
    "Remove-Item a.txt -Force",
    "ri a.txt",
    "unlink a.txt",
    "rmdir somedir",
    "rd somedir",
    "python -c \"import shutil; shutil.rmtree('x')\"",
    "python -c \"import os; os.remove('x')\"",
    "python -c \"import os; os.unlink('x')\"",
    "python -c \"import os; os.rmdir('x')\"",
    "python -c \"from pathlib import Path; Path('x').unlink()\"",
    "powershell -Command \"[System.IO.File]::Delete('C:/tmp/a.txt')\"",
    "powershell -Command \"[System.IO.Directory]::Delete('C:/tmp/a')\"",
    "git rm -r --cached x",
    "git clean -fdx",
    "format D:",
    "mkfs.ext4 /dev/sdb1",
    "diskpart /s C:/tmp/part.txt",
    "cipher /w:C",
    "sdelete -p 3 C:/tmp/a.txt",
    "Clear-Disk -Number 1",
    "Remove-Partition -DiskNumber 1",
)

# [B] 间接删除（红线第 6 条"脚本里的删除也算小焦自己删"）。
# 脚本文件那几条的路径在 main 里补进来（它们要先被造出来）。
_CASES_B = (
    "echo hi; rm a.txt",
    "echo hi && del a.txt",
    "echo hi | Remove-Item a",
    "echo hi\nrm a.txt",
    "$(rm a.txt)",
    "echo \"$(rm a.txt)\"",
    "echo " + _BT + "rm a.txt" + _BT,
    "powershell -Command \"rm a\"",
    "cmd /c del a",
    "python -c \"import os; os.system('rm -rf x')\"",
    "python -c \"import os; os.truncate('a', 0)\"",
    "bash missing_not_here.sh",
    "python missing_not_here.py",
)

# [C] 清空 / 重置（红线第 8 条：内容没了就是没了）。重定向那两条的目标在 main 里补。
_CASES_C = (
    "Clear-Content a.txt",
    "Set-Content a.txt $null",
    "truncate -s 0 a.txt",
    "echo $null > out.txt",
    ": > a.txt",
    "git reset --hard HEAD",
    "git checkout -- .",
)

# [D] 必须放行。这些是"误杀"的靶子：每一条都是正常干活，被拦一次用户就会怀疑闸门。
# 其中三条最容易被写坏，单独说明：
#   · Select-String … "delete" —— delete 只是**读取**的参数值，不是动作；
#   · grep -rn "os.remove" / echo "本文件不会被删除" —— 引号里是数据，只是"提到"删除；
#   · python tools/test_no_delete.py —— 自洽：守卫不许拦项目自己的自测脚本
#     （它自己就得是一份"含删除命令示例但绝不含删除动作"的正常文件）。
#   · python core/security/no_delete.py —— 同理：规则书里成段引用危险命令原文，
#     但全在注释和文档字符串里（= 数据）。守卫要连这个都拦，说明它没分清"写到"和"做到"。
_CASES_D = (
    "echo hello",
    "dir",
    "ls",
    "type a.txt",
    "cat a.txt",
    "head -5 a.txt",
    "Get-Content a.txt",
    "python -c \"print(1)\"",
    "python --version",
    "git status",
    "git log --oneline -5",
    "git diff --stat",
    "Select-String -Path a.py -Pattern \"delete\"",
    "echo \"本文件不会被删除\"",
    "grep -rn \"os.remove\" src/",
    "findstr rm a.txt",
    "mkdir -p logs/security/_test_tmp/placeholder_dir",
    "python tools/test_no_delete.py",
    "python core/security/no_delete.py",
)


# ------------------------------------------------------------------ 记账
# 拒绝提示的固定前缀：打印时把它去掉，只留"为什么被拦"那句，一行看得完。
_PREFIX = "🚫 这条操作被载体的「删除禁区」拦下了："


def _record(tag, ok, detail):
    """记一条结果并立刻打印（测试要能一眼看出是哪条挂了，不能攒到最后才说）。"""
    _COUNT["total"] += 1
    if ok:
        _COUNT["pass"] += 1
        print("   ✅ %s  %s" % (tag, detail))
    else:
        _FAILED.append(tag)
        print("   ❌ %s  %s" % (tag, detail))


def _prompt_shape_ok(msg):
    """拒绝提示必须是给用户看的：🚫 开头 + 原因 + 替代建议，且不许泄漏正则/栈/异常名。

    为什么把"提示长什么样"也当验收项：被拦的人要的是"我该怎么办"。
    一条只有"违反了规则 3"的提示，等于把人堵在门口还不说怎么走。
    """
    leaked = ("Traceback", "re.compile", "regex", "Exception", "ValueError",
              "TypeError", "FileNotFoundError", "KeyError")
    return (msg.startswith("🚫") and "原因：" in msg and "替代建议：" in msg
            and not any(x in msg for x in leaked))


def _show(cmd, limit=62):
    """把命令显示成一行（换行转义，免得把表格撑破）。"""
    s = cmd.replace("\n", "\\n").replace("\r", "\\r")
    return s if len(s) <= limit else s[:limit - 3] + "..."


def _check_cmd(tag, cmd, want_block):
    """命令组的一条：两个入口必须**结论一致**，被拦时的提示形状也必须合格。

    为什么要同时验 check_command 和 is_delete_command：
    主线走 check_command，别的模块可能走 is_delete_command；
    两个入口给出不同答案，是安全代码里最危险的那种不一致。
    """
    msg = nd.check_command(cmd)
    hit, _why = nd.is_delete_command(cmd)
    blocked = bool(msg)
    ok = (blocked == want_block) and (bool(hit) == want_block)
    if ok and want_block:
        ok = _prompt_shape_ok(msg)
        detail = "拦下 → %s" % msg.splitlines()[0].replace(_PREFIX, "")
    elif want_block:
        detail = "**漏放**（这是漏删，比误杀严重）"
    elif blocked:
        detail = "误杀 → %s" % msg.splitlines()[0]
    else:
        detail = "放行"
    _record(tag, ok, "%s  ｜ %s" % (_show(cmd), detail))


def _check_guard(tag, msg, want_block):
    """文件操作 / 写文件守卫的一条。"""
    blocked = bool(msg)
    ok = blocked == want_block
    if ok and want_block:
        ok = _prompt_shape_ok(msg)
    detail = ("拦下 → %s" % msg.splitlines()[0].replace(_PREFIX, "")) if blocked else "放行"
    _record(tag, ok, "%s  ｜ %s" % (tag, detail))


def _assert(tag, ok, detail):
    """不涉及守卫调用的断言（源码级 / 接口形状）。"""
    _record(tag, bool(ok), detail)


# ------------------------------------------------------------------ 素材
def _mk(name, text):
    """在本次运行的临时目录里**新建**一个文件，返回绝对路径。

    为什么显式指定 newline="\\n"：Windows 下默认会把 \\n 写成 \\r\\n，
    而脚本正文是逐行判的，别让平台差异影响测试结论。
    """
    p = os.path.join(_TMP, name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return os.path.abspath(p)


def _fixtures():
    """造本次运行要用的素材：干净脚本 / 脏脚本 / 用户已有文件（**只新建，不删除**）。

    为什么要专门造一个"干净脚本"和一个"正文里只提到删除 API"的脚本：
    如果守卫对任何脚本一刀切地拦，"脚本执行"就废了；这两条证明它读的是正文内容。
    """
    os.makedirs(_TMP, exist_ok=True)
    return {
        "clean_sh": _mk("clean.sh", "#!/bin/bash\n# 只看一眼当前目录，什么都不动\necho \"hello from a clean script\"\n"),
        "clean_py": _mk("clean.py", "\"\"\"文档字符串里提到过 os.remove 的示例，但那只是文字。\"\"\"\nimport os\n# 注掉的旧代码：os.unlink('old')\nprint(os.getcwd())\n"),
        "dirty_sh": _mk("dirty.sh", "#!/bin/bash\nrm -rf ./never_exists_dir\n"),
        "dirty_py": _mk("dirty.py", "import os\nos.remove(\"never_exists_file.txt\")\n"),
        "dirty_bat": _mk("dirty.bat", "@echo off\ndel never_exists_file.txt\n"),
        "dirty_ps1": _mk("dirty.ps1", "Remove-Item ./never_exists_file.txt\n"),
        # 脚本里再执行脚本：验"递归读正文"，删除藏在第二层也跑不掉
        "nested_sh": _mk("nested.sh", "#!/bin/bash\npython \"%s\"\n" % _mk("inner.py", "import os\nos.remove(\"never_exists_file.txt\")\n").replace("\\", "/")),
        "existing": _mk("existing_user_file.txt", "这是用户已有的内容，谁都不许覆盖。\n"),
        "brand_new": os.path.join(_TMP, "brand_new_file.txt"),      # 故意不创建：代表"新建"
        "readme": os.path.join(_ROOT, "README.md"),
    }


# ------------------------------------------------------------------ 各组
def _group_a(_fx):
    print("\n[A] 直接删除：删文件 / 删目录 / 删磁盘的各种写法 —— 必须**全部**拦下")
    for cmd in _CASES_A:
        _check_cmd("[A]", cmd, True)


def _group_b(fx):
    print("\n[B] 间接删除：拼接 / 内联代码 / 脚本正文 / 要写盘的脚本内容 —— 红线第 6 条")
    rel_ps1 = os.path.relpath(fx["dirty_ps1"], _ROOT).replace("\\", "/")
    for cmd in _CASES_B + (
        "bash \"%s\"" % fx["dirty_sh"],          # 删除藏在脚本正文里
        "python \"%s\"" % fx["dirty_py"],        # 正文里用的是库函数形态
        "bash \"%s\"" % fx["nested_sh"],         # 脚本里再执行脚本（递归）
        "& \"%s\"" % fx["dirty_bat"],            # PowerShell 调用运算符
        "./" + rel_ps1,                          # 直接执行脚本
    ):
        _check_cmd("[B]", cmd, True)
    _check_guard("[B] 写脚本内容含删除（要写盘的脚本也算，红线第 6 条）",
                 nd.guard_write(fx["brand_new"], "@echo off\ndel never_exists_file.txt\n"), True)
    _check_guard("[B] 写脚本内容含删除（Python 库函数形态）",
                 nd.guard_write(fx["brand_new"], "import shutil\nshutil.rmtree('never_exists_dir')\n"), True)


def _group_c(fx):
    print("\n[C] 清空 / 重置：内容和删除同罪（红线第 8 条）—— 必须拦下")
    for cmd in _CASES_C + (
        "echo hi > \"%s\"" % fx["existing"],     # 重定向到**已存在**的文件 = 清空它
        "echo hi 2> \"%s\"" % fx["existing"],
    ):
        _check_cmd("[C]", cmd, True)


def _group_d(fx):
    print("\n[D] 正常操作：一条都不许误杀（误杀多了，用户会关掉闸门，闸门就废了）")
    for cmd in _CASES_D + (
        "echo hello > \"%s\"" % fx["brand_new"],   # 重定向到**不存在**的文件 = 新建，允许
        "echo hi >> \"%s\"" % fx["existing"],      # 追加不动旧内容，允许
        "bash \"%s\"" % fx["clean_sh"],            # 正文干净 → 放行
        "python \"%s\"" % fx["clean_py"],          # 正文里的删除 API 只在注释/文档里 → 放行
    ):
        _check_cmd("[D]", cmd, False)


def _group_e(fx):
    print("\n[E] 文件红线：不覆盖用户文件，只能新建或追加（红线第 7 条）")
    _check_guard("[E] 写已存在的用户文件（mode=w）→ 拦", nd.guard_write(fx["existing"], "新内容"), True)
    _check_guard("[E] 写不存在的路径（新建）→ 放行", nd.guard_write(fx["brand_new"], "print(1)\n"), False)
    _check_guard("[E] 追加已存在的用户文件（mode=a）→ 放行", nd.guard_write(fx["existing"], "额外一行\n", mode="a"), False)
    _check_guard("[E] 追加但内容里有删除动作 → 拦", nd.guard_write(fx["existing"], "rm -rf x\n", mode="a"), True)
    _check_guard("[E] check_file_op(read) → 一律放行", nd.check_file_op("read", fx["existing"]), False)
    _check_guard("[E] check_file_op(delete) → 一律拒绝", nd.check_file_op("delete", fx["existing"]), True)
    _check_guard("[E] check_file_op(write, 已存在) → 拦", nd.check_file_op("write", fx["existing"], "x"), True)
    _check_guard("[E] check_file_op(write, 已存在, allow_overwrite=True) → 放行（载体自有文件的唯一出口）",
                 nd.check_file_op("write", fx["existing"], "x", allow_overwrite=True), False)
    _check_guard("[E] check_file_op(write, 新文件) → 放行", nd.check_file_op("write", fx["brand_new"], "hello"), False)
    _check_guard("[E] check_file_op(不认识的动词) → 一律拦（fail-closed）",
                 nd.check_file_op("purge", fx["existing"]), True)
    _check_guard("[E] 写真实仓库文件 README.md → 拦", nd.guard_write(fx["readme"], "x"), True)
    # 守卫必须"只判断、不落盘"：上面调了十几次，用户文件必须一个字节都没变
    with open(fx["existing"], "r", encoding="utf-8") as f:
        after = f.read()
    _assert("[E] 守卫只判断不落盘", after.startswith("这是用户已有的内容"),
            "临时用户文件内容未被改动：%r" % after[:16])


def _group_f(_fx):
    print("\n[F] 不依赖任何权限开关：判断全在代码里，模型和配置都没有否决权")
    src = ""
    for p in (os.path.join(os.path.dirname(nd.__file__), "no_delete.py"),
              os.path.join(os.path.dirname(nd.__file__), "__init__.py")):
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            src += f.read()
    # 这一条是**源码级断言**：不是"看起来没读配置"，而是"源码里根本搜不到那个开关名"。
    # 为什么必须这么验：靠"运行时没触发"证明不了什么（换个配置就触发了）；
    # 搜源码才能钉死"判断里没有那条分支"。
    _assert("[F1] 源码里没有任何权限开关分支", "full_access" not in src,
            "no_delete.py / __init__.py 里搜不到那个开关名（真·代码层硬约束）")
    for bad in ("xiaojiao_app", "import flask", "from flask", "xiaojiao_config"):
        _assert("[F2] 不依赖主程序/配置：%s" % bad, bad not in src.lower(),
                "源码里没有 %s" % bad)
    _assert("[F3] 模块能独立 import（没有顺带拉起 Flask / 主程序）",
            "flask" not in sys.modules and "xiaojiao_app" not in sys.modules,
            "sys.modules 里没有 flask / xiaojiao_app")


def _group_g(_fx):
    print("\n[G] 接口形状：主线会照这套接口接入，签名/别名/异常都要对得上")
    _assert("[G1] BAN_RULES 是可审计的 (正则, 原因) 表",
            isinstance(nd.BAN_RULES, list) and len(nd.BAN_RULES) >= 20
            and all(isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], str)
                    and isinstance(r[1], str) for r in nd.BAN_RULES),
            "共 %d 条硬规则" % len(nd.BAN_RULES))
    _assert("[G2] SUSPECT_RULES 是次级信号表（单独命中不拦，执行器语境才升级）",
            isinstance(nd.SUSPECT_RULES, list) and len(nd.SUSPECT_RULES) >= 3
            and all(isinstance(r, tuple) and len(r) == 2 for r in nd.SUSPECT_RULES),
            "共 %d 条次级信号" % len(nd.SUSPECT_RULES))
    _assert("[G3] guard_command 是 check_command 的同义闸门",
            nd.guard_command("rm a.txt") == nd.check_command("rm a.txt") != "",
            "同一结论：拦")
    raised = False
    try:
        nd.assert_command("rm a.txt")
    except nd.DeleteBlocked as e:
        raised = _prompt_shape_ok(str(e))
    _assert("[G4] assert_command 被拦时抛 DeleteBlocked（消息就是给人看的中文提示）", raised,
            "DeleteBlocked 已抛出且提示形状合格")
    hit, why = nd.is_delete_command("rm a.txt")
    _assert("[G5] is_delete_command 返回 (布尔, 证据片段)",
            hit is True and bool(why) and nd.is_delete_command("echo hello") == (False, ""),
            "命中带证据：%s" % why)
    _assert("[G6] explain() 是给用户看的中文说明",
            "删除" in nd.explain() and len(nd.explain()) > 80, "共 %d 字" % len(nd.explain()))
    _assert("[G7] 空命令/None 不炸也不误拦",
            nd.check_command("") == "" and nd.check_command(None) == ""
            and nd.is_delete_command("") == (False, ""), "空输入安全放行")


def main():
    print("=" * 100)
    print("小焦 · 载体层 · 删除禁区自测（删除是小焦世界里唯一的禁区）")
    print("模块：%s" % nd.__file__)
    print("临时目录（只新建、从不删除）：%s" % _TMP)
    print("=" * 100)
    fx = _fixtures()
    for group in (_group_a, _group_b, _group_c, _group_d, _group_e, _group_f, _group_g):
        group(fx)

    print("\n" + "=" * 100)
    if _FAILED:
        print("❌ 失败的条目：%s" % "、".join(_FAILED))
    print("通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    print("本次新建的临时文件在：%s（本脚本从不删除任何文件）" % _TMP)
    print("=" * 100)
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
