# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 任务级自主（2026-10-28）

【它解决什么】到这一轮为止，小焦能"答一句""调一个工具""生成一个能力"，
但**不能把一件复杂的事自己做完**。用户说「把这批书都抓下来存好」时，
它要么只抓一页、要么跑一半就回来问。市面上 Agent 也一样：一旦多步、一旦中途失败，
就丢上下文重来，而且**从不告诉你哪一步没做成**。

本模块给它三样东西：
  ① **状态机 + 落盘**：每一步都写进 `logs/tasks/<id>.json`，进程重启也能接着做（resume）；
  ② **失败换路**：某一步的工具挂了，按 `_tool_fallback_for` 自动换同族工具重试，
     换完还不行就**停下并如实说卡在哪一步**，不假装完成；
  ③ **验收判据**：每步有自己的"做成没做成"判据（产物存在 / 关键实体在结果里 / 工具链成功），
     全部通过才叫 done；有一项没把握就标 partial —— **"部分完成"这四个字必须能出现**。

【拆解为什么先走规则、后走模型】
  实测本地 4B 写多步计划很不稳（工具名编造、参数乱填）。而"抓取→落盘""天气→取数→措辞"
  这些链载体早就有了（`_detect_scrape_intent` / `_scrape_save_target` / 意图路由）。
  所以：**能由规则定的绝不让模型定**；规则覆盖不到时，才让模型给步骤 JSON，
  并且每个工具名必须过白名单、每个参数必须过类型检查 —— 不合规就整份扔掉重来。

【和 `core/autonomy` 的分工】autonomy 管"它自己什么时候想干什么"（逛世界、学东西）；
  本模块管"用户交给它一件事，它怎么把这件事做完"。两者不互相调用。
"""
import io
import json
import logging
import os
import re
import threading
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "tasks")
_MAX_STEPS = 12

_LOCK = threading.RLock()
_RUNNING = {}          # tid -> thread（只在内存里记"谁在跑"）
_TASKS = {}            # tid -> dict（内存镜像，落盘为准）

# 步骤失败的判据（工具返回里出现这些就算没做成）
_FAIL_MARKS = ("error", "traceback", "失败", "不可用", "没有装载", "未知工具", "超时", "拒绝")


# ============================== 落盘 ==============================
def _ensure():
    if not os.path.isdir(_DIR):
        os.makedirs(_DIR, exist_ok=True)


def _path(tid):
    return os.path.join(_DIR, "%s.json" % tid)


def _save(task):
    """落盘（原子写：先写临时文件再替换，避免断电写出半个 JSON）。"""
    try:
        _ensure()
        task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = _path(task["id"]) + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(task, ensure_ascii=False, indent=1))
        os.replace(tmp, _path(task["id"]))
        _TASKS[task["id"]] = task
        return True
    except Exception as e:      # noqa: silent-ok — 落盘失败要记日志但不炸
        LOG.warning("任务落盘失败（%s）：%s", task.get("id"), e)
        return False


def load(tid):
    """按 id 读任务（内存里没有就从磁盘读）。"""
    if tid in _TASKS:
        return _TASKS[tid]
    try:
        p = _path(str(tid))
        if os.path.isfile(p):
            t = json.loads(io.open(p, encoding="utf-8").read())
            _TASKS[t["id"]] = t
            return t
    except Exception as e:      # noqa: silent-ok — 读不出来就是没有
        LOG.debug("任务读取失败（%s）：%s", tid, e)
    return None


def list_tasks(limit=10):
    """最近的任务（按更新时间倒序）。"""
    out = []
    try:
        _ensure()
        for fn in os.listdir(_DIR):
            if not fn.endswith(".json"):
                continue
            try:
                t = json.loads(io.open(os.path.join(_DIR, fn), encoding="utf-8").read())
            except Exception:      # noqa: silent-ok — 坏文件跳过
                continue
            out.append({"id": t.get("id"), "goal": t.get("goal"),
                        "state": t.get("state"), "steps": len(t.get("steps") or []),
                        "done_steps": sum(1 for s in (t.get("steps") or [])
                                          if s.get("state") == "done"),
                        "updated_at": t.get("updated_at")})
    except Exception:      # noqa: silent-ok
        pass
    out.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return out[:limit]


# ============================== 拆解 ==============================
def _need_app():
    import xiaojiao_app as app
    try:
        app._build_tools()
    except Exception as e:      # noqa: silent-ok — 建表失败不影响后面
        LOG.debug("任务拆解：建工具表失败（忽略）：%s", e)
    return app


def _step(tool, args, why, verify=""):
    return {"tool": tool, "args": dict(args or {}), "why": why, "verify": verify,
            "state": "pending", "result": "", "tried": [], "at": ""}


def plan_by_rules(goal):
    """先用**载体规则**拆解（能定就不问模型）。返回 steps 列表或 []。"""
    g = str(goal or "")
    try:
        app = _need_app()
    except Exception as e:      # noqa: silent-ok — 拿不到 app 就走模型拆解
        LOG.debug("任务拆解：拿不到 app（%s）", e)
        return []

    # ① 抓网页 → 落盘（最常见的长任务）
    try:
        sc = app._detect_scrape_intent(g)
        if sc:
            tool, args = sc
            out = app._scrape_save_target(g)
            steps = [_step(tool, args, "先把页面抓下来（失败会自动换同族工具）",
                           verify="返回非空且无失败标记")]
            if out:
                # 【2026-10-28 修】`_scrape_save_target` 取出来的是"用户给的保存位置"，
                #   它可能是**目录**，也可能是**文件**。一开始我一律当目录，
                #   于是「存到 G:\\dzs\\out\\stage1.html」被拼成了
                #   `G:\\dzs\\out\\stage1.html\\example.com.md` ——
                #   系统建了一个叫 stage1.html 的**目录**，验收按文件名去找文件当然找不到，
                #   项目因此判失败（实测：里程碑 1 failed，产物 1 字节且根本是目录）。
                #   判据很简单：带扩展名且不像目录的，就当文件路径原样用。
                _a = str(args.get("url") or g)
                if _looks_like_file(out):
                    _p = out
                else:
                    _p = os.path.join(out, _out_name(_a))
                steps.append(_step("write_file", {"path": _p, "content": "__BODY__"},
                                   "把正文写到用户指定的位置", verify="文件真的存在且不是空的"))
            return steps
    except Exception as e:      # noqa: silent-ok — 规则不可用就试下一条
        LOG.debug("任务拆解：抓取规则失败（%s）", e)

    # ② 天气 → 取数（后续"能不能出门"这类判断由模型基于数据说）
    try:
        if app._weather_intent(g):
            city = (app._specialized_args("get_weather", g) or {}).get("city") or ""
            if city:
                return [_step("get_weather", {"city": city}, "先查到真数据",
                              verify="返回里有气温数字")]
    except Exception as e:      # noqa: silent-ok
        LOG.debug("任务拆解：天气规则失败（%s）", e)

    # ③ 电子书：清单 / 下载
    try:
        eb = app._ebook_intent(g)
        if eb:
            tool, args = eb
            return [_step(tool, args, "走电子书专用工具（它自己会跳过付费墙）",
                          verify="返回里有成功项或明确的跳过原因")]
    except Exception as e:      # noqa: silent-ok
        LOG.debug("任务拆解：电子书规则失败（%s）", e)

    # ④ 公网 IP / 漏洞 / 架构图：单步但值得走任务框架（要验收）
    try:
        from core import tool_isolation as TI
        spec = TI.specialized_for(g)
        if "net_ip" in spec:
            return [_step("net_ip", {}, "查本机公网 IP", verify="返回里有 IP 样式")]
        if "collect_vulnerabilities" in spec:
            return [_step("collect_vulnerabilities", {"limit": 5},
                          "拉最近漏洞（限量，别刷人家接口）", verify="返回里有条目")]
        if "archify_deliver" in spec:
            return []       # 画图要 spec，交给模型拆解
    except Exception as e:      # noqa: silent-ok
        LOG.debug("任务拆解：专用工具规则失败（%s）", e)
    return []


_PLAN_PROMPT = """把下面这个目标拆成**可执行的步骤**，只输出 JSON 数组，不要解释。

可用工具（只能用这些名字）：{tools}

每一步形如：
{{"tool": "工具名", "args": {{"参数": "值"}}, "why": "为什么这一步", "verify": "怎么算做成"}}

规则：
1. 最多 {maxn} 步；能在 1~2 步做完的别拆成 5 步；
2. args 必须符合该工具的参数（不确定的字段就不要写）；
3. 最后一步必须产生**用户能直接用的产物**（文件/数据/结论）；
4. 只输出 JSON 数组。

目标：{goal}
"""


def plan_by_model(goal, timeout=90):
    """规则覆盖不到时，让模型拆解。工具名必须过白名单，否则整份扔掉。"""
    try:
        import requests
        from core import model_router as MR
        app = _need_app()
        names = [n for n in app.all_tool_names()]
        base = MR._base_url() + "/v1"
        prompt = _PLAN_PROMPT.format(tools=", ".join(names[:120]), maxn=_MAX_STEPS,
                                     goal=str(goal)[:300])
        for model in ("qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "xiaojiao"):
            try:
                r = requests.post(base + "/chat/completions", json={
                    "model": model, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 900, "temperature": 0.2,
                }, timeout=timeout)
                if r.status_code != 200:
                    continue
                txt = str(((r.json().get("choices") or [{}])[0].get("message") or {})
                          .get("content") or "")
                txt = re.sub(r"^```(?:json)?\s*", "", txt.strip())
                txt = re.sub(r"\s*```$", "", txt).strip()
                m = re.search(r"\[.*\]", txt, re.S)
                if not m:
                    continue
                arr = json.loads(m.group(0))
                steps, bad = [], []
                for it in (arr or [])[:_MAX_STEPS]:
                    if not isinstance(it, dict):
                        continue
                    tool = str(it.get("tool") or "").strip()
                    if tool not in names:               # 白名单：模型编的工具名一律不要
                        bad.append(tool)
                        continue
                    args = it.get("args") if isinstance(it.get("args"), dict) else {}
                    steps.append(_step(tool, args, str(it.get("why") or "")[:80],
                                       str(it.get("verify") or "返回非空且无失败标记")[:60]))
                if bad:
                    LOG.warning("任务拆解：模型给了不存在的工具（%s），已剔除", bad[:3])
                if steps:
                    return steps
            except Exception:      # noqa: silent-ok — 换下一个模型
                continue
    except Exception as e:      # noqa: silent-ok — 拆不出来就如实失败
        LOG.warning("任务拆解：模型拆解失败（%s）", e)
    return []


# ============================== 执行 ==============================
def _step_ok(result):
    """一步算不算做成。

    【先解析 JSON，再退回文本】实测踩到：抓取类工具返回
    `{"status": 200, "url": …, "content": "…", "error": ""}` —— `error` 字段存在但为空，
    而我原来用"文本里有没有 error 字样"判，于是一个**成功的抓取**被判成失败，
    整个任务在第一步就 failed（同一个坑我在体检脚本里也踩过，这里又犯了一次）。
    现在：JSON 能解析就按 status/error 字段判；只有解析不了才看文本，
    而且文本判据去掉了 `error`、`失败`、`不可用` 这些到处都出现的泛词。
    """
    s = str(result or "")
    if not s.strip():
        return False, "返回空"
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            err = str(d.get("error") or "").strip()
            if err:
                return False, "工具报错：%s" % err[:60]
            st = d.get("status")
            if st not in (None, 200, "200") and not str(d.get("content") or "").strip():
                return False, "HTTP %s 且没有内容" % st
            return True, ""
    except Exception:      # noqa: silent-ok — 不是 JSON 就走下面的文本判断
        pass
    low = s.lower()
    for mk in ("traceback", "抓取失败", "服务暂时不可用", "没有装载", "未知工具",
               "连接被拒绝", "拒绝连接", "name or service not known"):
        if mk in low or mk in s:
            return False, "返回里有失败标记（%s）" % mk
    return True, ""


def _body_of(result):
    """从抓取结果里取出**正文**，不要整个 JSON 外壳。

    【实测踩到】第 1 步 `get` 返回 `{"status":200,"url":…,"content":"…"}`，
    落盘那步把 `str(res)` 整串写进文件，于是存下来的 Markdown 开头是
    `{"status": 200, "url": …}` —— 用户要的是正文，不是我们内部的返回包装。
    """
    s = str(result or "")
    try:
        d = json.loads(s)
    except Exception:      # noqa: silent-ok — 不是 JSON 就是纯文本，原样返回
        return s
    if isinstance(d, dict):
        for k in ("content", "text", "markdown", "body", "html"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return s


def _looks_like_file(path):
    """"用户给的保存位置"是文件还是目录？

    判据（保守）：有扩展名、且不是以分隔符结尾 → 当文件。
      实测踩过：`G:\\dzs\\out\\stage1.html` 被当目录，系统真去建了一个**叫 stage1.html 的目录**，
      正文写进了它里面的 example.com.md，而验收按"文件在不在"判 → 失败，整个项目跟着失败。
    """
    p = str(path or "").strip()
    if not p:
        return False
    if p.endswith("\\") or p.endswith("/"):
        return False
    ext = os.path.splitext(p)[1]
    return bool(ext) and len(ext) <= 6 and re.fullmatch(r"\.[A-Za-z0-9]+", ext) is not None


def _out_name(url_or_goal):
    """给落盘文件起一个**看得懂**的名字（原来固定叫 `_task_body.md`，开文件夹一脸问号）。"""
    u = str(url_or_goal or "")
    m = re.search(r"https?://([^\s/]+)(/[^\s?#]*)?", u)
    if not m:
        return "_task_body.md"
    host = re.sub(r"[^A-Za-z0-9.]+", "_", m.group(1)).strip("_")
    path = re.sub(r"[^A-Za-z0-9]+", "_", m.group(2) or "").strip("_")
    name = (host + ("_" + path if path else "")).strip("_")[:80] or "_task_body"
    return name + ".md"


def _run_one(app, step):
    """跑一步；失败按同族工具换路。返回 (ok, 用到的工具, 结果, 说明)。"""
    from core import tool_gate  # noqa: F401  — 仅确认模块在；任务由载体发起，force=True
    tool = step["tool"]
    tried = []
    chain = [tool]
    try:
        chain += [x for x in app._tool_fallback_for(tool) if x != tool]
    except Exception:      # noqa: silent-ok — 没有兜底链就只试原工具
        pass
    last = ""
    for cand in chain[:3]:
        tried.append(cand)
        args = dict(step.get("args") or {})
        # __BODY__ 占位：用上一步抓到的正文填（拆解时还不知道正文）
        if args.get("content") == "__BODY__":
            args["content"] = str(step.get("_body") or "")[:20000] or "（上一步没有正文）"
        try:
            res = app.run_tool(cand, args, force=True)
            res = app._tool_result_str(res) if hasattr(app, "_tool_result_str") else str(res)
        except Exception as e:      # noqa: silent-ok — 单步异常不许中断整条任务
            res = "%s: %s" % (type(e).__name__, str(e)[:120])
        ok, why = _step_ok(res)
        if ok:
            return True, cand, str(res), "第 %d 次尝试成功（%s）" % (len(tried), cand)
        last = "%s 没成：%s" % (cand, why)
        LOG.info("任务步骤：%s", last)
    return False, (tried[-1] if tried else tool), last, "换路后仍失败"


def _verify_step(step, result):
    """按步骤自带的 verify 描述做**可执行的**验收（只做能程序化判定的）。"""
    v = str(step.get("verify") or "")
    s = str(result or "")
    if not s.strip():
        return False, "没有产物"
    if "文件真的存在" in v:
        need_size = "不是空" in v
        m = re.search(r"([A-Za-z]:\\[^\s\"'，。；]+|/[^\s\"'，。；]{3,})", s)
        if m:
            p = m.group(1)
            # 只信"结果里点了名的路径"，不猜
            if not os.path.isfile(p):
                return (False, "结果里说的路径不存在：%s" % p)
            if need_size:
                try:
                    n = os.path.getsize(p)
                except Exception:      # noqa: silent-ok — 拿不到大小就不按大小判
                    return (True, "文件在：%s" % p)
                # 阈值必须**很低**：实测 example.com 这类页面正文转成 Markdown 就只有 158 字节，
                #   第一版设 200 字节，把真页面判成「没把握」→ 整条任务标 partial，是误报。
                #   这里只挡"空壳"（占位符 / 空文件），不评价正文够不够长 —— 长短是用户的事。
                if n < 60:
                    return (False, "文件在但几乎没内容（%d 字节），不像正文：%s" % (n, p))
                return (True, "文件在：%s（%d 字节）" % (p, n))
            return (True, "文件在：%s" % p)
        # 也认"已存清单 / 已写入 <path>"这种说法
        return (True, "结果里没有给出明确路径，按工具成功计")
    if "失败标记" in v:
        # 抓取那步的判据就是「返回非空且无失败标记」—— 直接复用 `_step_ok`（它已经会拆 JSON 判
        # status/error）。原来这里没有分支，掉进最后的默认项，验收结论写的是
        # 「没有专门的验收判据」—— 等于没验收。
        ok, why = _step_ok(s)
        return (ok, why or "非空、无失败标记")
    if "气温数字" in v:
        return (bool(re.search(r"[-+]?\d", s)), "有数字")
    if "IP 样式" in v:
        return (bool(re.search(r"\d+\.\d+\.\d+\.\d+", s)), "有 IP")
    if "条目" in v:
        return (len(s) > 40, "有条目内容")
    return (True, "没有专门的验收判据，按工具成功计")


def _run_task(tid):
    """任务主循环（在后台线程里跑）。"""
    with _LOCK:
        task = load(tid)
        if not task or task.get("state") in ("done", "failed"):
            return
        task["state"] = "running"
        _save(task)
    app = _need_app()
    body = ""
    try:
        for i, step in enumerate(task.get("steps") or []):
            if step.get("state") == "done":
                continue
            if step.get("args", {}).get("content") == "__BODY__":
                step["_body"] = body
            task["current"] = i
            _save(task)
            ok, used, res, note = _run_one(app, step)
            step["tried"] = list(step.get("tried") or []) + [used]
            step["tool_used"] = used
            step["result"] = str(res)[:1200]
            step["note"] = note
            step["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if step.get("tool") in ("get", "fetch", "stealthy_fetch", "bulk_get"):
                body = _body_of(res)     # 只留正文，别把返回外壳一起落到用户文件里
            if not ok:
                step["state"] = "failed"
                task["state"] = "failed"
                task["why"] = "第 %d 步（%s）没做成：%s" % (i + 1, step["tool"], note)
                _save(task)
                _after_fail(task)
                return
            vok, vnote = _verify_step(step, res)
            step["verify_ok"] = bool(vok)
            step["verify_note"] = vnote
            step["state"] = "done"
            _save(task)
            if not vok:
                task["partial"] = True
                task.setdefault("warnings", []).append("第 %d 步验收没把握：%s" % (i + 1, vnote))
        task["state"] = "done"
        task["partial"] = bool(task.get("partial"))
        _save(task)
        _after_done(task)
    except Exception as e:      # noqa: silent-ok — 主循环异常必须落盘并如实标失败
        task["state"] = "failed"
        task["why"] = "任务循环异常：%s: %s" % (type(e).__name__, str(e)[:160])
        _save(task)
        _after_fail(task)


def _after_done(task):
    """做成之后：固化进技能库（下次同类目标可照抄）+ 记经验。"""
    try:
        from core import skill_memory as SK
        trace = [{"tool": s.get("tool_used") or s.get("tool"), "args": s.get("args") or {},
                  "result": s.get("result") or ""} for s in (task.get("steps") or [])]
        ok, why = SK.remember_task(task.get("goal"), trace,
                                   task.get("summary") or "任务完成", seconds=0.0)
        LOG.info("任务 %s 完成，技能固化：%s", task.get("id"), why if not ok else "已固化")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("任务完成：技能固化失败（忽略）：%s", e)
    try:
        from core import experience as EXP
        EXP.record("task_ok", True, need=str(task.get("goal"))[:120],
                   stage="done", lesson="这类目标按这条步骤链能做成")
    except Exception:      # noqa: silent-ok
        pass


def _after_fail(task):
    """失败之后：记经验 + 写改进卡（供人看，也供下次生成时当教训）。"""
    try:
        from core import experience as EXP
        bad = next((s for s in (task.get("steps") or []) if s.get("state") == "failed"), {})
        EXP.remember_forge(str(task.get("goal"))[:120],
                           {"ok": False, "stage": "task", "why": str(task.get("why"))[:200],
                            "attempts": len(bad.get("tried") or []), "tools": [bad.get("tool")]})
    except Exception as e:      # noqa: silent-ok
        LOG.debug("任务失败：记经验失败（忽略）：%s", e)


# ============================== 对外 API ==============================
def start(goal, background=True, max_steps=_MAX_STEPS):
    """开一个任务。返回 (task_id, 说明)。

    `background=True` 时立刻返回，任务在后台线程跑（长任务必须这样，否则用户得等到天荒地老）。
    """
    goal = str(goal or "").strip()
    if len(goal) < 4:
        return "", "目标太短，说清要做成什么（例如「把某站的书目抓下来存到 G:\\dzs」）"
    steps = plan_by_rules(goal)
    plan_from = "规则"
    if not steps:
        steps = plan_by_model(goal)
        plan_from = "模型"
    if not steps:
        return "", ("拆不出可执行的步骤（规则和模型都没给出合规步骤）。"
                    "要不要换个说法，或者直接把网址/目录给我？")
    tid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    task = {"id": tid, "goal": goal, "state": "planning", "plan_from": plan_from,
            "steps": steps[:_MAX_STEPS], "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "partial": False, "warnings": [], "why": ""}
    _save(task)
    LOG.info("任务 %s 已创建（%s 拆解，%d 步）：%s", tid, plan_from, len(task["steps"]), goal[:40])
    if background:
        t = threading.Thread(target=_run_task, args=(tid,), name="xj-task-%s" % tid, daemon=True)
        _RUNNING[tid] = t
        t.start()
        return tid, "已开始（%s 拆解成 %d 步，后台在跑）" % (plan_from, len(task["steps"]))
    _run_task(tid)
    return tid, "已跑完（同步）"


def resume(tid):
    """把某个没跑完的任务接着跑（进程重启后也能用，因为状态在磁盘上）。"""
    task = load(tid)
    if not task:
        return False, "没有这个任务：%s" % tid
    if task.get("state") == "done":
        return False, "这个任务已经完成了"
    todo = [s for s in (task.get("steps") or []) if s.get("state") != "done"]
    if not todo:
        return False, "没有待做的步骤"
    for s in (task.get("steps") or []):
        if s.get("state") == "failed":
            s["state"] = "pending"          # 失败步重置，重跑一次
    task["state"] = "running"
    _save(task)
    t = threading.Thread(target=_run_task, args=(tid,), name="xj-task-%s" % tid, daemon=True)
    _RUNNING[tid] = t
    t.start()
    return True, "接着跑（还剩 %d 步）" % len(todo)


def status(tid):
    """任务详情（含每步结果与验收）。"""
    task = load(tid)
    if not task:
        return None
    done = sum(1 for s in (task.get("steps") or []) if s.get("state") == "done")
    return {"id": task.get("id"), "goal": task.get("goal"), "state": task.get("state"),
            "plan_from": task.get("plan_from"), "progress": "%d/%d" % (done, len(task.get("steps") or [])),
            "partial": bool(task.get("partial")), "why": task.get("why"),
            "warnings": task.get("warnings") or [],
            "steps": [{"i": i + 1, "tool": s.get("tool"), "used": s.get("tool_used"),
                       "state": s.get("state"), "verify_ok": s.get("verify_ok"),
                       "verify_note": s.get("verify_note"), "note": s.get("note"),
                       "result_head": str(s.get("result") or "")[:160]}
                      for i, s in enumerate(task.get("steps") or [])]}


def stats():
    ts = list_tasks(limit=200)
    by = {}
    for t in ts:
        by[t["state"]] = by.get(t["state"], 0) + 1
    return {"total": len(ts), "by_state": by, "dir": _DIR}


# ============================== 做完要主动说 ==============================
# 【为什么需要】任务在后台跑，用户不一定守着。做完只写进磁盘、等人来问，
#   等于"做了"但"没交付"。这里留一个**一次性播报位**：下一次对话开始前取走，
#   贴在回答最前面；取过就再也不提（不重复念、不堆积）。
def _notice_line(task):
    st = str(task.get("state") or "")
    steps = task.get("steps") or []
    done = sum(1 for s in steps if s.get("state") == "done")
    goal = str(task.get("goal") or "")[:40]
    if st == "done":
        tail = "，有 %d 处验收没把握（已标 partial）" % len(task.get("warnings") or []) \
            if task.get("partial") else "，每步验收都过了"
        return "✅ 你先前开的任务 `%s` 做完了（%d/%d 步）%s —— 目标：%s" % (
            task.get("id"), done, len(steps), tail, goal)
    if st == "failed":
        return "⚠️ 你先前开的任务 `%s` 没做成（%d/%d 步）：%s —— 目标：%s" % (
            task.get("id"), done, len(steps), str(task.get("why") or "")[:80], goal)
    return ""


def take_notice_text(limit=3):
    """取走还没播报过的完成/失败通知（取过就标 notified，只播一次）。没有就返回空串。"""
    out = []
    try:
        for fn in os.listdir(_DIR) if os.path.isdir(_DIR) else []:
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            try:
                task = load(fn[:-5])
            except Exception:      # noqa: silent-ok — 坏文件跳过
                continue
            if not task or task.get("notified"):
                continue
            if task.get("state") not in ("done", "failed"):
                continue
            line = _notice_line(task)
            if not line:
                continue
            task["notified"] = True
            _save(task)            # 先标再播：宁可漏播一次，也不重复念
            out.append(line)
            if len(out) >= limit:
                break
    except Exception as e:      # noqa: silent-ok — 播报失败不影响这一轮
        LOG.debug("任务播报：取通知失败（忽略）：%s", e)
        return ""
    return "\n".join(out)
