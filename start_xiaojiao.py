# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""
小焦 · 一键启动（把她融合成一套：大模型大脑 + 小焦壳 + Web + N.E.K.O. 猫娘）

用法：  python start_xiaojiao.py
它做五件事：
  1. 读取「操控文件」xiaojiao_control.json
  2. 若配置了本地大模型(GGUF) → 自动用 llama.cpp 跑起来
  3. 启动小焦的 Web 界面
  4. 自动打开浏览器
  5. 拉起 N.E.K.O. 猫娘(48911/48912) + 后台学习
"""
import os
import shutil, sys, time, threading, webbrowser, subprocess
import requests
import xiaojiao_app as app
import logging  # noqa: F401  （由 tools/fix_silent_except.py 注入）
try:
    from xiaojiao_log import get_logger
except Exception:  # 独立运行时退化为标准 logging
    def get_logger(name=None):
        return logging.getLogger(name or 'xiaojiao')
LOG = get_logger(__name__)

CONTROL = app.CONTROL
MODEL_NAME = app.MODEL_NAME
BRAIN = CONTROL.get("brain", {})
ENGINE = BRAIN.get("engine", "auto")


def resolve_llama_paths():
    """解析大模型路径：控制文件(存在才用) -> 统一解析器（环境变量 XIAOJIAO_LLAMA_SERVER/XIAOJIAO_GGUF
    -> PATH -> 项目/常见目录）。换电脑不用改代码。

    【2026-09-19 收口到 `core.paths`】这里原来自己写了一份查找逻辑，而 `brain_manager.py`、
    `llama-swap.yaml`、两个浏览器自测各自又写了一份 —— 同一件事四份实现，改一处漏三处。
    现在只有一份（`core/paths.py`），本函数只保留"控制文件优先"这一层项目自己的规矩。
    """
    server = BRAIN.get("llama", {}).get("server", "")
    gguf = BRAIN.get("llama", {}).get("gguf", "")
    if not (os.path.exists(server) and os.path.exists(gguf)):
        try:
            from core import paths as _PATHS
            if not os.path.exists(server):
                server = _PATHS.find_llama_server()[0]
            if not (gguf and os.path.exists(gguf)):
                gguf = _PATHS.find_gguf()[0]
        except Exception as e:      # noqa: silent-ok — 解析器出问题就退回下面的老办法
            LOG.debug("统一路径解析不可用，退回本地查找：%s", e)
            if not os.path.exists(server):
                server = shutil.which("llama-server") or ""
                if not server:
                    for d in ("C:/llama", ".", "..", os.path.expanduser("~")):
                        c = os.path.join(d, "llama-server.exe")
                        if os.path.exists(c):
                            server = c
                            break
            if not (gguf and os.path.exists(gguf)):
                gguf = ""
                for d in ("C:/llama", ".", "..", os.path.expanduser("~/Downloads"), os.path.expanduser("~")):
                    if not os.path.isdir(d):
                        continue
                    for fn in sorted(os.listdir(d)):
                        if fn.lower().endswith(".gguf"):
                            gguf = os.path.join(d, fn)
                            break
                    if gguf:
                        break
    return server, gguf

def stop_stray_direct_line(port=None, expect="llama-server"):
    """**收回备用直连线**：llama-swap 已经接管时，把之前那条直连端口上的 llama-server 停掉。

    【为什么必须有这一步（2026-09-18 实测）】
      llama-swap 不在时，应用会退到**直连 8080** 那条备用线（下面的 `start_llama_brain`）。
      等 llama-swap 回来、应用也回到 9292 之后 —— **没有人去关掉那条备用线**：
      "跳过启动"被当成了"已经收好"。实测后果是一个 8080 的 `llama-server` 从 21:57 一直活到
      01:20（我手工杀掉），**两份 4B 权重同时抢 16GB 内存与 8GB 显存**（可用内存只剩 0.15GB），
      一个 token 要 100 秒、"你好"要 205 秒。
      用户对这件事的原话是：**「互相打架是因为没触发切换」** —— 对，缺的就是这个"切回来时收旧线"。

    【安全】**只停"名字/命令行里带 `expect` 的进程"**。8080 上如果蹲着的是别的服务，
      一个字都不许动 —— 宁可留着多余进程，也不许误杀别人。
      取不到 psutil 时用 `netstat + taskkill` 兜底（和 `_stop_swap` 同一套路）。

    返回 `(pid, 说明)`；没找到要停的返回 `(None, 原因)`。
    """
    port = int(port or BRAIN.get("llama", {}).get("port", 8080) or 8080)
    try:
        import psutil
    except Exception as e:      # noqa: silent-ok — 没有 psutil 就用 netstat 兜底
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=15).stdout
            pid = None
            for line in out.splitlines():
                if (":%d" % port) in line and "LISTENING" in line:
                    pid = int(line.split()[-1])
                    break
            if not pid:
                return None, "直连端口 %d 上没有进程（不用收）" % port
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=15)
            return pid, "已按端口 %d 停掉（没有 psutil，按 netstat 取到的 PID）" % port
        except Exception as e2:      # noqa: silent-ok
            return None, "收线失败：%s / %s" % (e, e2)
    try:
        for c in psutil.net_connections(kind="tcp"):
            if not (c.laddr and c.laddr.port == port and c.status == "LISTEN" and c.pid):
                continue
            try:
                p = psutil.Process(c.pid)
                cmd = " ".join(p.cmdline())
                if expect.lower() not in cmd.lower():
                    # ⚠️ 名字对不上 → **绝不动手**，并把这件事说出来
                    return None, ("%d 上那个进程不是 %s（是 %s），**没动它**"
                                  % (port, expect, cmd[:60] or p.name()))
                p.terminate()
                p.wait(timeout=15)
                return c.pid, "已收回备用直连线（%d）" % port
            except Exception as e:      # noqa: silent-ok — 单个进程处理失败就跳过
                return None, "收线时出错：%s" % e
        return None, "直连端口 %d 上没有进程（不用收）" % port
    except Exception as e:      # noqa: silent-ok
        return None, "收线失败：%s" % e


def start_llama_brain():
    """启动本地大模型。小焦脑优先走 llama-swap(9292)；若已在线则跳过冗余8080直连，避免冲突/占显存/卡住。"""
    try:
        api = BRAIN.get("api", {}); burl = (api.get("base_url") or "").lower()
        if "9292" in burl and requests.get("http://127.0.0.1:9292/v1/models", timeout=3).status_code == 200:
            print("✅ 大脑已由 llama-swap(9292) 管理，跳过冗余直连(8080)。")
            # ⚠️ **"跳过启动"不等于"已经收好"** —— 上一轮退到备用线时起的那个进程可能还活着。
            #    不收它就等于两份模型同时活着（实测：一个 token 100 秒）。见上面那个函数的说明。
            _pid, _why = stop_stray_direct_line()
            if _pid:
                print("🧹 已收回备用直连线 8080（pid=%d）：%s" % (_pid, _why))
            elif _why and "没有进程" not in _why:
                print("ℹ️ 备用直连线没有收回：%s" % _why)
            return None
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 55, e)
    server, gguf = resolve_llama_paths()
    port = int(BRAIN.get("llama", {}).get("port", 8080))
    if not (server and gguf and os.path.exists(server) and os.path.exists(gguf)):
        print(f"⚠️ 没找到大模型文件/服务，跳过自动启动（小焦将用自建模型兜底）。")
        return None
    ctx = BRAIN.get("llama", {}).get("ctx", 32768)
    print(f"🧠 正在启动大脑 {MODEL_NAME} (~{os.path.getsize(gguf)/1e9:.1f}GB) ...")
    proc = subprocess.Popen(
        [server, "-m", gguf, "--port", str(port), "-c", str(ctx)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 等待模型就绪
    for _ in range(120):
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                print(f"✅ 大脑 {MODEL_NAME} 已就绪 (port {port})")
                return proc
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 73, e)
        time.sleep(2)
    print(f"⚠️ 大脑启动超时（可能在加载模型），小焦仍会尝试连接。")
    return proc

def start_neko():
    """启动 N.E.K.O. 猫娘(融合进小焦一键启动)。支持两种形态(自动探测, 找不到就跳过, 不阻塞小焦):
      - Steam 版(你实际的): G:\\SteamLibrary\\steamapps\\common\\n.e.k.o
          入口 = 桌面客户端 N.E.K.O.exe; 它会连带拉起 projectneko_server.exe(监听 48911/48912 后端)。
          【主界面是桌面客户端, 不是 web 页面】
      - 源码克隆版: 任意 N.E.K.O-main/launcher.py + .venv
    路径可改(用户下载位置不同): XIAOJIAO_NEKO_DIR 环境变量优先, 其余**自动探测, 不写死**。"""
    import subprocess as _sp
    # 1) 定位 N.E.K.O. 项目根: 优先环境变量 -> Steam 版 -> 源码克隆版候选（含全盘自动探测）
    roots = []
    env_neko = os.environ.get("XIAOJIAO_NEKO_DIR", "")
    if env_neko:
        roots.append(env_neko)
    roots += [
        r"C:\Program Files (x86)\Steam\steamapps\common\n.e.k.o",
        r"C:\Program Files\Steam\steamapps\common\n.e.k.o",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "N.E.K.O"),
        os.path.expanduser("~/N.E.K.O"),
    ]
    # Steam 库可能装在任意盘: 扫各盘 steamapps\common\n.e.k.o
    import string as _str
    for _L in _str.ascii_uppercase:
        for _lib in ("SteamLibrary", "Steam", "Games", "游戏"):
            roots.append(os.path.join(_L + ":\\", _lib, "steamapps", "common", "n.e.k.o"))
            roots.append(os.path.join(_L + ":\\", _lib, "steamapps", "common", "N.E.K.O"))
    # 先找含 N.E.K.O.exe(Steam版) 或 launcher.py(源码版) 的根
    root = None
    for r_ in roots:
        if os.path.exists(os.path.join(r_, "N.E.K.O.exe")):
            root = r_; break
    if not root:
        root = next((r_ for r_ in roots if os.path.exists(os.path.join(r_, "launcher.py"))), None)
    if not root:
        # 上面的常见位置都没命中 → 才做较慢的全盘自动探测（不写死路径）
        try:
            import install_all as _ia
            root = _ia.discover_neko()   # 返回猫娘根目录，或 None
            if root and not (os.path.exists(os.path.join(root, "N.E.K.O.exe"))
                             or os.path.exists(os.path.join(root, "launcher.py"))):
                root = None
        except Exception:
            root = None
    if not root:
        print("⚠️ 未找到 N.E.K.O. 猫娘(设 XIAOJIAO_NEKO_DIR 指向其目录, 或装 Steam 版于 n.e.k.o)")
        return None

    steam_exe = os.path.join(root, "N.E.K.O.exe")            # Steam 版桌面客户端入口
    launcher = os.path.join(root, "launcher.py")             # 源码版入口
    py = os.path.join(root, ".venv", "Scripts", "python.exe")

    def _alive(port):
        try:
            import socket as _s
            s = _s.socket(); s.settimeout(2); s.connect(("127.0.0.1", port)); s.close(); return True
        except Exception:
            return False

    # 2) 确保猫娘已运行: 看桌面客户端进程 + 后端端口
    import subprocess as sp
    def _running(exe):
        for pr in sp.check_output("tasklist /FI \"IMAGENAME eq %s\"" % os.path.basename(exe), text=True, shell=True, errors="ignore").splitlines():
            if os.path.basename(exe).lower() in pr.lower():
                return True
        return False
    # 都在线(客户端+后端)则认为已运行; 否则拉起桌面客户端 N.E.K.O.exe(会连带拉后端)
    if not (_running(steam_exe) or _alive(48911)):
        if os.path.exists(steam_exe):
            _sp.Popen([steam_exe], cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
            print("🐱 [N.E.K.O] Steam 桌面客户端已启动(N.E.K.O.exe, 连带拉起后端 48911/48912)")
        elif os.path.exists(launcher) and os.path.exists(py):
            _sp.Popen([py, "-m", "app.memory_server"], cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
            _sp.Popen([py, "-m", "app.main_server"], cwd=root, creationflags=subprocess.CREATE_NO_WINDOW,
                      env={**os.environ, "PYTHONUTF8": "1"})
            print("🐱 [N.E.K.O] 源码版已启动(memory_server:48912 + main_server:48911)")
        else:
            print("⚠️ [N.E.K.O] 在 %s 但既无 N.E.K.O.exe 也无可用 launcher.py/.venv, 跳过自动拉起" % root)
            return root
    else:
        print("🐱 [N.E.K.O] 已在运行(N.E.K.O.exe + 后端 48911/48912)")

    # 3) 后台学习通道(每 5 分钟学一次你与猫娘的对话)
    try:
        learn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_from_neko.py")
        if os.path.exists(learn):
            _sp.Popen([sys.executable, learn, "--daemon", "--interval", "300"],
                      cwd=os.path.dirname(os.path.abspath(__file__)), creationflags=subprocess.CREATE_NO_WINDOW)
            print("🎓 [N.E.K.O] 后台学习通道已启动(每5分钟学你与猫娘的对话)")
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 166, e)
    return root


def start_llama_swap():
    """自动启动 llama-swap(多大脑热切换管理器)。独立端口9292, 不冲突直接大脑8080。
    路径自动探测(不写死, 兼容移动位置): 环境变量 → 项目目录 → 全盘扫描。"""
    # ⚠️ 测试克隆 / CI **不许**起 llama-swap（真实事故）：克隆目录里也有一份
    #    llama-swap.yaml，一旦它把 9292 占了，真正的小焦之后每次启动都会因为
    #    "9292 已被占用"而跳过自己的配置 —— 大脑就停在那份**克隆的旧配置**上，
    #    用户新加的模型在里面根本不存在（选了就 404/500，看着就是"用不了"）。
    #    `tools/test_fresh_clone.py` 会带上这个环境变量。
    if os.environ.get("XIAOJIAO_NO_SWAP") == "1":
        print("  [llama-swap] 按 XIAOJIAO_NO_SWAP=1 跳过（测试克隆不抢 9292）")
        return None
    env_exe = os.environ.get("XIAOJIAO_LLAMA_SWAP", "")
    cands = [env_exe] if env_exe else []
    _here = os.path.dirname(os.path.abspath(__file__))
    cands += [os.path.join(_here, "llama-swap.exe"),
              os.path.join(_here, "llama-swap", "llama-swap.exe")]
    exe = next((c for c in cands if c and os.path.exists(c)), "")
    if not exe:
        # 全盘自动探测兜底（关键词 + 有限深度 + where /r）
        try:
            import install_all as _ia
            exe = _ia.discover_exe("llama-swap.exe", ("llama-swap", "swap", "秒切", "大脑")) or ""
        except Exception:
            exe = ""
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llama-swap.yaml")
    if not (exe and os.path.exists(cfg)):
        print("  [llama-swap] 未找到(exe或配置)，跳过 —— 聊天大脑不会跟起，请设 XIAOJIAO_LLAMA_SWAP 或检查 llama-swap.exe")
        return None
    print("  [llama-swap] exe: %s" % exe)
    try:
        import socket
        s = socket.socket(); s.settimeout(0.8)
        try:
            s.connect(("127.0.0.1", 9292)); s.close()
            print("  [llama-swap] 已在运行(9292)"); return None
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 198, e)
        finally:
            s.close()
        proc = subprocess.Popen([exe, "--config", cfg, "--listen", "127.0.0.1:9292"],
                                cwd=os.path.dirname(exe), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  [llama-swap] 已启动(9292) —— 多大脑秒级切换管理")
        return proc
    except Exception as e:
        print("  [llama-swap] 启动失败: %s" % e); return None


def ask_start_neko():
    """询问是否启动 N.E.K.O. 猫娘（可选；不启动不影响小焦本体）。
    设环境变量 XIAOJIAO_NEKO_AUTO=1 可免询问直接启动(自动化用)；非交互环境默认不启动。"""
    if os.environ.get("XIAOJIAO_NEKO_AUTO") == "1":
        return True
    try:
        ans = input("🐱 是否启动 N.E.K.O. 猫娘桌面伙伴？(可选，不启动不影响小焦) [Y/n]: ").strip().lower()
    except Exception:
        return False   # 被脚本/后台调用(非交互)时不擅自拉起猫娘
    return ans in ("", "y", "yes", "是", "1")


def start_carrier():
    """变形金刚：启动时**扫描能力 + 注册火种**（第 6 部分）。

    【为什么要在启动时做】这两件事都是"把当前世界的样子读进来"：
      · 能力扫描：用户随时往 `plugins/` 丢新 .py/.json/.md，工具数就变 ——
        不扫就还是旧清单，"用户加什么工具它就会什么"这句话就不成立；
      · 火种注册：模型是可替换的零件，注册表是"有哪些零件可用"的花名册，
        出问题时三级治疗要能从这里拿备用火种。
    【去掉它会怎样】能力清单停在常量上（新插件要重启才认），
    健康系统的"切备用火种"永远无火种可切 —— 变形金刚变不了形。
    全程 try/except：能力/火种读不出来不影响小焦本体启动。
    """
    info = {"tools": 0, "source": "", "brains": []}
    try:
        from core.carrier import BrainRegistry, CapabilityRegistry
    except Exception as e:      # noqa: silent-ok — 载体层不可用也要能启动
        print("  [载体] 变形金刚模块不可用（跳过）：%s" % e)
        return info
    try:
        cap = CapabilityRegistry()
        r = cap.scan()
        info["tools"], info["source"] = r.get("count", 0), r.get("source", "")
        cap.manifest()
        print("  [载体] 能力已扫描：%d 个工具（来源=%s，插件目录=%s）—— 上限不封顶，丢新插件即生效"
              % (info["tools"], info["source"], r.get("files", 0)))
    except Exception as e:      # noqa: silent-ok — 扫描失败不影响启动
        print("  [载体] 能力扫描失败（跳过）：%s" % e)
    try:
        reg = BrainRegistry()
        info["brains"] = reg.names()
        cur = reg.current()
        print("  [载体] 火种已注册：%d 个%s —— 当前=%s"
              % (len(info["brains"]), ("（%s）" % "、".join(info["brains"][:4])),
                 (cur.name if cur else "未指定")))
        if len(info["brains"]) < 2:
            print("  [载体] 提示：只登记了 1 个火种，健康系统三级治疗时将无备用火种可切"
                  "（在 xiaojiao_control.json 的 brains 里多配一个即可）")
    except Exception as e:      # noqa: silent-ok — 同上
        print("  [载体] 火种注册失败（跳过）：%s" % e)
    return info


def start_autonomy():
    """自主性：启动后台调度/学习/盯梢（第 4 部分）。

    【为什么默认是关的】自主性会在后台花用户的额度与带宽（抓网页、跑模型）——
    这种事必须用户点头，不能替用户决定。`xiaojiao_control.json` 里
    `autonomy.enabled=true` 才起；没配就是一个线程都不起，并**如实说明**怎么打开。
    【为什么这里返回统计】"用户不说 → 也在做事"是它活着的证据；
    启动时把"起了几个任务、盯了几个源"打出来，用户才知道它到底在不在干活。
    """
    try:
        from core.autonomy import start_all
        r = start_all(app.CONTROL)
        if not r.get("enabled"):
            print("  [自主性] 未启用（%s）—— 想让它自己在后台做事，把 xiaojiao_control.json 的 "
                  "autonomy.enabled 设为 true（tasks/watchers 一起配）" % (r.get("reason") or "enabled=false"))
        else:
            print("  [自主性] 已启用：定时任务 %s 个 / 盯梢源 %s 个"
                  % (r.get("tasks", 0), r.get("watchers", 0)))
        return r
    except Exception as e:      # noqa: silent-ok — 自主性起不来不影响小焦本体
        print("  [自主性] 启动失败（跳过）：%s" % e)
        return {"enabled": False, "reason": str(e)[:80]}


def stop_autonomy():
    """退出时**优雅关闭**自主性线程（不优雅关闭会留下半截状态的盯梢文件）。"""
    try:
        from core.autonomy import stop_all
        r = stop_all(timeout=3)
        print("  [自主性] 已优雅关闭：%s" % (r,))
    except Exception as e:      # noqa: silent-ok — 关不掉也得让主进程退出（线程本来就是 daemon）
        print("  [自主性] 关闭时出错（忽略）：%s" % e)


def start_heartbeat():
    """心跳：**模型启动 → 心跳开始**，一直到进程结束。

    【为什么和别的后台线程不一样，是"必起"的】自主性、世界层都可以关，
    心跳不能 —— 它是"它一直在"的唯一证明：挂起（睡着）时大脑不推理、载体不跑任务，
    全机只剩下这一条线程还在跳。不起它，"睡着不是死"就只是句口号。
    代价极小：一个 daemon 线程，每 5 秒写一行日志，不调模型、不占显存。
    """
    try:
        from core import heartbeat as hb
        r = hb.start(why="start_xiaojiao 启动")
        print("  [心跳] 已开始：每 %ss 一下%s —— 挂起时它**不停**（%s）"
              % (hb.BEAT_INTERVAL, "（已在跳）" if not r.get("started") else "", hb.path()))
        return r
    except Exception as e:      # noqa: silent-ok — 心跳起不来也要能启动，如实说
        print("  [心跳] 启动失败（跳过）：%s" % e)
        return {"started": False, "why": str(e)[:80]}


def stop_heartbeat():
    """退出时停心跳（**只有整个系统下线才停** —— 挂起不停，见 `core/heartbeat.py`）。"""
    try:
        from core import heartbeat as hb
        ok = hb.stop(why="start_xiaojiao 退出")
        print("  [心跳] 已停：%s" % ok)
    except Exception as e:      # noqa: silent-ok
        print("  [心跳] 停止时出错（忽略）：%s" % e)


def start_world():
    """世界层：起**自主探索器**（从"人给地图"改成"自己啃互联网"）。

    【为什么默认是开的（和自主性相反）】自主性默认关，因为它会花用户的**模型额度**；
    而世界探索花的是**带宽**，且有硬预算（daily_budget）、硬间隔（explore_speed=slow）、
    禁区名单 —— 代价小、可预期。更关键的是：**不主动探索，世界层就是一张空地图**，
    "它一直在啃互联网"这件事就无从谈起（用户明确要的就是这个）。
    所以要关就显式关：`world.explore_enabled=false`。
    """
    try:
        from core.world import maybe_start as _world_start
        r = _world_start(app.CONTROL)
        if not r.get("enabled"):
            print("  [世界层] 自主探索未启用（%s）" % (r.get("reason") or "explore_enabled=false"))
            return r
        st = r.get("status") or {}
        print("  [世界层] 自主探索已启动：空闲 %ss 后开啃 ｜ 速度=%s ｜ 今日预算剩 %s ｜ 地图里已有 %s 个站"
              % (st.get("idle_seconds", "?"), st.get("speed"), st.get("budget_left"),
                 st.get("model_sites")))
        return r
    except Exception as e:      # noqa: silent-ok — 世界层起不来不影响小焦本体
        print("  [世界层] 启动失败（跳过）：%s" % e)
        return {"enabled": False, "reason": str(e)[:80]}


def stop_world():
    """退出时停掉探索线程（它在抓网页，得让它把手上的活收干净）。"""
    try:
        from core.world import stop_all as _world_stop
        print("  [世界层] 已停止探索：%s" % (_world_stop(timeout=3),))
    except Exception as e:      # noqa: silent-ok — 停不掉也得让主进程退出（线程本来就是 daemon）
        print("  [世界层] 停止时出错（忽略）：%s" % e)


def main():
    print("=" * 50)
    print("  小焦 · XiaoJiao")
    print(f"  模型名: {MODEL_NAME}")
    print(f"  大脑:   {ENGINE}")
    print("=" * 50)

    # 2b. 先拉起 llama-swap(9292), 让大脑由它管理(8080直连会检测到9292后自动跳过)
    llama_swap_proc = start_llama_swap()

    # 2. 启动大模型大脑(若9292在线则跳过冗余8080, 不再卡)
    llama_proc = None
    if ENGINE in ("auto", "llama"):
        llama_proc = start_llama_brain()

    # 3. 确定 Web 端口
    port = 5000
    if "--port" in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        except Exception:
            port = 5000
    else:
        port = int(CONTROL.get("web_port", os.environ.get("PORT", 5000)))
    os.environ["PORT"] = str(port)

    # 3c. N.E.K.O. 猫娘（可选）：先询问用户；不启动也不影响小焦本体
    neko_root = None
    if ask_start_neko():
        neko_root = start_neko()
    else:
        print("🐱 已跳过 N.E.K.O. 猫娘（不影响小焦启动；想开时单独运行本脚本并选 y 即可）")

    # 3d. 载体层：扫描能力 + 注册火种（变形金刚）→ 启动自主性（后台 daemon 线程）
    #     顺序有意：先把"有哪些能力、有哪些火种"读进来，再放后台任务出去跑 ——
    #     反过来的话，自主任务的第一轮会拿着一份还没注册的空火种表去干活。
    start_carrier()
    start_autonomy()
    # 3e. 世界层：自己啃互联网（空闲就开啃；有预算、有间隔、有禁区名单）
    start_world()
    # 3f. 心跳：**一直在**的那个证明。挂起时别的全停，只有它不停。
    start_heartbeat()

    # 4. 打开浏览器
    _host, _host_lines = app.bind_host(port)      # 与 main() 共用同一套监听规则，见该函数说明
    print(f"🌐 启动小焦 Web: http://127.0.0.1:{port}")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    for _line in _host_lines:
        print("  " + _line)
    # N.E.K.O. 猫娘: Steam 桌面客户端(不是 web 页面)。start_neko 已确保拉起它。
    if neko_root:
        print("🐱 N.E.K.O. 猫娘桌面客户端已就绪 (Steam 客户端 / N.E.K.O.exe)")

    # 5. 启动 Web 服务（阻塞在这里）
    # 以前这里写死 host="0.0.0.0" —— 把任务 1 的「默认只听本机 + 令牌鉴权」整个绕过去了，
    # 实测同网段无令牌就能打开小焦（安全第一批·任务 A 修）。
    try:
        app.app.run(host=_host, port=port, debug=False, use_reloader=False)
    finally:
        # 清理所有子进程
        stop_autonomy()          # 先优雅关掉自主性线程（有序收尾，别留下半截盯梢状态）
        stop_world()             # 再停世界层（它可能正在抓网页，先收干净）
        stop_heartbeat()         # 最后停心跳：**只有整个系统下线才停**（挂起不停）
        if llama_proc:
            try:
                llama_proc.kill()
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 270, e)
        print("🛑 所有服务已关闭。")

if __name__ == "__main__":
    main()
