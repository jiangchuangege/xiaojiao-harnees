# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 健康系统（无限 8：它不生病 —— 模型退化时载体自己能治）

【一句话定位】
    火种会烧坏，载体得会修。这一层就是小焦的**免疫系统**。

【为什么必须有这一层（模型会退化，像人一样）】
    人脑会退化：疲劳、生病、精神失常。
    模型也会退化：复读、逻辑混乱、幻觉、答非所问、突然暴躁、突然消极、
    乱调工具、前后矛盾。
    这不是"模型坏了"，是**模型生病了**。
    不能等它病入膏肓才治（那时整轮回答已经废了、还可能污染长期记忆），
    要在**症状出现的那一刻**就介入 —— 这就是本层存在的全部理由。

【五层结构（每一层一个模块，缺一层都会漏诊或漏治）】
    ① 监测 monitor.py    18 类症状，分五组（语言/逻辑/情绪/行为/生理）。
                          没有它 → 病到什么程度全靠感觉，无法自动干预。
    ② 诊断 diagnose.py   轻 / 中 / 重 / 急 四级 + 判因（模型/上下文/资源/逻辑）。
                          没有它 → 要么小题大做（把正常口误当病危），要么大病小治。
    ③ 治疗 heal.py       四级治疗 + 预防体检 + 会话隔离。
                          没有它 → 诊断出来了也没人动手，等于没诊。
    ④ 病历 records.py    每次症状+治疗如实落盘，可分析、可给预防建议。
                          没有它 → 同一个坑会一遍遍踩，系统不会变聪明。
    ⑤ 地基 degeneration.py（已存在，**本层不修改**）复读检测与截断。
                          监测层的"复读"症状**直接调用**它，绝不另写一套 ——
                          两套重复检测的必然结果是两套阈值、两套误报。

【目标】
    让 4B 模型在载体里长期稳定运行；即使偶尔退化也能立刻恢复，不积累成大问题。

【为什么 __init__ 里放这几个小工具（而不是四个模块各写一份）】
    四个模块都要做同样四件事：读健康配置、拿落盘目录、追加一行 JSONL、惰性拿 app。
    各写一份的结果是"四份略有差异的实现"，早晚出现"监测认 health.monitor 段、
    治疗不认"这种灵异现象。放这里统一；去掉它就等于把配置语义撕成四份。

【数据落盘一律在 logs/health/ 下】（logs/ 已被 .gitignore 忽略，不脏仓库）
    degeneration.jsonl  退化命中流水（degeneration.py 自己写）
    records.jsonl       病历（症状+治疗+结果）
    notify.jsonl        强通知流水
    isolated.json       会话隔离状态
    preventive_state.json 预防层"今天做过自检没有"
    snapshot_*.json     保留现场的状态快照

【为什么这里**不**import 任何子模块】
    monitor / diagnose / heal / records 都要 `from . import ...` 拿本文件的工具函数，
    本文件若在 import 期反过来把子模块拉进来，就成了循环 import：
    单独 `import core.health.monitor` 会直接 ImportError。
    于是改用 PEP 562 的模块级 `__getattr__`：**用到才 import**。
    去掉它：`import core.health as H; H.HealthMonitor` 这种顺手写法会 AttributeError，
    而 `from core.health.monitor import HealthMonitor` 仍然正常。
"""
import json
import os
import sys
import time

# 仓库根：core/health/__init__.py → 上溯三级
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTROL_FILE = os.path.join(_REPO_ROOT, "xiaojiao_control.json")
HEALTH_DIR = os.path.join(_REPO_ROOT, "logs", "health")

# health 段的默认值。为什么默认是"开"而 autonomy 默认"关"：
# 自主性会在后台花用户的额度和带宽，必须用户点头；健康系统只在**已经出问题**时
# 做几毫秒的本地判断和一次截断，不联网、不调模型，代价可以忽略 ——
# 关掉它省不下什么，却会在模型退化时把几千字垃圾交给用户。所以默认开。
_DEFAULT_HEALTH = {
    "enabled": True,
    "auto_heal": True,        # 允许一级/二级自动治疗（三级等确认、四级必须停机）
    "preventive": True,       # 允许预防层（清上下文 / 后台整理 / 凌晨自检）
    "isolate_after": 3,       # 同一会话反复退化多少次后隔离
    "self_check_hour": (0, 5),  # 凌晨 00:00~05:00 做全面自检
    "idle_organize_s": 1800,  # 空闲 30 分钟后整理记忆
    "turns_reset": 50,        # 连续对话 ≥50 轮建议清一次上下文
}


def health_dir(sub=None):
    """健康数据目录（默认 `logs/health/`）；建不出来也不抛，各写入点自己还会兜一层。

    为什么集中在这里算路径：如果每个模块各用 `os.path.dirname(__file__)` 拼一次，
    早晚有人拼错一级，日志就散到仓库别的地方去了 —— 排查时你以为"没记录"，
    其实记录在另一个目录里。去掉它就会这样。
    """
    d = HEALTH_DIR if not sub else os.path.join(HEALTH_DIR, sub)
    try:
        os.makedirs(os.path.dirname(d) if os.path.splitext(d)[1] else d, exist_ok=True)
    except Exception:      # noqa: silent-ok — 目录建不出来时写入点自己再兜一层
        pass
    return d


def cfg(override=None):
    """健康配置：默认值 ← `xiaojiao_control.json` 的 `health` 段 ← 显式 override。

    为什么读操控文件而不是写死：阈值（比如"连续几轮算持续"）是要按机器和模型调的；
    调阈值不该改代码。三级合并让"代码默认 / 用户配置 / 调用方临时覆盖"各司其职。
    为什么**绝不抛错**：用户手改 JSON 少个逗号，不能让整个健康系统（乃至对话）起不来。
    去掉容错会怎样：一次手抖 → `import core.health` 直接失败 → 小焦起不来。
    """
    merged = dict(_DEFAULT_HEALTH)
    try:
        with open(CONTROL_FILE, "r", encoding="utf-8", errors="replace") as f:
            raw = json.load(f) or {}
        if isinstance(raw, dict) and isinstance(raw.get("health"), dict):
            merged.update(raw["health"])
    except Exception:      # noqa: silent-ok — 读不到/写坏了就用默认值
        pass
    if isinstance(override, dict):
        merged.update(override)
    return merged


def append_jsonl(path, obj):
    """追加一行 JSON（append-only）。返回 True/False，**绝不抛**。

    为什么是 JSONL 而不是一个大 JSON：健康记录是"一条一条发生"的。
    追加不用重写整个文件（大文件重写有半截写坏的风险），进程被 kill 也不会
    毁掉已有记录。去掉它换成单个 JSON：一次写坏，整部病历全丢。
    """
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except Exception:      # noqa: silent-ok — 记不上也不能影响对话
        return False


def read_jsonl(path, days=None, limit=None):
    """读 JSONL，**半截/损坏的行直接跳过**（返回 list[dict]）。

    为什么必须容忍坏行：日志是边写边读的 —— 恰好在读到一半时进程被杀，
    最后一行就是半截 JSON。若这里抛异常，整个病历分析全废，
    而坏行只有一行。去掉容忍 = 一行半截 JSON 毁掉全部历史。
    """
    out = []
    try:
        if not os.path.exists(path):
            return out
        since = (time.time() - float(days) * 86400.0) if days else None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:      # noqa: silent-ok — 半截行跳过，不能连累其它行
                    continue
                if not isinstance(row, dict):
                    continue
                if since is not None:
                    try:
                        if float(row.get("ts") or 0) < since:
                            continue
                    except Exception:      # noqa: silent-ok — ts 坏掉就当作当期，宁可多算不可丢
                        pass
                out.append(row)
                if limit and len(out) >= int(limit):
                    break
    except Exception:      # noqa: silent-ok — 读不动就当没有病历
        return out
    return out


def read_json(path, default=None):
    """读一个小 JSON（状态文件）。读不到/坏了 → 返回 default，绝不抛。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            v = json.load(f)
        return v if v is not None else default
    except Exception:      # noqa: silent-ok — 状态文件坏了等价于"没状态"
        return default


def write_json(path, obj):
    """写一个小 JSON（状态文件），原子性靠"先写临时名再重命名"之外的**直写**方式。

    为什么不搞 tmp+rename：rename 在 Windows 上要覆盖目标，语义上等同"删掉旧文件"，
    而本层有一条硬规矩是**绝不删除任何文件**。这里写的是自己的状态文件，
    内容全在内存里，写坏了下一次写会覆盖回来 —— 直写足够，且不触删除。
    去掉它（改成 tmp+rename）在别的平台上没问题，但会破坏"绝不删文件"这条约束。
    """
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:      # noqa: silent-ok — 状态写不上只是"少记住一件事"
        return False


def log_line(name, msg):
    """往 `logs/health/<name>.log` 追加一行（人肉排查"它到底治了什么"）。"""
    p = os.path.join(HEALTH_DIR, "%s.log" % name)
    try:
        os.makedirs(HEALTH_DIR, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:      # noqa: silent-ok — 写不上日志不影响功能
        pass


_APP_CACHE = {"mod": None, "tried": False}


def app_module(allow_import=False):
    """惰性拿 `xiaojiao_app` 模块；拿不到返回 None（**绝不抛错**）。

    这是整个载体层"能独立跑"的关键手法（`core/autonomy/__init__.py` 同款）：
    先看 `sys.modules` —— 应用已经起来了就直接用现成的，不重复初始化那一套。

    【为什么默认**不**主动 import（实测数据，写下来免得有人"顺手优化"掉）】
    `import xiaojiao_app` 会连带加载小脑模型、视频/播客服务与刮取桥，
    本机实测 **2.63s**，还会往 stdout 打一堆启动横幅。
    健康系统的默认实现全都在**对话热路径**上（治一下、重试一次），
    为了"可能能重试"先卡 2.6 秒、还把用户终端刷脏，是明显亏的交换。
    所以默认只认已经 import 过的 app；真要离线实验时把 allow_import 打开
    （或设环境变量 XIAOJIAO_HEALTH_IMPORT_APP=1）。
    去掉这个分寸（一律积极 import）会怎样：单测从秒级变十几秒，
    真机上每次触发健康检查都可能把整个应用再初始化一遍。
    """
    if _APP_CACHE["tried"] and _APP_CACHE["mod"] is not None:
        return _APP_CACHE["mod"]
    mod = sys.modules.get("xiaojiao_app")
    if mod is None and (allow_import or os.environ.get("XIAOJIAO_HEALTH_IMPORT_APP") == "1"):
        try:
            import xiaojiao_app as mod      # noqa: F401 — 只有显式允许时才走这条
        except Exception:      # noqa: silent-ok — 没有 app 是合法情形（离线自测就是这样）
            mod = None
    _APP_CACHE["tried"] = True
    if mod is not None:
        _APP_CACHE["mod"] = mod
    return mod


def _lazy(name):
    """按需 import 子模块（PEP 562 用）。"""
    import importlib
    return importlib.import_module("." + name, __name__)


__all__ = ["degeneration", "monitor", "diagnose", "heal", "records",
           "HealthMonitor", "HealthDiagnose", "HealthHealer", "HealthRecords",
           "health_dir", "cfg", "append_jsonl", "read_jsonl", "read_json",
           "write_json", "log_line", "app_module"]


def __getattr__(name):
    """让 `core.health.HealthMonitor` 这类顺手写法可用，且**不引入 import 环**。

    只有被真正取用时才 import 对应子模块；`__all__` 里的名字全部覆盖。
    去掉它：`H.HealthMonitor` 报 AttributeError（得写全 `core.health.monitor`）。
    """
    if name in ("degeneration", "monitor", "diagnose", "heal", "records"):
        return _lazy(name)
    if name == "HealthMonitor":
        return _lazy("monitor").HealthMonitor
    if name == "Symptom":
        return _lazy("monitor").Symptom
    if name == "HealthDiagnose":
        return _lazy("diagnose").HealthDiagnose
    if name == "HealthHealer":
        return _lazy("heal").HealthHealer
    if name == "HealthRecords":
        return _lazy("records").HealthRecords
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
