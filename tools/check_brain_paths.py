# -*- coding: utf-8 -*-
"""大脑路径体检：`llama-swap.yaml` 里每个路由的 **模型文件到底在不在**。

【为什么要有这个工具（实测踩到的真事）】
`llama-swap.yaml` 里的 `coder` 路由指着 `G:/模型文件/工具调用模型/Qwen3-8B-Q4_K_M.gguf`，
而那个文件**早就不在了**（模型挪去了 `G:/moxing__xiaojiao/工具调用模型/`）。
后果很阴：配置里看着有这条路由，真去调它才会发现起不来 —— 而且中间**没有任何报错**，
表现只是"一直等"。换个盘、挪个目录，同样的坑会再来一次。
所以把"配置里写的路径 vs 磁盘上真实存在"这件事变成一条可跑的命令。

顺带体检：**配置文件里出现的每一台机器上的绝对路径**（模型 / llama-server / 目次），
以及 llama-swap 本身在不在、9292 通不通。

用法：
    python tools/check_brain_paths.py            # 只看
    python tools/check_brain_paths.py --probe    # 顺带探一下 9292/8080 通不通

退出码：0 = 全部路径都在；1 = 有缺（CI/启动前都能用）。
"""
import argparse
import io
import os
import re
import socket
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 从配置里捞"像路径的字符串"：cmd 里的 --model X / 独立一行的 X
_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\s\"']+|/[^\s\"']+)")
# yaml 会把整条 cmd 用引号包起来（内层双引号留给 llama-swap 的 ${PORT} 占位符替换）——先脱掉最外面那层
_CMD_WRAP_RE = re.compile(r"""^\s*cmd:\s*(['"])(.*)\1\s*$""")
# 成对双引号里的整条（路径里带空格时，只有看引号才捞得对）
_DQ_RE = re.compile(r'"([^"\n]*)"')


def _unwrap_cmd(line):
    """`cmd: '...'` → `...`（没被包起来就原样返回）。"""
    m = _CMD_WRAP_RE.match(line)
    return m.group(2) if m else line


def _paths_in(text):
    """捞路径。**先看引号、再看裸文本** —— 这条顺序是踩过坑才定下来的：

    实测 `--model "C:/xiaojiao/xiaojiao harness/Qwopus....gguf"` 这条路径**本身是对的**，
    但按空白切词的老写法把后面的 `harness/Qwopus....gguf` 当成了一个新路径，体检于是误报
    「有 1 处路径不存在」——配置没错、是工具错了（假红比不报更误导人）。
    """
    out = []
    for q in _DQ_RE.findall(text):
        if re.match(r"^[A-Za-z]:[\\/]", q) or q.startswith("/"):
            out.append(q)
    out.extend(_PATH_RE.findall(_DQ_RE.sub(" ", text)))
    return out


def _swap_cfg_path():
    """llama-swap 配置：优先仓库根目录那份（本项目自己的），其次 gitignored 的 vendor 目录。"""
    for p in (os.path.join(ROOT, "llama-swap.yaml"),
              os.path.join(ROOT, "llama-swap", "llama-swap.yaml")):
        if os.path.exists(p):
            return p
    return ""


def _lines(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().split("\n")


def _routes(text):
    """粗解析：`models:` 下面每个二级键就是一条路由（够用且不引第三方 yaml）。"""
    out, cur = [], None
    in_models = False
    for line in text.split("\n"):
        if re.match(r"^models:\s*$", line):
            in_models = True
            continue
        if in_models and re.match(r"^\S", line) and not line.startswith("#"):
            break
        m = re.match(r"^  (\w[\w\-\.]*):\s*$", line)
        if in_models and m:
            cur = m.group(1)
            out.append({"name": cur, "paths": [], "lines": []})
            continue
        if cur and line.strip() and not line.strip().startswith("#"):
            out[-1]["lines"].append(line.strip())
            for p in _paths_in(_unwrap_cmd(line)):
                out[-1]["paths"].append(p)
    return out


def _port_open(port, host="127.0.0.1", timeout=1.5):
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:      # noqa: silent-ok — 探不通就是探不通
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="大脑路径体检")
    ap.add_argument("--probe", action="store_true", help="顺带探 9292 / 8080 通不通")
    args = ap.parse_args()

    cfg = _swap_cfg_path()
    print("=" * 74)
    print("  大脑路径体检")
    print("=" * 74)
    if not cfg:
        print("❌ 找不到 llama-swap 配置（llama-swap.yaml）")
        return 1
    print("配置：%s" % os.path.relpath(cfg, ROOT))
    text = "\n".join(_lines(cfg))

    # 1. llama-server 可执行文件
    exes = set()
    for p in _paths_in(text):
        if p.lower().endswith(".exe"):
            exes.add(p)
    bad = 0
    print("\n【llama-server】")
    for p in sorted(exes):
        ok = os.path.exists(p)
        print("  %s %s" % ("✅" if ok else "❌", p))
        bad += 0 if ok else 1

    # 2. 每条路由的模型文件
    print("\n【路由 → 模型文件】")
    for r in _routes(text):
        models = [p for p in r["paths"] if p.lower().endswith(".gguf")]
        if not models:
            print("  ⚠️  %-14s 这条路由里没解析出 .gguf（可能是云接口/别的形态）" % r["name"])
            continue
        for m in models:
            ok = os.path.exists(m)
            size = ""
            if ok:
                try:
                    size = "（%.2f GB）" % (os.path.getsize(m) / (1024.0 ** 3))
                except OSError:      # noqa: silent-ok
                    size = ""
            print("  %s %-14s %s%s" % ("✅" if ok else "❌", r["name"], m, size))
            if not ok:
                bad += 1
                # 帮着找一下同名文件是不是被挪走了（这正是实测踩到的那个形状）
                name = os.path.basename(m)
                hits = []
                for drive in ("C:\\", "D:\\", "E:\\", "F:\\", "G:\\"):
                    if not os.path.isdir(drive):
                        continue
                    for dirpath, dirnames, filenames in os.walk(drive):
                        dirnames[:] = [d for d in dirnames
                                       if d.lower() not in ("windows", "$recycle.bin", "node_modules")]
                        if name in filenames:
                            hits.append(os.path.join(dirpath, name))
                            break
                        if len(hits) >= 3:
                            break
                    if hits:
                        break
                if hits:
                    print("      ↳ 磁盘上找到了同名文件（很可能是被挪走了）：%s" % hits[0])

    # 3. 端口
    if args.probe:
        print("\n【端口】")
        for port, what in ((9292, "llama-swap"), (8080, "llama-server 直连"), (5000, "小焦 Web")):
            ok = _port_open(port)
            print("  %s %-22s :%d" % ("✅" if ok else "—", what, port))

    print("\n" + "-" * 74)
    print("结论：%s" % ("✅ 配置里写的路径**全都在**" if bad == 0
                      else "❌ 有 %d 处路径不存在（上面的 ❌）—— 那种路由调起来只会干等" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
