# -*- coding: utf-8 -*-
"""明文密钥自查：找出还写在配置文件里的 API Key / Token（安全第一批·任务3）

为什么要有这个工具：
    密钥以前只能写在 xiaojiao_control.json 这类**本地明文**文件里，一旦被误发、误传、
    误提交，就等于公开了。任务3 把读取顺序改成「环境变量 XIAOJIAO_API_KEY 优先、控制文件
    兜底」——但**旧文件里的明文密钥不会自己消失**，这个工具就是用来把它找出来的。

定位：**自查 / 迁移提醒工具，不是 CI 闸门**。
    本机的 xiaojiao_control.json 是被 .gitignore 忽略的私有文件，里面留明文 key 属于历史
    遗留且相当常见；把它挂进 CI 会让每个人本地都判失败，所以**故意不接入** CI 与
    tools/check_principles.py。想迁移就按 --fix-hint 的提示做，然后重跑本工具确认清零。

用法：
    python tools/check_secrets.py                 # 扫默认的候选配置文件
    python tools/check_secrets.py --include-logs  # 连 logs/ 下的历史备份一起扫（"确认没残留"用）
    python tools/check_secrets.py --fix-hint      # 额外打印「怎么改成环境变量」
    python tools/check_secrets.py 某文件.json      # 只扫指定文件
退出码：0 = 未发现明文密钥；1 = 发现了（需要处理）

为什么要有 --include-logs：默认只扫仓库根目录的配置文件，而 logs/ 里的历史备份
（backup_before_*/xiaojiao_control.json、_ctl_backup.json 之类）**同样带着明文密钥**。
真实教训：本工具第一次跑默认扫描时报"未发现明文密钥"，可 logs/ 下其实还躺着 4 个文件、
8 处明文 —— 假阴性比不报还危险。默认不扫它们是因为"备份是回滚安全网、常年留着很正常"，
但想做一次彻底确认，就用 --include-logs。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: silent-ok — 老环境没有 reconfigure 也不该让工具挂掉
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 默认要扫哪些文件：控制文件/配置文件的正文，以及它们的 .bak / .example / 带后缀的副本
# （副本最容易被人忘了删、又最容易被一起打包发出去，所以一并扫）
CANDIDATE_GLOBS = (
    "xiaojiao_control.json", "xiaojiao_config.json",
    "xiaojiao_control*.json*", "xiaojiao_config*.json*",
    "*.bak", "*.bak.*",
)

# 密钥形状的指纹。变量名固定叫 SECRET_PATTERNS：仓库里的"无明文密钥"用例
# （tests/stress/test_security.py 第 9 项）按这个名字豁免"扫描器自身的规则文本"。
SECRET_PATTERNS = (
    ("OpenAI 风格密钥", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GitHub Token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
)

# 带这些标记的行是"故意放的假密钥"（用例夹具），不算命中
IGNORE_MARKERS = ("secret-fixture", "SECRET_PATTERNS")

FIX_HINT = """
怎么改成环境变量（不用改代码，设好重启小焦即可）：

  Windows（只在当前窗口有效，适合先试一下）：
      $env:XIAOJIAO_API_KEY="sk-你的密钥"

  Windows（永久，以后新开的窗口都生效）：
      setx XIAOJIAO_API_KEY "sk-你的密钥"

  Linux / macOS：
      export XIAOJIAO_API_KEY=sk-你的密钥

  然后把控制文件里的明文擦掉（两种写法都行）：
      "api_key": ""                        # 留空即可 —— 环境变量已经优先生效
      "api_key": "env:XIAOJIAO_API_KEY"    # 显式写"去读这个环境变量"

  优先级：环境变量 XIAOJIAO_API_KEY  >  控制文件 brain.api.api_key

  ⚠️ 密钥已经在明文文件里躺过一段时间了 —— 建议去服务商后台**作废它、重新生成**一把。
  ⚠️ 这个文件已被 .gitignore 忽略；但它若曾被提交过，历史记录里仍然有明文，务必轮换。
"""


def mask(secret, keep_head=3, keep_tail=2):
    """把密钥打码成"只够认出是哪一把"的样子（打码后依然不泄露中间部分）。"""
    s = secret.strip()
    if len(s) <= keep_head + keep_tail:
        return "*" * len(s)
    return s[:keep_head] + "*" * (len(s) - keep_head - keep_tail) + s[-keep_tail:]


def candidate_files():
    """默认候选文件：按 glob 收集去重（同一文件不会因为命中多个 glob 被扫两遍）。"""
    found = {}
    for pat in CANDIDATE_GLOBS:
        for p in glob.glob(os.path.join(ROOT, pat)):
            if os.path.isfile(p):
                found[os.path.abspath(p)] = True
    return sorted(found)


# --include-logs 时要跳过的二进制/大文件后缀（它们不可能"改去环境变量"，扫了只有噪音）
LOG_SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp",
                ".pth", ".pkl", ".zip", ".bin", ".pt", ".onnx", ".db",
                ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".wav", ".pdf")


def log_files():
    """logs/ 下的历史备份（递归）。默认不扫：备份是回滚安全网，常年留着很正常 ——
    但它们确实可能带着明文密钥，所以用 --include-logs 做一次彻底确认。"""
    out = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "logs")):
        for fn in filenames:
            if fn.lower().endswith(LOG_SKIP_EXT):
                continue
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def scan_file(path):
    """扫单个文件，返回命中列表 [{'line': n, 'kind':..., 'masked_line':...}]。"""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError as e:
        print("  ⚠️ 读不了，跳过：%s（%s）" % (os.path.relpath(path, ROOT), e))
        return []

    hits = []
    for no, line in enumerate(text.splitlines(), 1):
        if any(mk in line for mk in IGNORE_MARKERS):
            continue
        shown, kinds = line.strip(), []
        for name, pat in SECRET_PATTERNS:
            for m in pat.finditer(line):
                kind = name
                if kind not in kinds:
                    kinds.append(kind)
                shown = shown.replace(m.group(0), mask(m.group(0)))
        if kinds:
            hits.append({"line": no, "kinds": kinds, "masked_line": shown[:120]})
    return hits


def main():
    ap = argparse.ArgumentParser(description="扫出配置文件里的明文密钥（默认只提醒，不改文件）")
    ap.add_argument("paths", nargs="*", help="只扫这些文件；不给就扫默认候选文件")
    ap.add_argument("--include-logs", action="store_true",
                    help="连 logs/ 下的历史备份一起扫（做一次彻底确认时用）")
    ap.add_argument("--fix-hint", action="store_true", help="额外打印「怎么改成环境变量」")
    args = ap.parse_args()

    if args.paths:
        files = [os.path.abspath(p) for p in args.paths]
        missing = [p for p in files if not os.path.isfile(p)]
        for p in missing:
            print("  ⚠️ 文件不存在：%s" % p)
        files = [p for p in files if os.path.isfile(p)]
    else:
        files = candidate_files()
        if args.include_logs:
            files = sorted(set(files) | set(log_files()))

    print("=" * 62)
    print("  明文密钥自查（优先读环境变量 XIAOJIAO_API_KEY）")
    print("=" * 62)
    if not files:
        print("  没有找到候选配置文件（还没建过 xiaojiao_control.json？）")
    for p in files:
        print("  · 扫描 %s" % os.path.relpath(p, ROOT))
    print("-" * 62)

    total, hit_files = 0, []
    for p in files:
        hits = scan_file(p)
        if not hits:
            continue
        hit_files.append(p)
        total += len(hits)
        for h in hits:
            print("  ❌ %s:%d  ·  %s" % (os.path.relpath(p, ROOT), h["line"], " / ".join(h["kinds"])))
            print("       明文：%s" % h["masked_line"])

    print("-" * 62)
    if total:
        print("  ❌ 发现 %d 处明文密钥（涉及 %d 个文件）—— 建议迁到环境变量。" % (total, len(hit_files)))
        if args.fix_hint:
            print(FIX_HINT)
        else:
            print("  想看怎么改：python tools/check_secrets.py --fix-hint")
        return 1
    print("  ✅ 未发现明文密钥（扫了 %d 个文件）" % len(files))
    if args.fix_hint:
        print(FIX_HINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
