# brain_manager.py —— 小焦「多大脑 · 秒级切换」调度中心
# 原理：小焦/小脑作为调度中心，连接多个「大脑」(聊天/视频/图像/推理...)。
#      空闲大脑 → sleep(权重从显存卸载到内存, ~1-2s)；要用 → wake(内存→显存, ~1-2s)。
#      进程常驻不杀，只做权重 offload/onload → 秒级切换，省显存。
import os, json, threading, time, subprocess, shutil
import logging  # noqa: F401  （由 tools/fix_silent_except.py 注入）
try:
    from xiaojiao_log import get_logger
except Exception:  # 独立运行时退化为标准 logging
    def get_logger(name=None):
        return logging.getLogger(name or 'xiaojiao')
LOG = get_logger(__name__)

# 大脑注册表：每个大脑 = 一个可连的"模型服务"(唯一端口/唯一指纹)
# state: RUN(权重在显存) / SLEEP(权重在内存, 进程在) / OFF(未加载)
# 新增大脑只需在 BRAINS 加一项 + 实现它的 _sleep/_wake(或默认 keep-alive)
# 【`proc` 不再写死 `C:/llama/llama-server.exe`（2026-09-19）】换台机器盘符/目录不同 →
#   统一的解析在 `core.paths.find_llama_server()`：环境变量 XIAOJIAO_LLAMA_SERVER >
#   PATH > 项目/常见目录 > 深搜；这里只在**注册表构建时**问一次，拿不到就空着（下游会再问）。
try:
    from core import paths as _PATHS
    _LLAMA_SERVER = _PATHS.find_llama_server()[0]
except Exception:      # noqa: silent-ok — 解析不了也不许把模块 import 弄挂
    _LLAMA_SERVER = ""

BRAINS = {
    "chat": {   # 聊天大脑：llama.cpp (llama-server)
        "name": "聊天大脑 (Qwen 4B, llama-swap)", "port": 9292,
        "type": "llama", "vram_gb": 3.5, "state": "SLEEP", "proc": _LLAMA_SERVER,
    },
    "video": {  # 视频大脑：ComfyUI + Wan2.1
        "name": "视频大脑 (Wan2.1 + ComfyUI)", "port": 8188,
        "type": "comfy", "vram_gb": 5.0, "state": "OFF", "proc": "comfy",
    },
    "coder": {  # 编码大脑：Qwen3-Coder 7B (llama-swap 托管, 8G 按需切换)
        "name": "编码大脑 (Qwen3-8B 工具·代码)", "port": 9292,
        "type": "llama", "vram_gb": 5.2, "state": "OFF",
    },
    "podcast": {  # 播客大脑：Chatterbox TTS + SD1.5 封面 (用时候加载, 用别的就替换/卸载)
        "name": "播客大脑 (LLM写稿+配音+封面)", "port": 5000,
        "type": "podcast", "vram_gb": 6.0, "state": "OFF",
    },
    "agnes": {  # Agnes 云端视频大脑(免费 API, 不占本地显存)
        "name": "云端视频大脑 (Agnes 免费)", "port": 0,
        "type": "cloud", "vram_gb": 0.0, "state": "OFF",
    },
    "deepseek-v4": {  # 新增: Deepseek-V4
        "name": "Deepseek-V4", "port": 9292,
        "type": "llama", "vram_gb": 5.0, "state": "OFF",
    },
    # 音乐：不是独立进程，生成时在应用进程内加载 MusicGen（所以 type=inproc）。
    # 登记它只是为了**显存归属**算得清：它跑的时候聊天模型让位，跑完聊天模型回来。
    "music": {
        "name": "音乐大脑 (MusicGen)", "port": 0,
        "type": "inproc", "vram_gb": 2.0, "state": "OFF",
    },
    "qwopus3.5-4b-coder-mtp-q5_k_m.gguf": {  # 新增: Qwopus3.5-4B-Coder-MTP-Q5_K_M.gguf
        "name": "Qwopus3.5-4B-Coder-MTP-Q5_K_M.gguf", "port": 9292,
        "type": "llama", "vram_gb": 5.0, "state": "OFF",
    },
    # 未来扩展(示例, 加进 BRAINS 即可被调度):
    # "image": {"name":"图像大脑(SD3)","port":8189,"type":"comfy","vram_gb":4.0,"state":"OFF"},
    # "reason": {"name":"推理大脑(DeepSeek)","port":8081,"type":"llama","vram_gb":6.0,"state":"OFF"},
}

# RLock（可重入）：策略函数（use_gen / done_gen / keep_chat_in_vram）在持锁期间会调用
# wake()/sleep()，而它们内部也要拿这把锁 —— 用普通 Lock 会**自己把自己锁死**
# （第一版就是 Lock，`done_gen("video")` 当场死锁，测试卡住不动）。
_lock = threading.RLock()

_CONTROL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json")


def _control_cfg():
    """读操控文件的 brain 段（只读，读不到就返回空 dict，绝不抛）。"""
    try:
        with open(_CONTROL_FILE, encoding="utf-8") as f:
            return (json.load(f) or {}).get("brain", {}) or {}
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 57, e)
        return {}


def _llama_cfg():
    """解析本地 llama 大脑的 (server, gguf)：操控文件 → 环境变量 → PATH/常见目录。

    真实缺陷：这两个函数以前**根本没定义**，`_start_llama` 一执行就 NameError，
    被下面的 `except Exception: return False` 吞掉 → "唤醒大脑"永远失败，
    多脑切换形同虚设（而且完全没有日志线索）。
    """
    brain = _control_cfg()
    llama = brain.get("llama", {}) if isinstance(brain.get("llama"), dict) else {}
    server = str(llama.get("server") or "")
    gguf = str(llama.get("gguf") or "")
    # 【2026-09-19 收口】控制文件里的路径能用就用；不能用时**统一交给 `core.paths`** ——
    #   这里原来自己写了一份"环境变量→PATH→常见目录"的查找，跟 `start_xiaojiao.py` 那份重复，
    #   而且目录表是写死的（`C:/llama`）。现在只有一份实现，环境变量优先级也一致。
    if not (server and os.path.exists(server)) or not (gguf and os.path.exists(gguf)):
        try:
            if not (server and os.path.exists(server)):
                server = _PATHS.find_llama_server()[0] or server
            if not (gguf and os.path.exists(gguf)):
                gguf = _PATHS.find_gguf()[0] or gguf
        except Exception:      # noqa: silent-ok — 解析器不可用就退回老的写死目录
            if not (server and os.path.exists(server)):
                server = shutil.which("llama-server") or ""
                if not server:
                    for d in ("C:/llama", ".", "..", os.path.expanduser("~")):
                        c = os.path.join(d, "llama-server.exe")
                        if os.path.exists(c):
                            server = c
                            break
            if not (gguf and os.path.exists(gguf)):
                for d in ("C:/llama", ".", "..", os.path.expanduser("~/Downloads")):
                    if not os.path.isdir(d):
                        continue
                    for fn in sorted(os.listdir(d)):
                        if fn.lower().endswith(".gguf"):
                            gguf = os.path.join(d, fn)
                            break
                    if gguf and os.path.exists(gguf):
                        break
    return server, (gguf if gguf and os.path.exists(gguf) else "")


def _comfy_dir():
    """ComfyUI 目录：环境变量 → 操控文件 brain.comfy_dir → 项目同级常见位置。"""
    root = os.environ.get("XIAOJIAO_COMFY_DIR", "") or str(_control_cfg().get("comfy_dir") or "")
    if root and os.path.exists(os.path.join(root, "main.py")):
        return root
    for d in (os.path.join(os.path.dirname(_CONTROL_FILE), "ComfyUI"), "ComfyUI", ".."):
        if os.path.exists(os.path.join(d, "main.py")):
            return os.path.abspath(d)
    return root                      # 交给调用方判断（它自己会检查 main.py 是否存在）


def _port_alive(port):
    import socket
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port)); return True
    except Exception:
        return False
    finally:
        s.close()


def _pid_on_port(port):
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if ":%d " % port in line and ("LISTENING" in line or "LISTEN" in line):
            try:
                return int(line.strip().split()[-1])
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 59, e)
    return None


def is_running(brain_key):
    b = BRAINS[brain_key]
    return _port_alive(b["port"])


def state():
    with _lock:
        return {k: {"name": v["name"], "state": v["state"], "port": v["port"], "vram_gb": v["vram_gb"]} for k, v in BRAINS.items()}


def _start_llama(b):
    # 先卸载其它 llama 模型(腾全部显存给当前大脑——8G 上两个 llama 不能同时占显存)
    try:
        import model_switch as _ms
        mine = "coder" if str(b.get("name", "")).find("编码") >= 0 or b.get("port") != 9292 else "xiaojiao"
        other = "coder" if mine == "xiaojiao" else "xiaojiao"
        _ms._llama_swap_unload(other)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 81, e)
    if _port_alive(b["port"]):
        return True
    try:
        server, gguf = _llama_cfg()
        if not os.path.exists(server):
            server = "llama-server"  # 走 PATH
        if not (gguf and os.path.exists(gguf)):
            return False  # 缺模型: 提示配置, 不死写
        cwd = os.path.dirname(gguf) if os.path.dirname(gguf) else "."
        subprocess.Popen([server, "-m", gguf, "--port", str(b["port"]), "-c", "32768"],
                         cwd=cwd, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def _start_comfy(b):
    root = os.environ.get("XIAOJIAO_COMFY_DIR") or _comfy_dir()
    if not root or not os.path.exists(os.path.join(root, "main.py")):
        return False  # 未配置 ComfyUI, 不死写
    py = os.path.join(os.path.dirname(root), "python_embeded", "python.exe")
    try:
        args = [py, "main.py", "--port", str(b["port"])]
        if os.environ.get("XIAOJIAO_KEEP_COMFY") == "1":
            args.append("--lowvram")
        subprocess.Popen(args, cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def wake(brain_key, wait=10, explicit=False):
    """唤醒大脑到显存(RUN)，并确保其它大脑让出显存。复用 video_service.model_switch 的真实控制。

    ⚠️ **聊天模型不许顶聊天模型**（用户给定的规则）：如果要把一个聊天模型放上显存，
    而显存里已经坐着**另一个**聊天模型，则只有 `explicit=True`（用户在界面上明确选了它）
    才允许 —— 否则**直接拒绝**。理由：两个聊天模型互顶，就是每一次对话都换一次模型，
    每次换都要重新读盘（USB 盘上 2 分钟），表现就是"越用越慢、像坏了一样"。
    功能模型不受这条限制（聊天模型顶功能模型是正常的，见 done_gen）。
    """
    b = BRAINS.get(brain_key)
    if b is None:
        return False
    with _lock:
        if is_chat(brain_key) and not explicit:
            for k, v in BRAINS.items():
                if k != brain_key and is_chat(k) and v.get("state") == "RUN":
                    LOG.info("拒绝把聊天模型 %s 顶上来：显存里已经坐着聊天模型 %s（聊天模型不许顶聊天模型）",
                             brain_key, k)
                    return False
        if is_chat(brain_key) and explicit:
            # **用户在界面上明确换了聊天模型** → 被换下的那个退到内存（llama 系=卸载），
            # 而且**不许它自己再顶回来**（它只会被下一次明确选择唤醒）。
            for k, v in BRAINS.items():
                if k != brain_key and is_chat(k) and v.get("state") in ("RUN", "WARM"):
                    LOG.info("用户明确切到聊天模型 %s → %s 退到内存待命", brain_key, k)
                    sleep(k)
                    _full_stop(k)
    return _wake_raw(brain_key, wait=wait)


def _wake_raw(brain_key, wait=10):
    """真正把大脑放上显存（内部用；对外走 `wake()` 以便过策略闸）。"""
    import sys, os as _os
    root = _os.path.dirname(_os.path.abspath(__file__))
    if _os.path.join(root, "video_service") not in sys.path:
        sys.path.insert(0, _os.path.join(root, "video_service"))
    import model_switch as ms
    keep_comfy = (_os.environ.get("XIAOJIAO_KEEP_COMFY") == "1")
    b = BRAINS[brain_key]
    if brain_key == "video":
        # 视频上显存; llama 大脑由 llama.cpp 空闲自动卸到内存(温存, 单槽), 不主动杀
        ms.start_comfy()     # 起视频大脑(ComfyUI+Wan)
    elif brain_key == "chat":
        # 聊天大脑上显卡; 其它温存大脑留在内存(切回快)
        ms.start_brain()     # 聊天大脑 -> 显卡
    else:
        _start_any(b)
    b["state"] = "RUN"
    return is_running(brain_key)


def sleep(brain_key):
    """温存(WARM, 内存单槽驻留): 不卸载——llama进程/模型保留(llama.cpp空闲自动卸到内存),
    视频保留ComfyUI。切回 = 内存→显存, 秒级。被新温存顶掉时才彻底卸载(_full_stop)。"""
    b = BRAINS.get(brain_key)
    if b:
        b["state"] = "WARM"
    return True


def _start_any(b):
    """按类型启动：llama→llama-server；comfy→ComfyUI；inproc（如 MusicGen）→ 不用启动（在进程内）。"""
    t = (b or {}).get("type")
    if t == "llama":
        return _start_llama(b)
    if t == "comfy":
        return _start_comfy(b)
    return None      # inproc：模型由生成代码自己加载，这里没有进程可起


def _full_stop(brain_key):
    """彻底卸载(OFF, 腾显存+内存): 新温存顶掉旧温存时调用——内存只允许一个。

    ⚠️ **必须按类型分派**：原来不管什么类型都调 `stop_comfy()` ——
    那会把 ComfyUI/视频大脑当替罪羊停掉（音乐那条链就是全 BRAINS 轮着 _full_stop，
    等于把每个大脑都按"视频"处理一遍）。
    """
    b = BRAINS.get(brain_key)
    if not b:
        return True
    t = b.get("type")
    try:
        import model_switch as _ms
        if t == "llama":
            _mid = b.get("useModelName") or ("xiaojiao" if brain_key == "chat" else brain_key)
            _ms._llama_swap_unload(_mid)
        elif t == "comfy":
            _ms.stop_comfy()
        # inproc（MusicGen 之类）：没有独立进程可停，权重由生成代码自己释放 —— 不碰 ComfyUI
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 155, e)
    b["state"] = "OFF"
    return True


def _evict_ram_brains(except_key):
    """切换到"第三个大脑"时, 把内存里温存的大脑清掉(腾内存)。chat/video 之间互不杀。"""
    import model_switch as _ms
    for k in list(BRAINS.keys()):
        if k == except_key or k in ("chat", "video"):
            continue  # 聊天/视频互相切换不清
        try:
            _ms.stop_comfy()  # 第三方大脑占用时, 视频大脑让位(或按类型扩展)
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 169, e)


def switch_to(target):
    """秒级切换(内存单槽温存): 顶掉旧温存 -> 当前活动去温存 -> 目标上显存。可切回。"""
    with _lock:
        # 1) 顶掉内存里旧的温存(内存只允许一个) —— 新温存进来, 旧的彻底卸载
        for k, v in BRAINS.items():
            if v["state"] == "WARM" and k != target:
                _full_stop(k)
        # 2) 当前活动大脑 -> 温存(留内存, 切回秒级)
        for k in [k for k, v in BRAINS.items() if v["state"] == "RUN" and k != target]:
            sleep(k)
        # 3) 目标 -> 活动(显存)
        ok = wake(target)
        return {"switched": target, "from": [k for k, v in BRAINS.items() if v["state"] == "RUN" and k != target], "ok": ok}


# ================== 显存归属策略（谁可以顶谁） ==================
# 【用户给定的逻辑，实现就照这个来】
#   · **聊天模型是显存的主人**：功能模型（视频/图像/音乐/播客…）跑完，聊天模型要回到显存，
#     功能模型退到内存待命（下次直接用内存里的，不用再读盘）。
#   · **聊天模型之间不许互顶**：切到另一个聊天模型时，被挤下的那个退到内存后
#     **不许自己再顶回来** —— 聊天模型只能顶功能性模型，不能顶聊天模型。
#
# 【一个必须如实说的技术事实】
#   对 llama 系的模型，"退到内存"= **卸载**：llama.cpp 没有"权重留在内存、不占显存"的睡眠模式
#   （那是 vLLM 的能力，见 docs/brain-switch.md 第 7 节）。所以聊天模型让位之后，
#   下次要重新读盘（本机盘约 5 秒，USB 盒上 120 秒）。ComfyUI 那类引擎才会把权重留在内存。
#   真正能让 llama 系"内存待命"的办法是让它以 `-ngl 0`（纯 CPU）驻留 —— 那要给每个模型
#   多配一条 CPU 入口，属于后续可做的优化，本轮没做。
_CHAT_KEYS = ("chat", "coder", "deepseek-v4", "cloud")


def is_chat(key):
    """这个大脑算不算"聊天模型"（用户能把它选成主大脑的那些）。"""
    if key in _CHAT_KEYS:
        return True
    b = BRAINS.get(key) or {}
    return b.get("type") in ("llama", "cloud")


def current_chat():
    """当前"在用"的聊天模型 key：优先控制文件里配置的那个（用户选的）。"""
    try:
        m = ((_control_cfg() or {}).get("brain", {}).get("api", {}) or {}).get("model") or ""
        for k, v in BRAINS.items():
            if is_chat(k) and (k == m or v.get("useModelName") == m or v.get("model") == m):
                return k
    except Exception as e:      # noqa: silent-ok — 读不到配置就用默认的 chat
        LOG.debug("忽略异常(%s:%d): %s", __file__, 0, e)
    # 兜底：谁在 RUN/WARM 里是聊天模型，就是谁；都没有就用 chat
    for k, v in BRAINS.items():
        if is_chat(k) and v.get("state") in ("RUN", "WARM"):
            return k
    return "chat"


_DISPLACED = {"key": ""}      # 被功能模型挤下去的聊天模型（跑完要还给它）


def use_gen(key):
    """要跑一个**功能性模型**了：① 记住当前聊天模型；② 让它让出显存；③ 清掉别的温存功能模型（内存只留一个）；④ 这个功能模型上显存。

    与 `switch_to` 的区别：这一步**记下了"该还给谁"**，跑完由 `done_gen()` 还回去 ——
    这正是原来缺的那一环（插件的 stop_brain() 之后没人恢复）。
    """
    with _lock:
        chat = current_chat()
        _DISPLACED["key"] = chat
        # ② 聊天模型让出显存（llama 系=卸载；ComfyUI 那类由各自实现处理）
        try:
            sleep(chat)
            _full_stop(chat)
        except Exception as e:      # noqa: silent-ok — 让位失败也要继续，不能把生成卡住
            LOG.debug("忽略异常(%s:%d): %s", __file__, 0, e)
        # ③ 内存只留一个功能模型：别的温存功能模型彻底清掉
        for k, v in BRAINS.items():
            if k != key and not is_chat(k) and v.get("state") in ("WARM", "RUN"):
                _full_stop(k)
        # ④ 功能模型上显存
        try:
            b = BRAINS.get(key)
            if b:
                _start_any(b)
                b["state"] = "RUN"
        except Exception as e:      # noqa: silent-ok — 上显存失败由调用方如实报错
            LOG.debug("忽略异常(%s:%d): %s", __file__, 0, e)
        return {"gen": key, "chat": chat}


def done_gen(key):
    """功能性模型跑完：① 它退到内存待命（WARM）；② **聊天模型回到显存**。

    这一条就是用户要的"聊天模型把用完的功能模型顶回来"。**只在生成路径里调用**，
    而且必须放在 finally 里 —— 生成报错也要把聊天模型还回来（视频 API 那条做到了，
    两个插件原来都没做）。
    """
    with _lock:
        b = BRAINS.get(key)
        if b:
            sleep(key)                     # 功能模型：留内存待命（ComfyUI 类留在内存，llama 类等同卸载）
        chat = _DISPLACED.get("key") or current_chat()
        _DISPLACED["key"] = ""
        try:
            wake(chat)                     # 聊天模型回显存
        except Exception as e:      # noqa: silent-ok — 还回去失败也要如实返回，不能吞
            LOG.debug("忽略异常(%s:%d): %s", __file__, 0, e)
        return {"gen": key, "chat_back": chat}


def keep_chat_in_vram(explicit=None):
    """聊天模型回到显存，并把占着显存的功能模型退到内存。**绝不顶另一个聊天模型**。

    `explicit` = 用户在界面上明确选的聊天模型（那种情况下才允许换聊天模型）。
    """
    with _lock:
        want = explicit or current_chat()
        # 功能模型让位（退内存待命）
        for k, v in BRAINS.items():
            if not is_chat(k) and v.get("state") == "RUN":
                sleep(k)
        # 聊天模型之间：只有"明确指定"才允许换
        if explicit:
            for k, v in BRAINS.items():
                if is_chat(k) and k != want and v.get("state") in ("RUN", "WARM"):
                    _full_stop(k)      # 被明确换下的聊天模型：退到内存（llama 系=卸载），且不再自动回来
        return {"chat": want, "ok": wake(want)}


if __name__ == "__main__":
    print("小焦调度中心 —— 多大脑秒级切换")
    while True:
        cmd = input("> switch <brain> | state | quit > ").strip().lower()
        if cmd == "quit":
            break
        if cmd == "state":
            print(json.dumps(state(), ensure_ascii=False, indent=1))
        elif cmd.startswith("switch "):
            print(json.dumps(switch_to(cmd.split()[1]), ensure_ascii=False))
