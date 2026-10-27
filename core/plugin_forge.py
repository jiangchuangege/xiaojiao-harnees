# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 能力自增长（自写插件闭环，2026-10-17）

【这是什么】用户提了一个"我现在没有的能力"时，小焦**自己写一个插件补上**：
  说需求 → 生成插件代码 → **静态检查** → **子进程沙箱试跑** → 不过就**回喂模型自修** → 通过才落地。

【为什么敢做这件事】"让模型写代码"不新鲜，新鲜的是**每一道关都不是模型说了算**：
  ① 静态检查（`ast`）：必须是插件契约（`get_tool_descriptions` / `execute` / `get_plugin`），
     import 必须在白名单里，不许出现 `os.system` / `subprocess` / `eval` / `exec` / 删文件；
  ② 沙箱试跑：**另起子进程**、在临时目录 import 它、校验参数 schema 合规，
     再用最小参数调一次 `execute()`，要求"不抛异常、返回非空字符串"；
  ③ 自修复：检查没过就把**错误原文回喂模型**让它改，最多 2 轮
     （实测 4B 一次成功率大约一半，不给自修复等于抽奖）；
  ④ 落地不覆盖：文件名带时间戳，**同名绝不覆盖**（本项目"只加不删"）。

【边界（写死，不给开关）】
  · 只写 `plugins/gen_*.py`，不碰 `core/`、不碰 `xiaojiao_app.py`；
  · 危险调用直接判死（即使它"能跑"）；
  · 生成的工具说明必须带「什么时候用」（模型漏了由载体补，并如实记下补了几处）；
  · 落地后**要重启或热注册才生效** —— 明确告诉用户，不假装"已经能用了"。
"""
import ast
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PLUGINS = os.path.join(_ROOT, "plugins")

# import 白名单：只允许"纯功能"的库（这些不足以破坏系统）
_ALLOWED_IMPORTS = {
    "re", "json", "time", "math", "datetime", "random", "hashlib", "base64", "uuid",
    "os", "os.path", "pathlib", "collections", "itertools", "functools", "typing",
    "urllib", "urllib.parse", "urllib.request", "requests", "string", "textwrap",
    "csv", "io", "statistics", "decimal", "calendar", "html", "html.parser",
}
# 危险调用：出现即判不合格（"能跑"也不行）
_FORBIDDEN_CALLS = {
    "system", "popen", "spawn", "spawnl", "execv", "execve", "fork", "kill",
    "rmtree", "unlink", "remove", "removedirs", "rmdir",
    "eval", "exec", "compile", "__import__", "input",
    "setattr", "delattr", "globals", "locals", "vars",
}

_PROMPT = """你是小焦插件作者。为需求写一个**单文件 Python 插件**，严格遵守：
1) 一个类，含 `get_tool_descriptions(self)` 返回工具列表：
   [{{"name": "英文小写工具名（只允许字母数字下划线，例如 cn_num_to_int）",
     "description": "中文说明（含「什么时候用」一句具体场景，60 字内）",
     "parameters": {{"type": "object", "properties": {{"参数名": {{"type": "string",
     "description": "这个参数是什么"}}}}, "required": ["必填参数"]}}}}]
2) 含 `execute(self, tool_name, params)`：按 tool_name 分派；**一律返回中文字符串**；
   **绝不抛异常**（用 try/except 兜住，把原因写成中文返回）。
3) 文件末尾 `def get_plugin(): return 你的类()`
4) 只许 import 这些：{allowed}
5) 不许用 subprocess / os.system / eval / exec / 删文件 这类危险调用。
6) 代码尽量短（60 行以内），不要在文件里写示例调用。

【照着这两个真实插件的样子写（骨架对齐，别照抄内容）】
{examples}

【这类需求以前栽过的地方（务必避开）】
{lessons}

需求：{need}

只输出完整 Python 代码，不要解释、不要 Markdown 代码围栏。"""

_FIX_PROMPT = """你上一个 Python 插件没过检查。请**只修检查指出的问题**，其它保持不动，输出完整代码。

需求：{need}

【检查给的问题】
{why}

【你上一版代码】
{code}

要求仍然一样：类里有 get_tool_descriptions / execute，末尾 get_plugin()，
一律返回中文字符串、不抛异常，只许用这些 import：{allowed}。代码控制在 60 行内。
只输出完整 Python 代码，不要解释、不要代码围栏。"""


def _base_url_v1():
    """大脑服务地址（读控制文件；读不到用本机 9292）。"""
    try:
        p = os.path.join(_ROOT, "xiaojiao_control.json")
        c = json.load(open(p, encoding="utf-8"))
        b = str(((c.get("brain") or {}).get("api") or {}).get("base_url") or "").rstrip("/")
        if b:
            return b if b.endswith("/v1") else b + "/v1"
    except Exception as e:      # noqa: silent-ok — 读不到就用默认
        LOG.debug("自增长：读配置失败（用默认 9292）：%s", e)
    return "http://127.0.0.1:9292/v1"


def _sanitize_module_name(s):
    """从需求里起一个安全的模块名：gen_<ascii片段>_<时间戳>。"""
    t = re.sub(r"[^A-Za-z0-9_]", "", str(s or ""))[:20].lower() or "cap"
    return "gen_%s_%s" % (t, time.strftime("%Y%m%d_%H%M%S"))


def _ensure_contract_phrases(code, need):
    """把「什么时候用」补进**每个工具条目的那段说明**里。返回 (新代码, 补了几处)。

    【为什么只补工具级、不补参数级】第一版用一条正则把所有 `"description": "..."` 全补了，
    结果参数说明里也被塞进「什么时候用：…」——读起来很蠢，也让工具说明变噪声。
    现在按 `"name":` 切块，每块**只补第一个 description**（那就是工具级说明）。
    """
    short = re.sub(r"\s+", " ", str(need or "")).strip()[:28] or "需要用到这个能力时"
    fixed = {"n": 0}
    # 以 "name" 出现的位置切块：每块内第一次出现的 description 就是工具级说明
    parts = re.split(r'("name"\s*:)', code)
    out = [parts[0]]
    i = 1
    while i < len(parts):
        marker, body = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        done = {"hit": False}

        def repl(m):
            if done["hit"]:
                return m.group(0)          # 同一块里的后续 description（参数级）不动
            done["hit"] = True
            text = m.group(1)
            if "什么时候用" in text:
                return m.group(0)
            fixed["n"] += 1
            tail = (" 什么时候用：%s" % short).replace('"', "")
            return '"description": "%s%s"' % (text, tail)

        body = re.sub(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', repl, body)
        out.append(marker)
        out.append(body)
        i += 2
    return "".join(out), fixed["n"]


def static_check(code):
    """静态检查。返回 (ok, 问题列表)。问题用中文写，直接能给人看。"""
    problems = []
    src = str(code or "").strip()
    if not src:
        return False, ["生成结果是空的"]
    src = re.sub(r"^```(?:python)?\s*", "", src)
    src = re.sub(r"\s*```$", "", src).strip()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, ["语法错误：第 %s 行 %s" % (e.lineno, e.msg)]

    top_funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "get_plugin" not in top_funcs:
        problems.append("缺少 `def get_plugin()`（插件契约要求）")

    has_desc = has_exec = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names = {f.name for f in node.body if isinstance(f, ast.FunctionDef)}
            if "get_tool_descriptions" in names:
                has_desc = True
            if "execute" in names:
                has_exec = True
    if not has_desc:
        problems.append("类里缺 `get_tool_descriptions()`")
    if not has_exec:
        problems.append("类里缺 `execute()`")

    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        for m in mods:
            base = (m or "").split(".")[0]
            if m not in _ALLOWED_IMPORTS and base not in _ALLOWED_IMPORTS:
                problems.append("不允许的 import：%s" % m)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = ""
            if isinstance(fn, ast.Attribute):
                name = fn.attr
            elif isinstance(fn, ast.Name):
                name = fn.id
            if name in _FORBIDDEN_CALLS:
                problems.append("出现危险调用：%s（这个项目不允许）" % name)

    if not re.search(r"[\u4e00-\u9fff]", src):
        problems.append("代码里完全没有中文说明（模型会选不对工具）")
    return (not problems), problems


_SANDBOX_CODE = r'''
import importlib.util, json, re, sys
path = sys.argv[1]
spec = importlib.util.spec_from_file_location("forge_candidate", path)
mod = importlib.util.module_from_spec(spec)
sys.modules["forge_candidate"] = mod
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(json.dumps({"ok": False, "why": "import 失败：%s: %s" % (type(e).__name__, e)},
                     ensure_ascii=False)); raise SystemExit(0)
fn = getattr(mod, "get_plugin", None)
if not callable(fn):
    print(json.dumps({"ok": False, "why": "没有可调用的 get_plugin()"}, ensure_ascii=False))
    raise SystemExit(0)
try:
    plug = fn()
    descs = plug.get_tool_descriptions()
except Exception as e:
    print(json.dumps({"ok": False, "why": "get_tool_descriptions 抛异常：%s: %s"
                      % (type(e).__name__, e)}, ensure_ascii=False)); raise SystemExit(0)
if not isinstance(descs, list) or not descs:
    print(json.dumps({"ok": False, "why": "get_tool_descriptions 没有返回非空列表"},
                     ensure_ascii=False)); raise SystemExit(0)
bad = []
for d in descs:
    if not isinstance(d, dict) or not d.get("name"):
        bad.append("条目缺 name")
        continue
    nm = str(d.get("name"))
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,40}", nm):
        bad.append("%s：工具名必须是英文字母开头、只含字母数字下划线（中文名调不准）" % nm[:20])
    p = d.get("parameters") or {}
    if p and (p.get("type") != "object" or not isinstance(p.get("properties"), dict)):
        bad.append("%s 的 parameters 不是标准 JSON Schema" % d.get("name"))
    if "什么时候用" not in str(d.get("description") or ""):
        bad.append("%s 的说明里没有「什么时候用」" % d.get("name"))
if bad:
    print(json.dumps({"ok": False, "why": "；".join(bad[:4])}, ensure_ascii=False))
    raise SystemExit(0)
name = str(descs[0].get("name"))
try:
    out = plug.execute(name, {})
    if not isinstance(out, str):
        print(json.dumps({"ok": False, "why": "execute 没返回字符串（返回类型 %s）"
                          % type(out).__name__}, ensure_ascii=False)); raise SystemExit(0)
except Exception as e:
    print(json.dumps({"ok": False, "why": "execute 抛异常：%s: %s" % (type(e).__name__, e)},
                     ensure_ascii=False)); raise SystemExit(0)
note = "调用成功" if out.strip() else "空参数返回空串（可接受：缺参数时本来就该这样）"
print(json.dumps({"ok": True, "tools": [d.get("name") for d in descs],
                  "sample": (out[:120] or note)}, ensure_ascii=False))
'''


def sandbox_run(path, timeout=30):
    """在**子进程**里试跑生成的插件。返回 (ok, 说明, 工具名列表)。"""
    try:
        tmp = tempfile.mkdtemp(prefix="xj_forge_")
        script = os.path.join(tmp, "_sandbox.py")
        io.open(script, "w", encoding="utf-8").write(_SANDBOX_CODE)
        env = dict(os.environ)
        env["XIAOJIAO_FORGE_SANDBOX"] = "1"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, script, path], capture_output=True, text=True,
                           timeout=timeout, cwd=tmp, env=env, encoding="utf-8",
                           errors="replace")
        out = (r.stdout or "").strip().splitlines()
        if not out:
            return False, "沙箱没有输出（stderr：%s）" % (r.stderr or "")[:200], []
        try:
            d = json.loads(out[-1])
        except Exception:
            return False, "沙箱输出看不懂：%s" % out[-1][:200], []
        return bool(d.get("ok")), str(d.get("why") or d.get("sample") or ""), \
            list(d.get("tools") or [])
    except subprocess.TimeoutExpired:
        return False, "沙箱试跑超时（%ds）" % timeout, []
    except Exception as e:
        return False, "沙箱跑不起来：%s: %s" % (type(e).__name__, str(e)[:120]), []


def _few_shot(max_files=2, max_lines=32):
    """从仓库现有插件里挑**最短的两个**当骨架样例，喂给生成模型。

    【为什么喂真代码而不是继续描述】实测：光靠文字说"要有 get_tool_descriptions/execute"，
    4B 仍然会漏（漏「什么时候用」、把工具名写成中文）。给它看两个**真实能跑**的插件骨架，
    比加三条要求有效得多 —— 这是"少说多给例子"的工程常识，也是喂样例而不是喂规则的原因。
    只读前 max_lines 行：只取骨架形态，不需要业务逻辑（也就不会把别人的业务抄错）。
    """
    try:
        files = []
        for fn in os.listdir(_PLUGINS):
            if not fn.endswith(".py") or fn.startswith("_") or fn == "forge.py":
                continue
            p = os.path.join(_PLUGINS, fn)
            try:
                with io.open(p, encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception:      # noqa: silent-ok — 单个文件读不了就跳过
                continue
            files.append((len(lines), fn, lines[:max_lines]))
        files.sort()
        out = []
        for n, fn, lines in files[:max_files]:
            body = "".join(lines).rstrip()
            out.append("--- 样例：%s（共 %d 行，这里只看前 %d 行）---\n%s"
                       % (fn, n, min(n, max_lines), body))
        return "\n\n".join(out) if out else "（仓库里暂时没有可参考的插件）"
    except Exception as e:      # noqa: silent-ok — 拿不到样例也不能挡住生成
        LOG.debug("自增长：取样例失败（忽略）：%s", e)
        return "（样例取不到，按契约写即可）"


def _lessons_block(need):
    """把经验库里"这类需求以前栽过的坑"整理成几行，注入提示词。"""
    try:
        from core import experience as EXP
        rows = EXP.lessons("forge_fail", keyword=need, limit=3)
        if not rows:
            return "（还没有同类失败记录 —— 这是第一次做这类能力）"
        lines = []
        for r in rows:
            ls = str(r.get("lesson") or "").strip()
            why = str(r.get("why") or "").strip()[:60]
            if ls:
                lines.append("- %s（当时的问题：%s）" % (ls, why))
        return "\n".join(lines) if lines else "（有失败记录但没提炼出教训）"
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自增长：取教训失败（忽略）：%s", e)
        return "（教训库不可用）"


def _ask_model(need):
    """用本机模型生成插件代码（失败返回空串，不抛异常）。"""
    try:
        import requests
        prompt = _PROMPT.format(allowed=", ".join(sorted(_ALLOWED_IMPORTS)),
                                need=str(need)[:400],
                                examples=_few_shot(), lessons=_lessons_block(need))
        for model in ("qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder", "xiaojiao"):
            try:
                r = requests.post(_base_url_v1() + "/chat/completions", json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2800, "temperature": 0.2,
                }, timeout=180)
                if r.status_code == 200:
                    return str(((r.json().get("choices") or [{}])[0].get("message") or {})
                               .get("content") or "")
            except Exception:      # noqa: silent-ok — 换下一个模型再试
                continue
    except Exception as e:      # noqa: silent-ok — 生成失败就如实返回空
        LOG.warning("自增长：生成异常 %s: %s", type(e).__name__, e)
    return ""


def _ask_model_fix(need, code, why):
    """把检查结果回喂模型让它改。失败返回空串。"""
    try:
        import requests
        prompt = _FIX_PROMPT.format(need=str(need)[:300], why=str(why)[:600],
                                    code=str(code)[:4000],
                                    allowed=", ".join(sorted(_ALLOWED_IMPORTS)))
        for model in ("qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder", "xiaojiao"):
            try:
                r = requests.post(_base_url_v1() + "/chat/completions", json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2800, "temperature": 0.1,
                }, timeout=180)
                if r.status_code == 200:
                    return str(((r.json().get("choices") or [{}])[0].get("message") or {})
                               .get("content") or "")
            except Exception:      # noqa: silent-ok — 换下一个模型再试
                continue
    except Exception as e:      # noqa: silent-ok
        LOG.warning("自增长：修复调用失败 %s: %s", type(e).__name__, e)
    return ""


def _strip_fence(code):
    t = re.sub(r"^```(?:python)?\s*", "", str(code or "").strip())
    return re.sub(r"\s*```$", "", t).strip()


def forge(need, generator=None, dry_run=False, timeout=30, max_repair=2):
    """完整闭环：生成 → 静态检查 →（不过则自修）→ 沙箱试跑 → 落地（或如实失败）。

    `generator`：callable(need) -> code；给了就**只**用它（自测打桩，不回落真调模型）。
    `dry_run=True`：走完全部检查但不写文件（评测/自测用）。
    """
    need = str(need or "").strip()
    if not need:
        return {"ok": False, "stage": "input", "why": "没说清要什么能力", "code": ""}

    if generator is not None:
        try:
            code = str(generator(need) or "")
        except Exception as e:
            return {"ok": False, "stage": "generate",
                    "why": "生成器出错：%s: %s" % (type(e).__name__, str(e)[:100]), "code": ""}
        if not code.strip():
            return {"ok": False, "stage": "generate", "why": "生成器没有产出代码", "code": ""}
    else:
        code = _ask_model(need)
        if not code:
            return {"ok": False, "stage": "generate",
                    "why": "模型没产出代码（大脑可能没起）", "code": ""}
    code = _strip_fence(code)

    code, _n_fixed = _ensure_contract_phrases(code, need)
    if _n_fixed:
        LOG.info("自增长：载体补了 %d 处「什么时候用」（模型没写全，如实记下）", _n_fixed)

    can_repair = (generator is None) and max_repair > 0
    attempts = 1 + (max_repair if can_repair else 0)
    last = {"ok": False, "stage": "unknown", "why": "没走到任何检查", "code": code}

    for attempt in range(1, attempts + 1):
        ok, problems = static_check(code)
        if not ok:
            last = {"ok": False, "stage": "static", "why": "；".join(problems[:5]),
                    "problems": problems, "code": code}
            if can_repair and attempt < attempts:
                LOG.info("自增长：静态检查没过（%s）→ 第 %d 次自修", problems[0][:40], attempt)
                fix = _ask_model_fix(need, code, last["why"])
                if fix.strip():
                    code = _ensure_contract_phrases(_strip_fence(fix), need)[0]
                    continue
            break
        LOG.info("自增长：静态检查通过（第 %d 次）", attempt)

        module = _sanitize_module_name(need)
        target = os.path.join(_PLUGINS, module + ".py")
        if os.path.exists(target):          # 只加不删：同名不覆盖
            module = "%s_%d" % (module, int(time.time()))
            target = os.path.join(_PLUGINS, module + ".py")
        tmpdir = tempfile.mkdtemp(prefix="xj_forge_chk_")
        tmp_path = os.path.join(tmpdir, module + ".py")
        io.open(tmp_path, "w", encoding="utf-8").write(code)
        ok2, why2, tools = sandbox_run(tmp_path, timeout=timeout)
        if not ok2:
            last = {"ok": False, "stage": "sandbox", "why": why2, "code": code}
            if can_repair and attempt < attempts:
                LOG.info("自增长：沙箱没过（%s）→ 第 %d 次自修", str(why2)[:40], attempt)
                fix = _ask_model_fix(need, code, why2)
                if fix.strip():
                    code = _ensure_contract_phrases(_strip_fence(fix), need)[0]
                    continue
            break
        LOG.info("自增长：沙箱试跑通过（工具：%s，第 %d 次）", tools, attempt)

        if dry_run:
            _remember(need, {"ok": True, "stage": "dry-run", "tools": tools,
                             "attempts": attempt, "fixed": _n_fixed})
            return {"ok": True, "stage": "dry-run", "why": "全部检查通过（未落地）",
                    "module": module, "path": "", "tools": tools, "code": code,
                    "attempts": attempt, "fixed": _n_fixed}
        try:
            os.makedirs(_PLUGINS, exist_ok=True)
            io.open(target, "w", encoding="utf-8").write(code)
        except Exception as e:
            return {"ok": False, "stage": "write",
                    "why": "写不进 plugins/：%s: %s" % (type(e).__name__, str(e)[:100]),
                    "code": code}
        _remember(need, {"ok": True, "stage": "written", "tools": tools,
                         "attempts": attempt, "fixed": _n_fixed})
        return {"ok": True, "stage": "written", "why": "已落地（重启或热注册后生效）",
                "module": module, "path": target, "tools": tools, "code": code,
                "attempts": attempt, "fixed": _n_fixed}
    _remember(need, last)
    return last


def _remember(need, result):
    """把这次成与败写进经验库（成功率、教训都从这里长出来）。失败不影响主流程。"""
    try:
        from core import experience as EXP
        EXP.remember_forge(need, result)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自增长：记经验失败（忽略）：%s", e)
