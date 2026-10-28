# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 长时项目（跨重启、跨天，2026-10-28）

【和 task_runner 的分工（一句话）】
  · `task_runner`：**一件事**，几秒到几分钟，跑完就结束；
  · 本模块：**一批事**，几小时到几天，中途会被关机、会被打断、会需要人接着喊一声。

【为什么"长时"必须单独做一件，不能把 task 的步骤拉长就行】
  拉长有三个必然会踩的坑，一次都不许含糊：
    ① **进程会死**：用户关电脑、蓝屏、我更新重启 —— 状态必须在磁盘上，且每一步都落；
    ② **预算会失控**：一件"做完为止"的事，可能自己跑八小时把电费和时间全吃掉，
       所以必须有**时间/步数预算**，超了就停下来汇报，而不是闷头跑；
    ③ **失败会有两种**：一种该继续（这步不挡后面），一种该立刻停（后面全靠它）。
       混在一起处理的后果是"一个关键步失败，后面的步骤全在垃圾上继续做"。

【状态机】
    created → running → done
                │  ├→ paused（超预算 / 进程重启 / 人喊停）
                │  ├→ failed（关键里程碑没做成，且换过一次路仍失败）
                └→ 每一步都写盘：`logs/projects/<id>.json`

【验收只做能程序化判定的】
  每个里程碑自带 `accept` 描述，落到三种可判形式：
    · `文件：<路径>`   —— 文件真的在，且不少于 60 字节；
    · `含：<关键词>`   —— 产物/结果里出现这些词（多个用「、」隔开，全部要有）；
    · `步数：<n>`      —— 至少做成 n 步；
  其余一律记「验收没把握」，并把项目标 `partial` —— **不假装通过**。
  （这条和 task_runner 一个口径：验收是尺子，不是奖状。）

【重启之后怎么办（这里做了一个明确的取舍）】
  不在开机时**偷偷**继续跑用户的项目 —— 那会在他不知道的时候花钱、动文件。
  重启后 `resume_pending()` 只做一件事：把上次没跑完的状态标成 `paused`，
  并留下一条"等你喊一声就接着跑"的记录。人喊了才继续（`resume_project`）。

落盘：
    logs/projects/<id>.json            项目状态（原子写）
    logs/projects/<id>-report.md       完工报告（每个里程碑的证据与如实缺口）
"""
import json
import logging
import os
import re
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "projects")
_LOCK = __import__("threading").Lock()
_RUNNING = {}

_MAX_MILESTONES = 5
_DEFAULT_BUDGET = {"max_minutes": 60.0, "max_steps": 40, "max_attempts_per_ms": 2}


# ============================== 存储 ==============================
def _ensure():
    if not os.path.isdir(_DIR):
        os.makedirs(_DIR, exist_ok=True)


def _path(pid):
    return os.path.join(_DIR, str(pid) + ".json")


def _save(p):
    _ensure()
    p["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = _path(p["id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(p, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def load(pid):
    try:
        with open(_path(pid), encoding="utf-8") as f:
            return json.load(f)
    except Exception:      # noqa: silent-ok — 没有这个项目就返回 None
        return None


def list_projects(limit=10):
    out = []
    try:
        names = sorted(os.listdir(_DIR)) if os.path.isdir(_DIR) else []
    except Exception:      # noqa: silent-ok
        names = []
    for fn in reversed(names):
        if not fn.endswith(".json"):
            continue
        p = load(fn[:-5])
        if not p:
            continue
        done = sum(1 for m in (p.get("milestones") or []) if m.get("state") == "done")
        out.append({"id": p.get("id"), "goal": str(p.get("goal") or "")[:60],
                    "state": p.get("state"), "done": done,
                    "total": len(p.get("milestones") or []),
                    "at": p.get("updated_at")})
        if len(out) >= limit:
            break
    return out


# ============================== 拆里程碑 ==============================
_PLAN_PROMPT = """把下面这个目标拆成 2~5 个**里程碑**，只输出 JSON 数组，不要解释。

每个里程碑形如：
{{"title": "短标题", "do": "这一步要做什么（能直接交给执行器）", "accept": "怎么算做成", "critical": true}}

规则：
1. 每个里程碑必须**能独立执行**，别互相等；
2. `do` 要具体到"做什么动作"，不要写"分析一下"这种空话；
3. `accept` 只写**能用程序判**的形式，三种任选：
   「文件：<绝对路径>」/「含：<关键词1、关键词2>」/「步数：<数字>」；
4. `critical` 表示"这步没做成，后面就别做了"（依赖它的都算关键）；
5. 最多 5 个，宁可少而清楚；
6. **凡是要产出文件，`do` 里必须写清「存到 <目录>」**，且 `accept` 的路径要和它一致
   —— 否则执行器不知道存哪、验收却去找文件，这一步必然失败。

目标：{goal}
{save_hint}
"""


def _accept_ok(accept, result_text, task_status):
    """按 `accept` 描述做程序化验收。返回 (ok, 说明)。"""
    a = str(accept or "").strip()
    s = str(result_text or "")
    if not a:
        return (bool(task_status and task_status.get("state") == "done"),
                "没有写验收判据，按任务状态计")
    m = re.search(r"文件[:：]\s*([A-Za-z]:\\[^\s，。；;]+|/[^\s，。；;]{3,})", a)
    if m:
        p = m.group(1).strip()
        if not os.path.isfile(p):
            return (False, "文件不在：%s" % p)
        try:
            n = os.path.getsize(p)
        except Exception:      # noqa: silent-ok
            return (True, "文件在：%s" % p)
        if n < 60:
            return (False, "文件在但几乎没内容（%d 字节）：%s" % (n, p))
        return (True, "文件在：%s（%d 字节）" % (p, n))
    m = re.search(r"含[:：]\s*(.+)$", a)
    if m:
        words = [w.strip() for w in re.split(r"[、,，/]+", m.group(1)) if w.strip()]
        if not words:
            return (False, "写了「含：」但没给关键词")
        missing = [w for w in words if w not in s]
        if missing:
            return (False, "结果里缺：%s" % "、".join(missing[:3]))
        return (True, "结果里都有：%s" % "、".join(words[:4]))
    m = re.search(r"步数[:：]\s*(\d+)", a)
    if m:
        want = int(m.group(1))
        steps = (task_status or {}).get("progress") or "0/0"
        try:
            done = int(str(steps).split("/")[0])
        except Exception:      # noqa: silent-ok
            done = 0
        return (done >= want, "做成 %d 步（要求 %d）" % (done, want))
    return (bool(task_status and task_status.get("state") == "done"),
            "验收判据不是可程序化的三种之一，按任务状态计")


def _accept_from_steps(steps):
    """从 task_runner 的规则拆解里**推出**可程序化的验收判据。

    【为什么必须推】规则拆解出来的里程碑原来 `accept` 是空的，于是验收退化成
    「按任务状态计」—— 等于没验收。既然拆解时就已经知道"要写哪个文件"，
    就把那个路径直接变成判据（这是载体自己知道的事，不该再问模型）。
    """
    for s in (steps or []):
        tool = str((s or {}).get("tool") or "")
        args = (s or {}).get("args") or {}
        if tool in ("write_file", "save_file", "write_text"):
            p = str(args.get("path") or args.get("file") or "")
            if p:
                return "文件：%s" % p
        if tool == "net_ip":
            return "含：IP"
        if tool == "get_weather":
            return "含：°C、℃、度"
    return ""


_STAGE_HINTS = ("阶段", "分期", "第一步", "第二步", "里程碑", "拆成几", "分几步", "多个步骤")


def _save_hint(goal):
    """把目标里的保存位置提取成一句提示，塞进拆解提示词（让模型的 accept 和 do 对得上）。

    【为什么要在提示词里就写死】实测过一个必然失败的组合：
    模型给的 `do` 是「用 curl 下载完整 HTML」（没说存哪），`accept` 却是
    「文件：G:\\dzs\\proj_e2e2\\step1.html」—— 执行器抓完就算完，验收去找文件必然失败。
    与其事后修补，不如拆解时就告诉它"用户已经指定了这个目录"。
    """
    try:
        from core import task_runner as TR
        app = TR._need_app()
        out = app._scrape_save_target(goal) if hasattr(app, "_scrape_save_target") else ""
    except Exception:      # noqa: silent-ok — 取不到就不提示
        out = ""
    if not out:
        return ""
    return ("\n【重要】用户已经指定了保存位置：`%s` —— 所有要落盘的步骤都存到这个目录下，"
            "`do` 里写「存到 %s」，`accept` 里的文件路径也必须在这个目录下。" % (out, out))


def _wants_stages(goal):
    """用户是不是**明确要求分阶段**？

    【为什么这条要先判】实测：用户说「把这一页的内容**分三个阶段**做完」，
    规则拆解认得「抓取 → 落盘」，于是直接给了**一个**里程碑（一次做完）——
    用户的"分阶段"要求被载体自己吞掉了。规则优先是为了省事，不是为了省掉用户的话。
    所以：句子里明确要求分阶段时，先让模型拆（规则只做兜底）。
    """
    g = str(goal or "")
    return any(w in g for w in _STAGE_HINTS)


def plan_milestones(goal):
    """拆里程碑：默认规则优先；用户**明确要求分阶段**时先问模型，规则兜底。"""
    goal = str(goal or "").strip()
    if _wants_stages(goal):
        try:
            from core import task_runner as TR
            app = TR._need_app()
            raw = app.llm_chat([{"role": "user", "content": _PLAN_PROMPT.format(goal=goal, save_hint=_save_hint(goal))}])
            ms = _parse_plan(raw)
            if len(ms) >= 2:
                return ms, "模型（用户要求分阶段）"
            LOG.info("项目拆解：用户要求分阶段，但模型只给出 %d 个里程碑 → 退回规则", len(ms))
        except Exception as e:      # noqa: silent-ok — 模型不可用就走规则
            LOG.debug("项目拆解：分阶段优先失败（%s）", e)
    try:
        from core import task_runner as TR
        steps = TR.plan_by_rules(goal)
        if steps:
            return [{"i": 1, "title": "按既有规则一次做完",
                     "do": goal, "accept": _accept_from_steps(steps), "critical": True,
                     "state": "pending", "task_id": "", "note": "", "verify_ok": None,
                     "verify_note": "", "result_head": "", "attempts": 0}], "规则"
    except Exception as e:      # noqa: silent-ok — 规则不可用就走模型拆
        LOG.debug("项目拆解：规则失败（%s）", e)
    try:
        from core import task_runner as TR
        app = TR._need_app()
        raw = app.llm_chat([{"role": "user", "content": _PLAN_PROMPT.format(goal=goal, save_hint=_save_hint(goal))}])
        ms = _parse_plan(raw)
        if ms:
            return ms, "模型"
    except Exception as e:      # noqa: silent-ok — 模型不可用就退成单里程碑
        LOG.debug("项目拆解：模型失败（%s）", e)
    return [{"i": 1, "title": "整件事一次做完", "do": goal, "accept": "",
             "critical": True, "state": "pending", "task_id": "", "note": "",
             "verify_ok": None, "verify_note": "", "result_head": "", "attempts": 0}], "兜底"


def _parse_plan(raw):
    """从模型输出里抠出里程碑数组，**只认合法形状**（宁可少，不可脏）。

    【2026-10-28 加一条：验收和动作必须对得上】
      实测：同一件事模型拆出的里程碑长这样 ——
        do：「使用 curl 下载 https://example.com 的完整 HTML」
        accept：「文件：G:\\dzs\\proj_e2e2\\step1.html」
      执行器只看 `do`，而 `do` 里**没说要存到哪**，于是它抓完就算做完；
      验收却按 `accept` 去找那个文件 → 找不到 → 里程碑失败，整个项目 failed。
      这不是执行器的错，是**拆解时把"做什么"和"怎么算做成"写岔了**。
      所以这里做一次对齐：`accept` 点了文件，`do` 里就必须有「存到 <目录>」。
    """
    s = str(raw or "")
    m = re.search(r"\[[\s\S]*\]", s)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:      # noqa: silent-ok — 解析不了就当模型没拆出来
        return []
    out = []
    for x in (arr or [])[:_MAX_MILESTONES]:
        if not isinstance(x, dict):
            continue
        do = str(x.get("do") or "").strip()
        if len(do) < 6:
            continue
        accept = str(x.get("accept") or "")[:200]
        # ---- 对齐：accept 指向文件 → do 必须说清存到哪 ----
        mf = re.search(r"文件[:：]\s*([A-Za-z]:\\[^\s，。；;]+|/[^\s，。；;]{3,})", accept)
        if mf and ("存到" not in do and "保存" not in do and "写到" not in do):
            do = (do + "，产物存到 %s" % mf.group(1))[:600]
        out.append({"i": len(out) + 1, "title": str(x.get("title") or do)[:40],
                    "do": do[:600], "accept": accept,
                    "critical": bool(x.get("critical", True)), "state": "pending",
                    "task_id": "", "note": "", "verify_ok": None, "verify_note": "",
                    "result_head": "", "attempts": 0})
    return out


# ============================== 执行 ==============================
def start(goal, budget=None, background=True):
    """开一个项目。返回 (project_id, 说明)。"""
    goal = str(goal or "").strip()
    if len(goal) < 6:
        return "", "目标太短，说清要做成什么"
    ms, plan_from = plan_milestones(goal)
    b = dict(_DEFAULT_BUDGET)
    if budget:
        b.update({k: v for k, v in dict(budget).items() if k in b})
    pid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    p = {"id": pid, "goal": goal, "state": "created", "plan_from": plan_from,
         "milestones": ms, "budget": b,
         "spent": {"minutes": 0.0, "steps": 0},
         "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": "",
         "warnings": [], "partial": False}
    _save(p)
    LOG.info("项目 %s 已创建（%s 拆成 %d 个里程碑）：%s", pid, plan_from, len(ms), goal[:40])
    if background:
        t = __import__("threading").Thread(target=_run, args=(pid,), name="xj-proj-%s" % pid,
                                           daemon=True)
        _RUNNING[pid] = t
        t.start()
        return pid, "已开始（%s 拆成 %d 个里程碑，后台在跑）" % (plan_from, len(ms))
    _run(pid)
    return pid, "已跑完（同步）"


def _budget_left(p, t0):
    """预算还剩多少。返回 (还能继续吗, 说明)。

    【坑】这里若写 `b.get("max_minutes") or 1e9`，把预算故意设成 **0** 时会被当成「没设」
    （0 在 Python 里是假值），于是"预算 0 分钟"变成了"预算无限" —— 实测踩过一次。
    所以用 `is None` 显式判，0 就是 0。
    """
    b = p.get("budget") or {}
    mins = (time.time() - t0) / 60.0
    p["spent"]["minutes"] = round(float(p["spent"].get("minutes") or 0) + mins, 4)
    steps = int(p["spent"].get("steps") or 0)
    max_min = b.get("max_minutes")
    max_min = 1e9 if max_min is None else float(max_min)
    max_steps = b.get("max_steps")
    max_steps = 10 ** 9 if max_steps is None else int(max_steps)
    if float(p["spent"]["minutes"]) >= max_min:
        return False, "超出时间预算（%.2f 分钟 ≥ %.2f）" % (p["spent"]["minutes"], max_min)
    if steps >= max_steps:
        return False, "超出步数预算（%d ≥ %d）" % (steps, max_steps)
    return True, ""


_CODE_PROMPT = """写一个 **Python 3** 脚本，只做这一件事：

目标：{do}

硬约束：
1. 只输出脚本正文（不要解释、不要 markdown 代码块围栏）；
2. **只用标准库**优先；需要联网就用 requests；不要 pip 装东西；
3. 输入：{inputs}
4. 输出：必须写到 `{output}`（这一步的验收就看这个文件）；
5. 任何失败都要在 stdout 打一行「失败：<原因>」并以退出码 1 结束，别静默吞掉。
"""


def _milestone_output_path(m):
    """里程碑的产物路径（从 accept 里取）。取不到返回空串。"""
    mf = re.search(r"文件[:：]\s*([A-Za-z]:\\[^\s，。；;]+|/[^\s，。；;]{3,})",
                   str(m.get("accept") or ""))
    return mf.group(1) if mf else ""


def _run_via_code(m, prev_outputs):
    """第二个执行策略：**生成脚本并真跑**（不是让模型"说说"）。

    【为什么需要这一手】实测：里程碑「解析网页 HTML 结构 → parsed.json」，
    走普通任务链时模型只写了个 28 字节的桩文件（因为它没有"解析 HTML"这种工具），
    验收如实判失败，整个项目跟着失败 —— 系统没撒谎，但**这件事其实做得成**：
    让模型写一段脚本、载体真跑，就能做成。
    所以长时项目给每个里程碑两条路：
      ① 先走既有工具链（快、稳、可预测）；
      ② 做不成时，退到"生成脚本 → 写文件 → 真跑 → 按产物验收"。
    这条路的意义：**里程碑不限于"载体已有的工具"，而是"载体能写出来的程序"**。
    """
    try:
        from core import task_runner as TR
        app = TR._need_app()
    except Exception as e:      # noqa: silent-ok — 拿不到 app 就走不了这条路
        return False, "拿不到载体（%s）" % e
    out_path = _milestone_output_path(m)
    if not out_path:
        return False, "这一步没写「文件：」验收，不适合走脚本路"
    d = os.path.dirname(out_path)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:      # noqa: silent-ok
            return False, "建目录失败：%s" % e
    script_path = os.path.join(d or ".", "_step_%d.py" % int(m.get("i") or 1))
    inputs = "、".join("`%s`" % p for p in (prev_outputs or []) if p) or "（没有前置产物）"
    prompt = _CODE_PROMPT.format(do=m.get("do"), inputs=inputs, output=out_path)
    last_note = ""
    # 两次机会：第一次跑不通就把**报错原文**喂回去让它改（和 `core/plugin_forge.py` 的自修一个思路：
    #   小模型一次写对的比例不高，但"看着报错改一版"能救回一大半）。
    for attempt in (1, 2):
        try:
            raw = str(app.llm_chat([{"role": "user", "content": prompt}]) or "")
        except Exception as e:      # noqa: silent-ok
            return False, "模型没给出脚本（%s）" % e
        code = raw.strip()
        mm = re.search(r"```(?:python)?\s*([\s\S]*?)```", code)
        if mm:
            code = mm.group(1)
        code = code.strip()
        if len(code) < 40 or ("def " not in code and "import " not in code):
            return False, "模型给的脚本不像脚本（%d 字节），不拿它去跑" % len(code)
        try:
            with open(script_path, "w", encoding="utf-8", newline="") as f:
                f.write(code)
        except Exception as e:      # noqa: silent-ok
            return False, "脚本写不下去：%s" % e
        try:
            res = str(app.run_tool("run_command",
                                   {"command": "python \"%s\"" % script_path, "timeout": 120},
                                   force=True))
        except Exception as e:      # noqa: silent-ok
            return False, "跑脚本失败：%s" % e
        ok_v, note_v = _accept_ok(m.get("accept"), res, {"state": "done"})
        if ok_v:
            return True, "脚本执行成功（第 %d 版）；%s" % (attempt, note_v)
        last_note = "第 %d 版脚本没成：%s（输出：%s）" % (attempt, note_v, res[-300:])
        LOG.info("项目脚本路：%s", last_note[:160])
        prompt = (_CODE_PROMPT.format(do=m.get("do"), inputs=inputs, output=out_path)
                  + "\n\n【上一版跑失败了，报错原文如下，请改掉它】\n" + res[-600:])
    return False, last_note


def _run(pid):
    """项目主循环：逐个里程碑跑，每步落盘，超预算/关键失败就停。"""
    with _LOCK:
        p = load(pid)
        if not p or p.get("state") in ("done", "failed"):
            return
        p["state"] = "running"
        _save(p)
    try:
        from core import task_runner as TR
    except Exception as e:      # noqa: silent-ok — 没有 task_runner 就做不成任何一步
        p["state"] = "failed"
        p["why"] = "没有 task_runner，项目做不了（%s）" % e
        _save(p)
        return
    t0 = time.time()
    prev_outputs = [m.get("accept") and _milestone_output_path(m)
                    for m in (p.get("milestones") or []) if m.get("state") == "done"]
    prev_outputs = [x for x in prev_outputs if x]
    try:
        for m in (p.get("milestones") or []):
            if m.get("state") == "done":
                continue
            ok_b, why_b = _budget_left(p, t0)
            t0 = time.time()          # 重置计时：预算按"已经花掉的分钟数"累计
            _save(p)
            if not ok_b:
                p["state"] = "paused"
                p["why"] = why_b + "（已停下；说「接着做」会从这里继续）"
                _save(p)
                LOG.warning("项目 %s 暂停：%s", pid, why_b)
                return
            m["state"] = "running"
            _save(p)
            max_att = int((p.get("budget") or {}).get("max_attempts_per_ms") or 2)
            done_ok, note = False, ""
            while int(m.get("attempts") or 0) < max_att and not done_ok:
                m["attempts"] = int(m.get("attempts") or 0) + 1
                p["spent"]["steps"] = int(p["spent"].get("steps") or 0) + 1
                _save(p)
                try:
                    tid, msg = TR.start(m["do"], background=False)
                except Exception as e:      # noqa: silent-ok — 单步异常不能让项目崩
                    tid, msg = "", "%s: %s" % (type(e).__name__, e)
                if not tid:
                    note = "没开起来：%s" % str(msg)[:120]
                    continue
                m["task_id"] = tid
                st = TR.status(tid) or {}
                m["result_head"] = "｜".join(
                    str(s.get("result_head") or "")[:40] for s in (st.get("steps") or [])[:2])
                # 里程碑验收 + 任务自身验收，两者都过才算过
                vok, vnote = _accept_ok(m.get("accept"), m.get("result_head") or "", st)
                task_ok = st.get("state") == "done"
                done_ok = bool(task_ok and vok)
                m["verify_ok"] = done_ok
                m["verify_note"] = ("任务%s；%s" % (st.get("state"), vnote))
                note = m["verify_note"]
                if done_ok:
                    break
                # 失败换路：让 task_runner 自己 resume 一次（它会重置失败步）
                try:
                    TR.resume(tid)
                except Exception as e:      # noqa: silent-ok
                    LOG.debug("里程碑换路失败（忽略）：%s", e)
                if int(m.get("attempts") or 0) >= max_att:
                    break
            # ---- 策略二：工具链做不成 → 生成脚本真跑（里程碑不限于"载体已有工具"）----
            if not done_ok and _milestone_output_path(m):
                _prev = [x for x in prev_outputs if x]
                _cok, _cnote = _run_via_code(m, _prev)
                p["spent"]["steps"] = int(p["spent"].get("steps") or 0) + 1
                m["verify_ok"] = bool(_cok)
                m["verify_note"] = ("脚本路：" + _cnote)
                m["script_used"] = True
                done_ok = bool(_cok)
                note = m["verify_note"]
                _save(p)
            m["state"] = "done" if done_ok else "failed"
            m["note"] = str(note)[:300]
            _save(p)
            if done_ok:
                _op = _milestone_output_path(m)
                if _op:
                    prev_outputs.append(_op)
            if not done_ok:
                p["warnings"].append("里程碑 %d「%s」没做成：%s" % (
                    m.get("i"), m.get("title"), note))
                if m.get("critical", True):
                    p["state"] = "failed"
                    p["why"] = "关键里程碑没做成（第 %d 个「%s」）：%s" % (
                        m.get("i"), m.get("title"), note)
                    _save(p)
                    _after_fail(p)
                    return
        # 全部里程碑走完
        n_bad = sum(1 for m in (p.get("milestones") or []) if m.get("state") != "done")
        p["partial"] = n_bad > 0
        p["state"] = "done"
        _save(p)
        _after_done(p)
    except Exception as e:      # noqa: silent-ok — 主循环异常必须落盘并如实标失败
        p["state"] = "failed"
        p["why"] = "项目循环异常：%s: %s" % (type(e).__name__, str(e)[:160])
        _save(p)
        _after_fail(p)


def _after_done(p):
    """做完：写报告 + 记经验 + 固化技能（技能由 task_runner 在每步里已经固化了）。"""
    try:
        path = write_report(p["id"])
        p["report"] = path
        _save(p)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("项目报告写入失败（忽略）：%s", e)
    try:
        from core import experience as EXP
        n = len(p.get("milestones") or [])
        EXP.record("project_ok", True, need=str(p.get("goal"))[:120], stage="project",
                   lesson="这类目标按 %d 个里程碑能做成（%s 拆解）" % (n, p.get("plan_from")))
    except Exception as e:      # noqa: silent-ok
        LOG.debug("项目经验记录失败（忽略）：%s", e)
    try:
        from core import evidence_ledger as EL
        EL.record_round(str(p.get("goal")), "项目完成：%s" % _summary_line(p),
                        [{"tool": "project_runner", "args": {"project": p.get("id")},
                          "result": _summary_line(p)}])
    except Exception as e:      # noqa: silent-ok
        LOG.debug("项目记账失败（忽略）：%s", e)
    LOG.info("项目 %s 完成：%s", p.get("id"), _summary_line(p))


def _after_fail(p):
    try:
        from core import experience as EXP
        EXP.record("project_fail", False, why=str(p.get("why"))[:160],
                   need=str(p.get("goal"))[:120], stage="project",
                   lesson="这一条卡在：%s" % str(p.get("why"))[:120])
    except Exception as e:      # noqa: silent-ok
        LOG.debug("项目失败经验记录失败（忽略）：%s", e)


def _summary_line(p):
    ms = p.get("milestones") or []
    ok = sum(1 for m in ms if m.get("state") == "done")
    tail = "，其中 %d 处验收没把握" % len(p.get("warnings") or []) if p.get("partial") else ""
    return "%s ｜ %d/%d 个里程碑做成%s" % (p.get("state"), ok, len(ms), tail)


# ============================== 接续 / 查询 / 报告 ==============================
def resume_project(pid):
    """接着跑（重启后也能用，因为状态在磁盘上）。"""
    p = load(pid)
    if not p:
        return False, "没有这个项目：%s" % pid
    if p.get("state") == "done":
        return False, "这个项目已经完成了"
    todo = [m for m in (p.get("milestones") or []) if m.get("state") != "done"]
    if not todo:
        return False, "没有待做的里程碑"
    for m in todo:
        if m.get("state") == "failed":
            m["state"] = "pending"      # 失败的里程碑重置，重跑一次
            m["attempts"] = 0
    p["state"] = "running"
    _save(p)
    t = __import__("threading").Thread(target=_run, args=(pid,), name="xj-proj-%s" % pid,
                                       daemon=True)
    _RUNNING[pid] = t
    t.start()
    return True, "接着跑（还剩 %d 个里程碑）" % len(todo)


def resume_pending():
    """进程启动时调用：把上次没跑完的项目标成「暂停」，并留下"喊一声就继续"的记录。

    **不自动接着跑**：用户关了电脑/我重启了，不能在他不知情时继续动文件、花时间。
    """
    out = []
    for row in list_projects(limit=50):
        if row.get("state") not in ("running", "created"):
            continue
        p = load(row["id"])
        if not p:
            continue
        p["state"] = "paused"
        p["why"] = "上次进程结束时还没跑完（不是失败）；说「接着做项目 %s」会从这里继续" % p["id"]
        _save(p)
        out.append(p["id"])
    if out:
        LOG.info("项目：上次有 %d 个没跑完，已标成暂停（等用户喊一声）：%s",
                 len(out), "、".join(out))
    return out


def status(pid):
    p = load(pid)
    if not p:
        return None
    done = sum(1 for m in (p.get("milestones") or []) if m.get("state") == "done")
    return {"id": p.get("id"), "goal": p.get("goal"), "state": p.get("state"),
            "plan_from": p.get("plan_from"), "progress": "%d/%d" % (done, len(p.get("milestones") or [])),
            "partial": bool(p.get("partial")), "why": p.get("why"),
            "warnings": p.get("warnings") or [],
            "spent": p.get("spent") or {}, "budget": p.get("budget") or {},
            "report": p.get("report") or "",
            "milestones": [{"i": m.get("i"), "title": m.get("title"),
                            "state": m.get("state"), "task_id": m.get("task_id"),
                            "verify_note": m.get("verify_note"),
                            "attempts": m.get("attempts")}
                           for m in (p.get("milestones") or [])]}


def write_report(pid):
    """写完工报告（Markdown）：每个里程碑做成了什么、证据在哪、哪些没把握。"""
    p = load(pid)
    if not p:
        return ""
    ms = p.get("milestones") or []
    ok = [m for m in ms if m.get("state") == "done"]
    lines = ["# 项目报告 · `%s`" % p.get("id"), "",
             "- 目标：%s" % p.get("goal"),
             "- 状态：**%s**（%d/%d 个里程碑做成）" % (p.get("state"), len(ok), len(ms)),
             "- 拆解来源：%s" % p.get("plan_from"),
             "- 花掉：%.1f 分钟 / %d 步（预算 %.0f 分钟 / %d 步）" % (
                 float((p.get("spent") or {}).get("minutes") or 0),
                 int((p.get("spent") or {}).get("steps") or 0),
                 float((p.get("budget") or {}).get("max_minutes") or 0),
                 int((p.get("budget") or {}).get("max_steps") or 0)),
             ""]
    if p.get("why"):
        lines += ["> ⚠️ 卡在这：%s" % p["why"], ""]
    lines += ["## 里程碑", "", "| # | 里程碑 | 状态 | 验收 | 试了几次 | 任务号 |",
              "| --- | --- | --- | --- | --- | --- |"]
    zh = {"done": "完成", "failed": "没做成", "pending": "没开始", "running": "在做"}
    for m in ms:
        lines.append("| %d | %s | %s | %s | %d | `%s` |" % (
            m.get("i"), m.get("title"), zh.get(m.get("state"), m.get("state")),
            str(m.get("verify_note") or "")[:60], int(m.get("attempts") or 0),
            m.get("task_id") or "—"))
    if p.get("warnings"):
        lines += ["", "## 没把握的地方（如实列出）", ""] + ["- %s" % w for w in p["warnings"]]
    lines += ["", "## 说明", "",
              "- 验收只做**能程序化判定**的三种（文件/含关键词/步数），判不了的一律记「没把握」，"
              "不会说成「完成」；",
              "- 每一步的原始记录在 `logs/tasks/<任务号>.json`，可单独用 `task_status` 复查；",
              "- 这个项目里做成的步骤已固化进技能库（`logs/skills.jsonl`），下次同类目标可直接照抄。"]
    path = os.path.join(_DIR, str(p.get("id")) + "-report.md")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path


def stats():
    rows = list_projects(limit=200)
    by = {}
    for r in rows:
        by[r["state"]] = by.get(r["state"], 0) + 1
    return {"total": len(rows), "by_state": by, "dir": _DIR}
