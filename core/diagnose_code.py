# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 代码治病（跑 → 载体诊断 → 模型改 → 再跑 → 通过）

【这段为什么这么设计】
    模型"一次写对可运行的代码"这件事**不可靠**，但"照着错误信息改一行"很可靠。
    所以载体把"能不能跑"这件事从模型手里拿走：
      1. 载体**真的跑一遍**（不是让模型想象跑起来会怎样）；
      2. 跑挂了就把错误**翻译成人能看懂的方向**（只给方向，**不给答案**）；
      3. 模型按方向改；
      4. 载体再跑一遍；通过就**直接输出结果**，不再走多余的流程。
    这是"精度叠加"在代码这件事上的落点：把不确定性收敛在"改一小步"里。

【为什么载体只给方向、不给答案】
    给了答案就等于载体写代码、模型当搬运工 —— 模型永远学不会，换个模型全废。
    而且用户的诉求是"让它把这段代码弄对"，不是"载体替它写"。
    判据：诊断输出里**只允许出现错误类型、位置、可能原因、检查方向**，
    绝不出现"把 X 改成 Y"这种成品代码。（自测有一条专门断言这一点。）

【红线】
    跑之前先过 `core/security/no_delete.py` 的命令拦截：
    「删所有文件」这类**在运行前就被拒绝**，连试都不试。这是与权限开关无关的硬拦截。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

__all__ = ["run_code", "diagnose", "diagnosis_text", "heal", "RUN_TIMEOUT",
           "health_path", "stats", "web_reference"]

RUN_TIMEOUT = 10           # 单次运行上限（秒）：死循环靠它拦，不靠模型自觉

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HEALTH = os.path.join(_ROOT, "logs", "code_health.jsonl")
_LOCK = threading.Lock()

# 错误类型 → 人能看懂的方向（**只有方向，没有改法**）
_PATTERNS = (
    (r"IndexError", "越界", "你访问的下标超出了序列长度。先确认长度是多少、你用的下标是多少，"
                        "再想清楚边界该取到哪。"),
    (r"KeyError", "键不存在", "你取的那个键在字典里没有。先列出字典到底有哪些键，再确认你要的是哪一个。"),
    (r"ZeroDivisionError", "除以零", "分母变成了 0。检查分母在什么情况下会是 0，那个情况该不该走这条路。"),
    (r"TypeError.*(?:not subscriptable|not iterable)", "类型不支持下标/迭代",
     "你对一个不是序列的东西用了下标或迭代。先确认这个变量此刻到底是什么类型。"),
    (r"TypeError.*argument", "参数不匹配", "调用时传的参数个数或类型和定义对不上。核对函数签名。"),
    (r"AttributeError", "属性不存在", "对象上没有你用的那个属性。确认对象类型，以及该属性名是否拼错。"),
    (r"NameError", "名字未定义", "用了一个还没定义的名字（变量名拼错，或定义在别的分支里）。"),
    (r"ValueError", "取值不合法", "传进去的值本身不合法（比如把非数字字符串转成数字）。"),
    (r"IndentationError|TabError", "缩进错误", "缩进不一致。同一个代码块必须用同一种缩进。"),
    (r"SyntaxError", "语法错误", "这一行不符合语法。看箭头指的位置往前一点。"),
    (r"RecursionError", "递归过深", "递归没有终止条件，或终止条件没被满足。"),
    (r"TimeoutExpired|超时", "运行超时", "程序没在限定时间内结束（多半是死循环）。检查循环的退出条件。"),
    (r"ModuleNotFoundError|ImportError", "模块缺失", "依赖没装或名字写错。"),
)
_LINE = re.compile(r'File "[^"]*", line (\d+)')


def _blocked_by_redline(code):
    """跑之前先过删除红线。返回拒绝原因（空串 = 放行）。

    【接口对齐 —— 这是一处真实事故的修复】
        `no_delete.check_command()` 的合约是**返回字符串**：空串 = 放行，非空 = 拒绝原因。
        这里曾经把它当 dict 用（`r.get("allowed", True)`）。`str` 没有 `.get`，会抛
        `AttributeError`，而异常被下面的 `except` 吞掉后返回了"放行" ——
        **红线在这条路上静默失效**，「删所有文件」会被直接执行。
        现在按字符串处理，并兼容历史 dict 形态（万一别处还在返回 dict）。

    【为什么取不到守卫时是"拒绝"而不是"放行"】
        删除**不可逆**。守卫取不到时无法证明这段代码安全：
        放行的代价是文件真的没了，拒绝的代价只是这次没跑成。只能选后者。
        这与"守卫拿不到就放行"的旧写法相反 —— 旧写法把"守卫坏了"变成了"禁区没了"。
    """
    try:
        from .security import no_delete as ND
        r = ND.check_command(code)
    except Exception as e:      # noqa: silent-ok — 但**不静默放行**：下面按拒绝处理
        return ("载体层没能加载删除守卫（%s）；删除不可逆，取不到守卫时拒绝执行"
                % type(e).__name__)
    if isinstance(r, str):
        return r.strip()
    if isinstance(r, dict) and not r.get("allowed", True):
        return str(r.get("reason") or "命中删除红线")
    return ""


def run_code(code, timeout=None):
    """真跑一遍。返回 {"ok","stdout","stderr","error_kind","seconds","blocked"}。

    `blocked` 非空 = **红线拒绝执行**，此时连子进程都不起。
    """
    t0 = time.time()
    code = str(code or "")
    if not code.strip():
        return {"ok": False, "stdout": "", "stderr": "代码是空的", "error_kind": "空代码",
                "seconds": 0.0, "blocked": ""}
    why = _blocked_by_redline(code)
    if why:
        return {"ok": False, "stdout": "", "stderr": "载体层拒绝执行：%s" % why,
                "error_kind": "红线拦截", "seconds": 0.0, "blocked": why}
    fd, path = tempfile.mkstemp(suffix=".py", prefix="xj_heal_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            p = subprocess.run([sys.executable, "-X", "utf8", path],
                               capture_output=True, timeout=(timeout or RUN_TIMEOUT))
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "执行超过 %d 秒仍未结束（多半是死循环）"
                    % (timeout or RUN_TIMEOUT), "error_kind": "运行超时",
                    "seconds": round(time.time() - t0, 2), "blocked": ""}
        so = (p.stdout or b"").decode("utf-8", "replace")
        se = (p.stderr or b"").decode("utf-8", "replace")
        return {"ok": p.returncode == 0, "stdout": so, "stderr": se,
                "error_kind": "" if p.returncode == 0 else (_kind_of(se) or "非零退出"),
                "seconds": round(time.time() - t0, 2), "blocked": ""}
    except Exception as e:      # noqa: silent-ok — 起不了子进程就如实返回，不当成"通过"
        return {"ok": False, "stdout": "", "stderr": "起不了执行环境：%s" % e,
                "error_kind": "环境错误", "seconds": round(time.time() - t0, 2), "blocked": ""}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _kind_of(err):
    for pat, kind, _hint in _PATTERNS:
        if re.search(pat, err, re.S):
            return kind
    return ""


def diagnose(err, code=""):
    """把错误翻译成**方向**（不是答案）。返回 {"kind","line","hint","raw"}。

    ⚠️ 这里**只允许**产出"错误类型 / 位置 / 可能原因 / 检查方向"。
    绝对不产出"把 X 改成 Y"这类成品代码 —— 那等于载体替模型写，模型永远学不会。
    """
    err = str(err or "")
    kind, hint = "", ""
    for pat, k, h in _PATTERNS:
        if re.search(pat, err, re.S):
            kind, hint = k, h
            break
    line = ""
    m = _LINE.search(err)
    if m:
        line = m.group(1)
    if not hint:
        hint = "先把错误原文看清楚：它说的是哪一行、哪一类问题。"
    return {"kind": kind or "未归类", "line": line, "hint": hint,
            "raw": err.strip().splitlines()[-1][:200] if err.strip() else ""}


def diagnosis_text(d):
    """给模型看的诊断文本（只给方向）。"""
    parts = ["【载体诊断 · 只给方向，不给答案】",
             "错误类型：%s" % d.get("kind")]
    if d.get("line"):
        parts.append("出错位置：第 %s 行" % d["line"])
    if d.get("raw"):
        parts.append("原始报错：%s" % d["raw"])
    parts.append("检查方向：%s" % d.get("hint"))
    parts.append("请你自己按这个方向改代码，把**完整代码**重新给我（不要只给改动片段）。")
    return "\n".join(parts)


def health_path():
    """病历路径：`logs/code_health.jsonl`。"""
    return _HEALTH


def record_case(**kw):
    """往病历追加一条。返回这条记录（写不进去也返回，只是没落盘）。

    【病历与精神记忆的分工】
        病历记的是**这一次发生了什么**（原始证据：错了几轮、错在哪几类、是不是被红线拦的）。
        精神记忆记的是**提炼出来的经验**（"编辑吃掉 def 行要用 ruff F821 兜"）。
        原始证据可以粗、可以多；提炼后的经验必须是一句话。两者不混。
    **只追加，不覆盖** —— 病历被改写就失去了取证价值。
    """
    rec = {"ts": time.time(), "kind": "code_heal"}
    rec.update(kw)
    try:
        os.makedirs(os.path.dirname(_HEALTH), exist_ok=True)
        with _LOCK:
            with open(_HEALTH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上病历只影响复盘，不影响这一轮回答
        pass
    return rec


def stats():
    """病历统计：总条数、成功/失败、被红线拦下的条数、最常见的错误类型。"""
    rows = []
    if os.path.exists(_HEALTH):
        try:
            with open(_HEALTH, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:      # noqa: silent-ok — 坏行跳过
                        continue
        except Exception:      # noqa: silent-ok — 读不到就当还没病历
            rows = []
    kinds = {}
    for r in rows:
        for k in (r.get("kinds") or []):
            kinds[k] = kinds.get(k, 0) + 1
    return {"total": len(rows),
            "ok": sum(1 for r in rows if r.get("ok")),
            "blocked": sum(1 for r in rows if r.get("blocked")),
            "used_web": sum(1 for r in rows if r.get("used_web")),
            "kinds": kinds, "path": _HEALTH}


def web_reference(err, code="", web_fn=None, max_chars=1200):
    """改到第 N 轮还不过时，上网查一段**参考**。

    【为什么是"参考"而不是"答案"】
        网上搜到的往往是**别人针对别人的问题**写的完整代码。直接拿来用有两个问题：
        它可能根本不适用（问题不同），而且一旦照抄，模型就没在解决问题，
        只是当了搬运工 —— 换个问题又不会了。所以这里的用法是：
        把检索结果作为**思路参考**交给模型，明确要求它理解之后**自己重写**。

    返回 `{"ok","text","query","why"}`。`web_fn(query) -> str` 由调用方注入
    （载体已有的联网能力）；没给或查不到时如实返回 ok=False，**不编造参考内容**。
    """
    if not callable(web_fn):
        return {"ok": False, "text": "", "query": "", "why": "没有可用的联网入口"}
    d = diagnose(err, code)
    # 检索词用"错误类型 + 报错原文"，不用整段代码 —— 代码里的细节会污染检索
    query = ("%s %s" % (d.get("kind") or "", d.get("raw") or "")).strip()[:120]
    if not query:
        return {"ok": False, "text": "", "query": "", "why": "提炼不出检索词"}
    try:
        text = web_fn(query) or ""
    except Exception as e:      # noqa: silent-ok — 联网失败不该中断治病，如实记下
        return {"ok": False, "text": "", "query": query, "why": "联网失败：%s" % type(e).__name__}
    text = str(text).strip()
    if not text:
        return {"ok": False, "text": "", "query": query, "why": "联网没查到内容"}
    return {"ok": True, "text": text[:max_chars], "query": query, "why": "查到一段参考"}


def _round(code, timeout, on_step, i, phase):
    res = run_code(code, timeout=timeout)
    if on_step:
        try:
            on_step(i, res)
        except Exception:      # noqa: silent-ok — 回调是锦上添花
            pass
    return res


def heal(code, llm_fn, max_rounds=3, timeout=None, on_step=None,
         web_fn=None, web_rounds=1):
    """跑 → 诊断 → 模型改 → 再跑。通过就停。

    `llm_fn(messages) -> str`：调大脑要一段新代码（返回里允许带 ``` 围栏，会自动剥）。
    `web_fn(query) -> str`：**自己改的机会用尽后**，用它上网查一段**参考**
    （明确标注是参考，并要求模型理解后自己重写，不照抄）。

    【升级规则】`max_rounds` 就是"自己改的机会数"，默认 3（规格值：三轮不行再查网络）。
    用尽之后才升级到联网参考；调用方把它调小（比如 1），就是主动要求更早去查资料。
    **红线被拦时不升级也不重试** —— 删文件不是"查查资料就能过"的错误。

    返回 {"ok","code","rounds","trace","final"}；`trace` 是每一轮的实际记录（自测取证用）。
    被红线拦下时额外带 `blocked`，且**不再重试**。
    """
    trace = []
    kinds = []
    cur = str(code or "")
    total = 0
    blocked = ""
    used_web = False

    # ---- 第一段：自己改，最多 max_rounds 轮 ----
    for i in range(1, max(1, int(max_rounds)) + 1):
        total = i
        res = _round(cur, timeout, on_step, i, "自改")
        trace.append({"round": i, "phase": "自改", "ok": res["ok"],
                      "error_kind": res["error_kind"], "blocked": res["blocked"],
                      "seconds": res["seconds"],
                      "stdout": res["stdout"][:400], "stderr": res["stderr"][:400]})
        if res["ok"]:
            return _finish(True, cur, trace, res["stdout"].strip(), blocked, kinds, used_web)
        if res["blocked"]:
            # 红线拒绝：**不许重试**。这不是"改一改就能跑"的错误，查网络也没用。
            return _finish(False, cur, trace, "", res["blocked"], kinds, used_web)
        if res["error_kind"]:
            kinds.append(res["error_kind"])
        d = diagnose(res["stderr"], cur)
        try:
            out = llm_fn([{"role": "user", "content":
                           "下面这段 Python 跑不起来。\n\n```python\n%s\n```\n\n%s"
                           % (cur, diagnosis_text(d))}]) or ""
        except Exception as e:      # noqa: silent-ok — 模型调不通就如实停下
            trace.append({"round": i, "phase": "自改", "note": "模型调用失败：%s" % e})
            break
        new = _strip_fence(out)
        if not new.strip() or new.strip() == cur.strip():
            trace.append({"round": i, "phase": "自改", "note": "模型没给出不同的代码，停止"})
            break
        cur = new

    # ---- 第二段：改满还不过 → 上网查**参考**，再给 web_rounds 轮 ----
    last_err = ""
    for t in reversed(trace):
        if t.get("stderr"):
            last_err = t["stderr"]
            break
    if callable(web_fn) and int(web_rounds) > 0 and last_err:
        ref = web_reference(last_err, cur, web_fn=web_fn)
        trace.append({"phase": "查网络参考", "ok": None, "query": ref.get("query", ""),
                      "reference_ok": ref["ok"], "note": ref["why"]})
        if ref["ok"]:
            used_web = True
            for j in range(1, int(web_rounds) + 1):
                total += 1
                prompt = (
                    "下面这段 Python 跑不起来，已经自己改了几轮都没过。\n\n"
                    "```python\n%s\n```\n\n%s\n\n"
                    "【网上查到的参考资料（**只是参考**）】\n%s\n\n"
                    "**要求**：理解这段参考的思路之后，**自己重写代码**。"
                    "不要照抄 —— 它可能是在回答别人的问题，直接搬过来多半不适用。"
                    "改写后的目标仍然是解决我原本的问题。请给出**完整代码**。"
                    % (cur, diagnosis_text(diagnose(last_err, cur)), ref["text"]))
                try:
                    out = llm_fn([{"role": "user", "content": prompt}]) or ""
                except Exception as e:      # noqa: silent-ok
                    trace.append({"round": total, "phase": "参考改", "note": "模型调用失败：%s" % e})
                    break
                new = _strip_fence(out)
                if not new.strip() or new.strip() == cur.strip():
                    trace.append({"round": total, "phase": "参考改", "note": "模型没给出不同的代码，停止"})
                    break
                cur = new
                res = _round(cur, timeout, on_step, total, "参考改")
                trace.append({"round": total, "phase": "参考改", "ok": res["ok"],
                              "error_kind": res["error_kind"], "blocked": res["blocked"],
                              "seconds": res["seconds"],
                              "stdout": res["stdout"][:400], "stderr": res["stderr"][:400]})
                if res["ok"]:
                    return _finish(True, cur, trace, res["stdout"].strip(), blocked, kinds, used_web)
                if res["blocked"]:
                    return _finish(False, cur, trace, "", res["blocked"], kinds, used_web)
                if res["error_kind"]:
                    kinds.append(res["error_kind"])
                last_err = res["stderr"]

    return _finish(False, cur, trace, "", blocked, kinds, used_web)


def _finish(ok, code, trace, final, blocked, kinds, used_web):
    """收尾：写病历 + 返回统一结构。**病历落盘失败不影响返回结果**。"""
    outcome = {"ok": ok, "code": code, "rounds": len([t for t in trace if t.get("ok") is not None]),
               "trace": trace, "final": final, "kinds": kinds, "used_web": used_web}
    if blocked:
        outcome["blocked"] = blocked
    record_case(ok=ok, blocked=blocked, kinds=kinds, used_web=used_web,
                rounds=outcome["rounds"],
                seconds=round(sum(float(t.get("seconds") or 0) for t in trace), 2),
                code_head=str(code or "")[:300],
                error_head=(trace[-1].get("stderr") or "")[:200] if trace else "")
    return outcome


def _strip_fence(s):
    s = str(s or "").strip()
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", s, re.S)
    return m.group(1) if m else s
