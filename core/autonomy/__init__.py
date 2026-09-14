# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自主性（自主 1：它活着 —— 不等你开口也在做事）

定位：前面几个包（memory_vec / retriever / continuation）解决的是"**用户问了**之后，
小焦怎么答得又多又好"。这一个解决的是另一个方向的问题：**用户不说话的时候，小焦在干什么。**

设计意图（这套东西为什么存在）：
  · 用户说「帮我盯着这个页面」→ 要的是**一直盯**，不是盯一次就完事；
  · 用户什么都不说 → 小焦也应该在分析我们聊过什么、去补自己不懂的东西。
    这件"没人要求也在做"的事，就是它**活着**的证据，而不是一个等回车键的工具。

本包三个器官：
  scheduler.py  时间轴 —— 到点就做事（cron / interval / idle 三种触发）
  learner.py    好奇心 —— 分析对话历史，提炼高频话题，主动去学，存进记忆
  watcher.py    注意力 —— 盯着配置里关心的源，一变就记录 + 通知

三条铁律（后台任务绝不能拖垮主对话）：
  ① 所有循环都是 **daemon 线程**：主进程退出时它们自动结束，不会挂住 Flask / 网页端。
  ② 每一步都 try/except 吞异常并落日志：后台崩了只是"少做一件事"，绝不影响用户这次对话。
  ③ 网络调用一律带超时、失败**不重试到死**：一次失败就等下一个周期，绝不空转烧钱。

为什么 __init__ 里放这几个小工具函数（而不是每个模块各写一份）：
  三个模块都要做同样三件事 —— 读操控文件、拿落盘目录、追加一行 JSONL。
  各写一份的结果是"三份略有差异的配置读取"，早晚会出现"调度器认 autonomy.enabled、
  学习者不认"这种灵异现象。放这里统一，去掉它就等于把配置语义撕成三份。

数据落盘一律在 `logs/autonomy/` 下（`logs/` 已被 .gitignore 忽略，不脏仓库）。
"""
import json
import os
import threading
import time

# 仓库根：core/autonomy/__init__.py → 上溯三级
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONTROL_FILE = os.path.join(_REPO_ROOT, "xiaojiao_control.json")
_STATE_DIR = os.path.join(_REPO_ROOT, "logs", "autonomy")

# autonomy 段的默认值：**默认全关**（enabled=False）。
# 为什么默认关：后台任务会自己抓网络、自己调模型。用户没明确说要，就不该在后台烧他的额度、
# 占他的带宽 —— 自主性要"有"，但必须**用户点头才启动**。去掉这个默认，装完就跑，
# 用户会觉得"这软件怎么偷偷联网"。
_DEFAULT_AUTONOMY = {
    "enabled": False,
    "tasks": [],
    "watchers": [],
    "webhooks": {},          # {"feishu": "...", "dingtalk": "..."}
    "learn_interval_s": 1800,
    "watch_poll_s": 60,
}

_LOG_LOCK = threading.Lock()      # 多线程同时追加日志时防串行（一行一条，不能交错）


def _cfg():
    """惰性读操控文件（`xiaojiao_control.json`），**绝不抛错**。

    为什么惰性 + 容错：三个模块在 import 期就会调它，而操控文件可能：
    不存在 / JSON 写坏了 / 用户手改到一半保存。任何一种情况下抛异常，
    都会让 `import core.autonomy` 直接失败 —— 一个"后台可有可无"的功能
    把整个载体的 import 拖死，是最不划算的交换。
    所以：读不到就返回默认值（enabled=False，等于什么都不做）。
    去掉容错会怎样：用户手抖少打一个逗号 → 小焦起不来。
    """
    cfg = {}
    try:
        with open(_CONTROL_FILE, "r", encoding="utf-8", errors="replace") as f:
            cfg = json.load(f) or {}
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:      # noqa: silent-ok — 读不到配置就用默认值，后台功能全关，不影响对话
        cfg = {}
    auto = cfg.get("autonomy")
    if not isinstance(auto, dict):
        auto = {}
    merged = dict(_DEFAULT_AUTONOMY)
    merged.update(auto)
    cfg["autonomy"] = merged
    return cfg


def _autonomy_cfg(cfg=None):
    """取 autonomy 段（合并过默认值）。传 cfg 就用传入的，方便测试注入假配置。"""
    if isinstance(cfg, dict) and isinstance(cfg.get("autonomy"), dict):
        merged = dict(_DEFAULT_AUTONOMY)
        merged.update(cfg["autonomy"])
        return merged
    return _cfg()["autonomy"]


def _enabled(cfg=None):
    """后台自主功能是否启用（默认 False，用户点头才开）。"""
    return bool(_autonomy_cfg(cfg).get("enabled"))


def _state_dir(state_dir=None):
    """落盘目录：默认 `logs/autonomy/`。取不到就现建（建不出来也只是功能降级，不抛）。"""
    d = state_dir or _STATE_DIR
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:      # noqa: silent-ok — 目录建不出来时各写入点自己还会再兜一层
        pass
    return d


def _append_jsonl(path, obj):
    """追加一行 JSON（一行一条，append-only）。失败返回 False，**绝不抛**。

    为什么是 JSONL 而不是一个大 JSON：后台是"一条一条发生"的（一条通知、一次执行），
    追加不用重写整个文件；进程被 kill 时也不会把已有记录毁掉。
    """
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False)
        with _LOG_LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return True
    except Exception:      # noqa: silent-ok — 记不下来也不能让后台任务本身失败
        return False


def _log(msg, path=None):
    """往 `logs/autonomy/autonomy.log` 写一行（人肉排查后台到底干了什么）。"""
    p = path or os.path.join(_STATE_DIR, "autonomy.log")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _LOG_LOCK:
            with open(p, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:      # noqa: silent-ok — 同上
        pass


def _app_module():
    """惰性、**只查不建**地拿 `xiaojiao_app`；拿不到返回 None（绝不抛、绝不主动 import）。

    两个刻意的设计（都跟"后台不能拖垮主对话"这条铁律有关）：

    ① **只看 `sys.modules`，不 `import xiaojiao_app`。**
       小焦正常起法（`start_xiaojiao.py`）就是 `import xiaojiao_app as app`，
       所以"应用在跑"就等价于"它在 sys.modules 里"。反过来，如果这里主动 import：
       · 后台线程会去执行 xiaojiao_app 的**模块级副作用**（加载模型、挂载媒体服务），
         等于让用户的一条后台任务去付"冷启动"的代价 —— 而且是在非主线程里付；
       · 更糟的是当应用以 `python xiaojiao_app.py` 方式跑时，它叫 `__main__`，
         `import xiaojiao_app` 会**再导入一份**（两个 Flask app、两份模型常驻内存）。
       所以顺序是：先 `xiaojiao_app`，再看 `__main__` 是不是应用本体（有没有 agent_run）。
       都拿不到 → 调用方走自己的默认实现（离线可用）。
    ② 判据用 `hasattr(m, "agent_run")` 而不是"名字对得上"：
       `__main__` 也可能是任何一个脚本（比如自测脚本），不能认错人。

    去掉①会怎样：单独跑这个包（自测、被别的宿主 import）会顺手把小焦整个应用拉起来；
    以 __main__ 启动时还会出现"两份小焦"。
    """
    try:
        import sys
        for name in ("xiaojiao_app", "__main__"):
            m = sys.modules.get(name)
            if m is None:
                continue
            if name == "xiaojiao_app" or hasattr(m, "agent_run"):
                return m
    except Exception:      # noqa: silent-ok — 拿不到 app 是合法情形（离线自测就是这样）
        return None
    return None


def _resp_text(resp):
    """把 HTTP 响应体**正确解码**成文本 —— 中文站点最容易踩的那个坑。

    为什么不能直接用 `resp.text`：HTTP 头里没写 charset 时（很多站点都这样，本机
    `http.server` 提供的 text/plain 更是必然如此），requests 按 RFC 2616 兜底成
    ISO-8859-1，中文就变成 `æ\x96°å\x86\x85...` 这种乱码。
    后果**不只是看着难受**：`contains:中文关键词` 规则会永远命不中（用户以为没变化），
    而内容哈希照样在变 —— 用户看到"变了"却找不到他关心的那条，等于功能废掉一半。

    解码顺序：头里声明的编码 → 严格 UTF-8 → 自动猜出来的编码 → GB18030（中文老站）→
    替换式兜底（保证一定返回一个字符串，绝不抛）。
    去掉它会怎样：中文内容全成乱码，中文关键词规则全部失灵。
    """
    raw = getattr(resp, "content", None)
    if raw is None:
        try:
            return str(resp or "")
        except Exception:      # noqa: silent-ok — 极端情况下返回空串即可
            return ""
    if isinstance(raw, str):
        return raw
    cands = []
    head = str(getattr(resp, "encoding", "") or "").strip().lower()
    if head and head not in ("iso-8859-1", "latin-1"):
        cands.append(head)
    cands.append("utf-8")
    try:
        app_enc = str(getattr(resp, "apparent_encoding", "") or "").strip().lower()
    except Exception:      # noqa: silent-ok — 猜编码失败就直接走后面的固定列表
        app_enc = ""
    if app_enc:
        cands.append(app_enc)
    cands.append("gb18030")
    for enc in cands:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


__all__ = ["scheduler", "learner", "watcher"]


# ============================== 宿主接入用的三个一行入口 ==============================
# 宿主（xiaojiao_app）只要在启动时调 start_all(cfg)、每条用户消息调 touch()、
# 退出时调 stop_all()，就接完了 —— 不用知道三个类的构造细节和启动顺序。
# 下面这三个函数**惰性 import 子模块**（而不是在文件顶部 import）：子模块开头是
# `from . import _cfg`，顶部互相 import 会形成环。Python 多半能兜住这种环，
# 但"能跑"不等于"该这么写" —— 有环的包早晚会在某个 import 顺序下炸。
_RUNNING = {"scheduler": None, "learner": None, "watcher": None}


def start_all(cfg=None, learn_interval_s=None, watch_poll_s=None):
    """按配置把三个后台器官拉起来。**`autonomy.enabled` 不为 True 就一个线程都不起。**

    为什么用 enabled 一刀切：后台会自己联网、自己调模型。用户没点头就在后台烧额度，
    是小焦最不该犯的错。返回启动概况 dict（含 enabled 字段），宿主可以据此在界面上
    如实显示"自主功能：已开/已关"，而不是让用户猜。

    【返回字段为什么补了 tasks / watchers / reason —— 实测抓出来的显示缺陷】
      宿主 `start_xiaojiao.start_autonomy()` 打的是
        「已启用：定时任务 %s 个 / 盯梢源 %s 个」% (r.get("tasks", 0), r.get("watchers", 0))
      而这里原来只返回 `enabled / scheduler / learner / watcher` 四个字段 ——
      名字对不上，于是 `.get("tasks", 0)` **永远取到 0**：
      用户看到"定时任务 0 个 / 盯梢源 0 个"，会以为自主性没起来（其实线程已经拉起来了）。
      关掉那一侧同样：宿主读 `r.get("reason")`，这里连 `reason` 都没返回，
      提示语只能退回硬编码的 "enabled=false"，看不出**到底缺了哪一项配置**。
      修法：返回字段与宿主显示口径对齐，补 `tasks` / `watchers` 真实数量与 `reason`；
      **原来的 `scheduler` / `learner` / `watcher` 布尔全部保留**（老调用方照旧可用）。
    """
    cfg = _cfg() if cfg is None else cfg
    auto = _autonomy_cfg(cfg)
    out = {"enabled": bool(auto.get("enabled")), "scheduler": False,
           "learner": False, "watcher": False, "tasks": 0, "watchers": 0}
    if not out["enabled"]:
        # 如实说明"为什么没启用"：是没打开开关，还是开关打开了却没配任务/盯梢源
        out["tasks"] = len(auto.get("tasks") or [])
        out["watchers"] = len(auto.get("watchers") or [])
        out["reason"] = "autonomy.enabled 未设为 true"
        return out
    from . import learner as _learner
    from . import scheduler as _scheduler
    from . import watcher as _watcher
    sch = _scheduler.get_scheduler()
    sch.load_from_config(cfg)
    out["scheduler"] = sch.start()
    _RUNNING["scheduler"] = sch
    lr = _learner.AutonomousLearner()
    out["learner"] = lr.start(learn_interval_s or auto.get("learn_interval_s") or 1800)
    _RUNNING["learner"] = lr
    wt = _watcher.AutonomousWatcher()
    wt.load_from_config(cfg)
    out["watcher"] = wt.start(watch_poll_s or auto.get("watch_poll_s") or 60)
    _RUNNING["watcher"] = wt
    # 真实数量：报"装配进调度器的任务数 / 装配进盯梢器的源数"，不是报配置里的条数 ——
    # 配置里有、装配失败的那些不该算进"正在干活"的数量里。
    try:
        out["tasks"] = len(sch.list_tasks())
    except Exception:      # noqa: silent-ok — 数不出来就报 0，不影响启动
        out["tasks"] = 0
    try:
        out["watchers"] = len(wt.list_watchers())
    except Exception:      # noqa: silent-ok — 同上
        out["watchers"] = 0
    return out


def stop_all(timeout=3):
    """停掉 start_all 起来的所有后台线程（有界等待，绝不挂住主线程）。返回各自是否退出。"""
    out = {}
    for name, obj in list(_RUNNING.items()):
        if obj is None:
            out[name] = True
            continue
        try:
            out[name] = bool(obj.stop(timeout))
        except Exception:      # noqa: silent-ok — 退出流程里任何异常都不该阻止程序关闭
            out[name] = False
        _RUNNING[name] = None
    return out


def touch():
    """上报"用户有交互"（宿主每收到一条用户消息调一次）—— idle 任务靠它判断"现在该不该不打扰"。

    用单例而不是"宿主自己 new 一个"：两处各建一个调度器，同一条任务会被触发两遍
    （用户收到两份通知）。单例是这里唯一正确的形状。
    """
    from . import scheduler as _scheduler
    _scheduler.get_scheduler().touch()
