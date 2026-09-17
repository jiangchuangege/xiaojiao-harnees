# -*- coding: utf-8 -*-
"""备用直连线「收线」自测（离线；用**真进程**跑，不用假的）

【钉的是什么】
2026-09-18 实测：llama-swap 不在时应用会退到**直连 8080** 那条备用线；等 llama-swap 回来，
**没有人去收掉那条线** —— 一个 8080 的 llama-server 从 21:57 活到 01:20，两份 4B 权重同时
抢 16GB 内存与 8GB 显存，一个 token 100 秒。用户的原话是「互相打架是因为没触发切换」。
`start_xiaojiao.stop_stray_direct_line()` 就是补上的那一步。

【两条都要钉】
  · **该收的**要收掉（起一个真进程，绑在临时端口，命令行里带标记 → 必须被杀掉）
  · **不该动的**一个字都不许动（同一个端口上是个**名字对不上**的进程 → 必须活着）
    ⚠️ 后一条比前一条重要：收线的判据写宽了，就可能 kill 掉用户在 8080 上的别的服务。

运行：python tools/test_brain_line_cleanup.py
"""
import os
import socket
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


DUMMY = ("import socket,time,sys\n"
         "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
         "s.bind(('127.0.0.1',int(sys.argv[1]))); s.listen(5)\n"
         "time.sleep(120)\n")


def _spawn(marker, port):
    """起一个真进程：绑住 port，命令行里带 marker（这样它就是"名字对得上的那个"）。"""
    return subprocess.Popen([sys.executable, "-c", DUMMY, str(port), marker],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_listen(port, timeout=10):
    for _ in range(int(timeout * 10)):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.3)
            s.close()
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main():
    import psutil
    import start_xiaojiao as S          # 只为拿那个函数；模块级不会起服务（有 __main__ 保护）

    port_a, port_b, port_free = 18091, 18092, 18093

    print("一、端口上**没有**进程 → 不该报错、也不该乱杀")
    pid, why = S.stop_stray_direct_line(port=port_free, expect="llama-server")
    ck("空端口 → (None, 说明)", pid is None and "没有进程" in why, (pid, why))

    print("\n二、**名字对不上**的进程 → 一个字都不许动（安全红线）")
    pa = _spawn("my-own-service", port_a)
    ck("假进程起来了（端口 %d 能连上）" % port_a, _wait_listen(port_a), pa.pid)
    pid2, why2 = S.stop_stray_direct_line(port=port_a, expect="llama-server")
    time.sleep(1)
    ck("返回「没动它」", pid2 is None and ("没动它" in why2 or "不是" in why2), (pid2, why2))
    ck("**那个进程还活着**（没被误杀）", psutil.pid_exists(pa.pid) and pa.poll() is None, pa.poll())
    try:
        s = socket.create_connection(("127.0.0.1", port_a), timeout=1); s.close()
        ck("端口还通着", True)
    except Exception as e:
        ck("端口还通着", False, e)
    pa.terminate()

    print("\n三、**名字对得上**的进程 → 必须收回")
    pb = _spawn("llama-server", port_b)
    ck("假 llama-server 起来了", _wait_listen(port_b), pb.pid)
    pid3, why3 = S.stop_stray_direct_line(port=port_b, expect="llama-server")
    time.sleep(1)
    ck("返回被杀掉的 pid", pid3 == pb.pid, (pid3, pb.pid, why3))
    ck("那个进程真的没了", not psutil.pid_exists(pb.pid) or pb.poll() is not None, pb.poll())
    try:
        s = socket.create_connection(("127.0.0.1", port_b), timeout=1); s.close()
        ck("端口已释放", False, "还通着")
    except Exception:
        ck("端口已释放", True)

    print("\n四、真的接在启动路径上了吗（源码级）")
    src = open(os.path.join(_ROOT, "start_xiaojiao.py"), encoding="utf-8").read()
    ck("start_llama_brain 里调了收线", "stop_stray_direct_line()" in src)
    _i = src.find("已由 llama-swap(9292) 管理")
    _j = src.find("stop_stray_direct_line()")
    ck("而且是在「跳过冗余直连」那个分支里调的", 0 < _i < _j < _i + 1200, (_i, _j))
    ck("默认端口取的是 BRAIN.llama.port（不是写死 8080）",
       'BRAIN.get("llama", {}).get("port", 8080)' in src)

    print("\n五、如实标注（写进测试，免得以后没人知道）")
    print("     · 收线只在**应用启动**那一步做（备用线本来就是启动时才会起）。")
    print("     · 找不到 psutil 时走 netstat+taskkill 兜底 —— 那条路**不校验进程名**，")
    print("       是已知的次优路径（只有装了 psutil 的正式环境才走安全那条）。")

    print("\n" + "=" * 66)
    print("备用直连线收线自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
