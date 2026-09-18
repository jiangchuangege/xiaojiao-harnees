# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""外部路径体检 / 一键改成"这台机器上的真路径"（**换电脑第一件事跑它**）。

【它解决什么】下载了源码、模型在别的盘 —— 以前得手工去改 `llama-swap.yaml` 里那几行绝对路径；
不改就是"路由一调就干等"（`tools/check_brain_paths.py` 会报 ❌）。现在一条命令：

    python tools/setup_paths.py                 # 只看：五项外部路径各自在哪、靠什么找到的
    python tools/setup_paths.py --apply         # 真改：把 llama-swap.yaml 里"指向不存在文件"的路径换成探测到的
    python tools/setup_paths.py --gguf D:/m/xx.gguf --llama-server D:/llama/llama-server.exe   # 自己指定
    python tools/setup_paths.py --deep          # 允许整盘深搜（慢，几十秒；不给就只查 PATH/项目/常见目录）

【解析顺序与"如实回报"】见 `core/paths.py` 的模块注释：环境变量 > PATH/常见目录 > 深搜；
每一项都打印**"靠什么找到的"**，找不到就明写该设哪个环境变量 —— **绝不猜一个看起来像的路径**。
`--apply` 只在"原来那条路径的文件真的不存在"时才动它，并且先整份备份到
`logs/backup_before_setup_paths/<时间戳>/`（跑得好好的配置不许被顺手改掉）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok
        pass

from core import paths as P  # noqa: E402


def main():
    argv = sys.argv[1:]
    deep = "--deep" in argv
    apply_ = "--apply" in argv

    def arg(name):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1].strip()
        return ""

    server = arg("--llama-server") or P.find_llama_server(deep=deep)[0]
    gguf = arg("--gguf") or P.find_gguf(deep=deep)[0]

    print("=" * 92)
    print("  外部路径体检（不写死任何一台机器；环境变量优先，其次 PATH/项目/常见目录%s）"
          % ("，本次允许整盘深搜" if deep else ""))
    print("=" * 92)
    if server:
        print("  llama-server : %s（%s）" % (server, "命令参数指定" if arg("--llama-server") else "自动探测"))
    else:
        print("  llama-server : ❌ %s" % P.find_llama_server(deep=deep)[1])
    if gguf:
        print("  GGUF 模型    : %s（%s）" % (gguf, "命令参数指定" if arg("--gguf") else "自动探测"))
    else:
        print("  GGUF 模型    : ❌ %s" % P.find_gguf(deep=deep)[1])
    print("-" * 92)
    print("  %-12s %-8s %s" % ("项目", "状态", "路径 / 说明"))
    for r in P.report(deep=deep):
        print("  %-12s %-8s %s" % (r["what"], "✅" if r["ok"] else "—",
                                   r["path"] or r["how"]))
    print("-" * 92)
    print("  自己指定（任何一项都能用手动值压过自动探测）：")
    for k, v in P.ENV_VARS.items():
        print("      set %-24s = 完整路径" % v)
    print("  改完重开一个终端再启动小焦（环境变量只对新开的窗口生效）。")

    print()
    print("=" * 92)
    print("  llama-swap.yaml 里写死的路径")
    print("=" * 92)
    out = P.fix_swap_cfg(server=server, gguf=gguf, only_missing=True, dry_run=not apply_)
    if not out.get("ok"):
        print("  %s" % out.get("why"))
        return 0
    ch = out.get("changes") or []
    if not ch:
        print("  ✅ 一条都不用改（里面写着的路径在这台机器上都存在）")
    else:
        for c in ch:
            print("  · 路由 %-28s %-6s\n      旧：%s\n      新：%s"
                  % (c["route"], c["what"], c["old"], c["new"]))
        if apply_:
            print("\n  ✅ 已改（备份：%s）" % os.path.relpath(out["backup"], ROOT))
            print("     改完重启 llama-swap 或重启小焦才生效。")
        else:
            print("\n  这是 **dry-run**（一个字节都没改）。要真改：加 `--apply`")
    print("\n  改完再复检路由：python tools/check_brain_paths.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
