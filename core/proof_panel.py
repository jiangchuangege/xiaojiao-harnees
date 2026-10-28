# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自证面板（2026-10-28）

【一句话】把"证据账本 / 交叉核验 / 改进闸门 / 换模型实测 / 长时项目"这五件东西
**一页看完**，全部数字来自磁盘上的真实记录，页面上不写一句手打的话。

【为什么必须有一个页面，而不是只有命令行】
  `tools/*.py` 那些脚本对写代码的人够用，但对使用者来说是"它说它可靠，你自己去跑脚本查"——
  那不叫好用。可核查的价值有一半在**随时能看到**：今天问的哪几条有据、哪个产物变了、
  自己昨天调过什么旋钮、换火种掉不掉分。看不到，就等于没有。

【这个页面**不做**的三件事（很重要）】
  1. **不诊断、不建议、不总结成"很好"**：它只把记录摆出来，结论由数字自己说；
  2. **不写任何常量数字**：每一格都是现读现算（`core/evidence_ledger.py` 等模块的实算结果）；
  3. **不改数据**：纯只读。想看细节就去点那句原始记录（`logs/evidence/rounds/<id>.json`）。

【页面结构】
  ├ 顶部：五张卡片（账本 / 有据率 / 链状态 / 换模型增量 / 闸门落地数）
  ├ 证据账本：最近若干轮，每轮一条（断言几条、复算有据几条、有没有失效产物）
  ├ 交叉核验：最近几次多火种对账（一致几条、一边有据几条、独有无据几条）
  ├ 改进闸门：旋钮当前值 + 最近决策（落地/拒绝/回滚，含"被拒绝"的那些）
  └ 长时项目：状态与里程碑进度
"""
import io
import json
import logging
import os
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _safe(fn, default=None):
    """每一项单独兜异常：面板上一格算不出来，不许让整页打不开。"""
    try:
        return fn()
    except Exception as e:      # noqa: silent-ok — 单格失败就显示"读不到"
        LOG.debug("自证面板：一项读取失败（%s）", e)
        return default


def collect(limit=12):
    """把面板要显示的所有原始数据取回来（纯读取，零副作用）。"""
    from core import evidence_ledger as EL
    from core import gate_evolve as GE
    from core import consensus as CN
    from core import project_runner as PR

    ledger_stats = _safe(EL.stats, {}) or {}
    chain = _safe(EL.verify_chain, {}) or {}
    audit = _safe(lambda: EL.audit_recent(limit=limit), {}) or {}
    gate = _safe(GE.stats, {}) or {}
    gate_hist = _safe(lambda: GE.history(limit=limit), []) or []
    knobs = []
    for k in (_safe(lambda: sorted(GE.KNOBS), []) or []):
        spec = GE.KNOBS.get(k) or {}
        knobs.append({"name": k, "value": _safe(lambda kk=k: GE.knob_read(kk), None),
                      "allowed": spec.get("allowed"), "desc": spec.get("desc")})
    parity = _safe(_parity_summary, {}) or {}
    cn_stats = _safe(CN.stats, {}) or {}
    cn_rows = _safe(lambda: CN.recent(limit=limit), []) or []
    projects = _safe(lambda: PR.list_projects(limit=limit), []) or []
    proj_rows = []
    for p in projects:
        st = _safe(lambda pid=p["id"]: PR.status(pid), None)
        if st:
            proj_rows.append(st)
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ledger": ledger_stats, "chain": chain, "audit": audit,
            "gate": gate, "gate_history": gate_hist, "knobs": knobs,
            "parity": parity, "consensus": cn_stats, "consensus_rows": cn_rows,
            "projects": proj_rows}


def _parity_summary():
    """换模型实测的摘要（读 `docs/capability-parity.json`，没跑过就是空）。"""
    path = os.path.join(_ROOT, "docs", "capability-parity.json")
    if not os.path.isfile(path):
        return {}
    with io.open(path, encoding="utf-8") as f:
        rep = json.load(f)
    return {"at": rep.get("at"), "summary": rep.get("summary") or {},
            "models": rep.get("models") or [], "cases": len(rep.get("cases") or [])}


# ============================== HTML ==============================
_CSS = """
:root{--bg:#0f1216;--card:#171c23;--line:#242c36;--fg:#e6edf3;--dim:#8b98a5;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:28px 0 10px;color:var(--acc)}
.sub{color:var(--dim);font-size:12px;margin-bottom:18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card .k{color:var(--dim);font-size:12px}
.card .v{font-size:20px;font-weight:600;margin-top:2px}
.card .n{color:var(--dim);font-size:11px;margin-top:2px}
table{width:100%;border-collapse:collapse;background:var(--card);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);
font-size:12.5px;vertical-align:top}
th{color:var(--dim);font-weight:500;background:#141a21}
tr:last-child td{border-bottom:none}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.dim{color:var(--dim)}
code{background:#0b0f13;padding:1px 5px;border-radius:4px;font-size:12px}
.foot{margin-top:26px;color:var(--dim);font-size:12px;line-height:1.9}
.empty{color:var(--dim);padding:14px;text-align:center;border:1px dashed var(--line);
border-radius:10px}
"""


def _esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _pct(v):
    try:
        return "%.0f%%" % (float(v) * 100)
    except Exception:      # noqa: silent-ok
        return "—"


def _card(k, v, n=""):
    return ('<div class="card"><div class="k">%s</div><div class="v">%s</div>'
            '<div class="n">%s</div></div>' % (_esc(k), _esc(v), _esc(n)))


def render(d=None):
    """渲染整页 HTML（数据全来自 `collect()`）。"""
    d = d or collect()
    lg = d.get("ledger") or {}
    ch = d.get("chain") or {}
    ag = d.get("audit") or {}
    gt = d.get("gate") or {}
    pa = (d.get("parity") or {}).get("summary") or {}
    cn = d.get("consensus") or {}

    cards = [
        _card("证据账本轮次", lg.get("rounds", 0),
              "快照 %s 份" % lg.get("blobs", 0)),
        _card("可核查断言", lg.get("claims", 0),
              "有据 %s 条（%s）" % (lg.get("supported", 0), _pct(lg.get("ratio")))),
        _card("哈希链", "完整" if ch.get("ok") else "断了",
              "核对 %s 条" % ch.get("checked", 0)),
        _card("换模型增量", ("%+.0f 个百分点" % ((pa.get("lift_mean") or 0) * 100))
              if pa.get("lift_mean") is not None else "还没实测",
              ("裸 %s → 载体 %s" % (_pct(pa.get("bare_fair_mean")),
                                    _pct(pa.get("carrier_fair_mean"))))
              if pa.get("bare_fair_mean") is not None else "跑 tools/parity_report.py"),
        _card("改进闸门", "落地 %s / 拒绝 %s" % (gt.get("accepted", 0), gt.get("rejected", 0)),
              "回滚 %s 次" % gt.get("rolled_back", 0)),
        _card("交叉核验", "%s 次" % cn.get("total", 0),
              "一致 %s ｜ 有问题 %s" % (cn.get("clean", 0), cn.get("flagged", 0))),
    ]
    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>小焦 · 自证</title><style>%s</style></head><body><div class="wrap">' % _CSS,
           '<h1>小焦 · 自证</h1>',
           '<div class="sub">这一页的每个数字都是现读现算的（%s）｜ 来源：'
           'logs/evidence、logs/evolve、logs/consensus、logs/projects、docs/capability-parity.json'
           '</div>' % _esc(d.get("at")),
           '<div class="cards">%s</div>' % "".join(cards)]

    # ---- 证据账本 ----
    out.append('<h2>证据账本（最近 %d 轮，逐轮复算）</h2>' % len(ag.get("details") or []))
    rows = ag.get("details") or []
    if rows:
        out.append('<table><tr><th>轮次</th><th>问题</th><th>断言</th><th>复算有据</th>'
                   '<th>结论</th></tr>')
        for r in reversed(rows):
            cls = "ok" if (r.get("verdict") or "").startswith("可复算一致") else "warn"
            out.append('<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td>'
                       '<td class="%s">%s</td></tr>' % (
                           _esc(r.get("id")), _esc(str(r.get("question") or "")[:46]),
                           r.get("claims") or 0, r.get("supported") or 0, cls,
                           _esc(r.get("verdict"))))
        out.append('</table>')
    else:
        out.append('<div class="empty">还没有记录 —— 用带工具的问几件事，账本才有东西可审</div>')

    # ---- 交叉核验 ----
    out.append('<h2>多火种交叉核验</h2>')
    crows = d.get("consensus_rows") or []
    if crows:
        out.append('<table><tr><th>时间</th><th>问题</th><th>火种</th><th>一致</th>'
                   '<th>单边有据</th><th>独有无据</th><th>结论</th></tr>')
        for r in crows:
            cls = "ok" if r.get("ok") else "warn"
            out.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                       '<td>%s</td><td class="%s">%s</td></tr>' % (
                           _esc(str(r.get("at") or "")[5:16]),
                           _esc(str(r.get("question") or "")[:40]),
                           _esc("、".join(r.get("models") or [])),
                           len(r.get("agree") or []),
                           len(r.get("one_side_supported") or []),
                           len(r.get("unique_unsupported") or []), cls,
                           _esc(r.get("verdict"))))
        out.append('</table>')
    else:
        out.append('<div class="empty">还没做过交叉核验 —— 问「换个火种再看一遍」就会跑一次</div>')

    # ---- 改进闸门 ----
    out.append('<h2>自我改进闸门</h2>')
    knobs = d.get("knobs") or []
    if knobs:
        out.append('<table><tr><th>旋钮</th><th>当前值</th><th>允许取值</th><th>说明</th></tr>')
        for k in knobs:
            out.append('<tr><td><code>%s</code></td><td>%s</td><td class="dim">%s</td>'
                       '<td class="dim">%s</td></tr>' % (
                           _esc(k.get("name")), _esc(k.get("value")),
                           _esc(k.get("allowed")), _esc(k.get("desc"))))
        out.append('</table>')
    hist = d.get("gate_history") or []
    if hist:
        out.append('<h2>闸门决策（含被拒绝的）</h2><table><tr><th>时间</th><th>改动</th>'
                   '<th>旋钮</th><th>改前→改后</th><th>分数</th><th>结论</th></tr>')
        for r in reversed(hist):
            dec = {"accept": ("落地", "ok"), "reject": ("拒绝", "warn"),
                   "rollback": ("回滚", "dim")}.get(r.get("decision"),
                                                    (r.get("decision"), "dim"))
            out.append('<tr><td>%s</td><td>%s</td><td><code>%s</code></td><td>%s → %s</td>'
                       '<td>%s → %s</td><td class="%s">%s</td></tr>' % (
                           _esc(str(r.get("at") or "")[5:16]), _esc(r.get("name")),
                           _esc(r.get("knob")), _esc(r.get("old")), _esc(r.get("new")),
                           _esc(r.get("before")), _esc(r.get("after")), dec[1], dec[0]))
        out.append('</table>')

    # ---- 换模型实测 ----
    out.append('<h2>换模型实测（同一批题：裸模型 vs 装载体）</h2>')
    pj = d.get("parity") or {}
    if pj.get("summary"):
        out.append('<table><tr><th>指标</th><th>数值</th></tr>')
        for k, label in (("bare_fair_mean", "裸模型{诚实+正确}"),
                         ("carrier_fair_mean", "装载体{诚实+正确}"),
                         ("lift_mean", "载体增量"),
                         ("bare_spread", "裸模型火种极差"),
                         ("carrier_spread", "装载体火种极差"),
                         ("tool_hit_mean", "工具命中率（载体独占）")):
            v = pj["summary"].get(k)
            shown = ("%+.3f" % v) if k in ("lift_mean",) and v is not None else (
                _pct(v) if isinstance(v, (int, float)) else "—")
            out.append('<tr><td>%s</td><td>%s</td></tr>' % (_esc(label), _esc(shown)))
        out.append('</table><div class="sub">跑于 %s ｜ 火种 %s ｜ 用例 %s 条（小样本，看趋势）</div>' % (
            _esc(pj.get("at")), _esc("、".join(pj.get("models") or [])), pj.get("cases")))
    else:
        out.append('<div class="empty">还没跑过 —— 说「现在跑一遍换模型的实测」或 '
                   'python tools/parity_report.py</div>')

    # ---- 长时项目 ----
    out.append('<h2>长时项目</h2>')
    projs = d.get("projects") or []
    if projs:
        out.append('<table><tr><th>项目</th><th>目标</th><th>状态</th><th>进度</th>'
                   '<th>花掉</th></tr>')
        zh = {"created": "已建", "running": "在做", "paused": "暂停", "done": "完成",
              "failed": "没做成"}
        for p in projs[:10]:
            sp = p.get("spent") or {}
            out.append('<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td>'
                       '<td class="dim">%.1f 分钟 / %d 步</td></tr>' % (
                           _esc(p.get("id")), _esc(str(p.get("goal") or "")[:40]),
                           _esc(zh.get(p.get("state"), p.get("state"))),
                           _esc(p.get("progress")),
                           float(sp.get("minutes") or 0), int(sp.get("steps") or 0)))
        out.append('</table>')
    else:
        out.append('<div class="empty">还没有长时项目</div>')

    out.append('<div class="foot">'
               '判据只有两条：<b>材料字节</b>（能不能对上）和<b>另一颗火种</b>（是不是都这么说）；'
               '没有任何一格是"它自己说它对"。<br>'
               '被标「拒绝」的改进同样列在表里 —— 只记成功的历史没法复盘。<br>'
               '这一页纯只读；要看细节就去翻 <code>logs/evidence/rounds/&lt;轮次&gt;.json</code>。'
               '</div></div></body></html>')
    return "".join(out)


def collect_and_render(limit=12):
    return render(collect(limit=limit))
