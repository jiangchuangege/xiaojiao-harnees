# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是“模型平等”和“变形金刚”的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层自测（感知 + 世界模型）—— **全部离线**。

跑法：
    python tools/test_world.py          # 全绿则退出码 0，有任何一条 ❌ 就是 1

为什么要"全部离线"（一个字节都不出网）：
  自测必须**可重复、可解释**。真实互联网会变（页面改版、站点挂了、被限流），
  那样失败的到底是我的代码还是对面，说不清。所以本地起一个 `http.server`（端口 0 自动分配），
  快照/变化/轮询全都打在自己身上 —— 世界感知的每一条口径（sha256、截断、diff、到期）
  都能被确定性地验证。

为什么不碰真实数据：
  所有状态都写在 `logs/world/_selftest/<本次运行>/...` 里，
  绝不读也不写 `logs/world/model.json` / `snapshots.jsonl`（那是小焦真正的世界）。
  每次运行的 URL 里带运行号，所以"首次见到 → first_seen"这类断言**反复跑也成立**。

顺带写死的原则：本脚本**不删除任何文件**（连自己产生的临时目录都不删）。
  "不能删文件"是身体边界的红线，自测脚本没有豁免权。
"""
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: silent-ok — 老环境没有 reconfigure，不该因此跑不了自测
    pass

from core.world import WorldModel, WorldPerception            # noqa: E402
from core.world import model as world_model                   # noqa: E402
from core.world import perception as world_perception         # noqa: E402

RID = time.strftime("%Y%m%d_%H%M%S") + "_%d" % os.getpid()
BASE_DIR = os.path.join(_ROOT, "logs", "world", "_selftest", RID)

PAGES = {}                    # 路径 → 正文（str）或 callable() → 正文（模拟"页面会变"）
HITS = {}                     # 路径 → 被请求次数


def CASE(name):
    """每个用例一个独立状态目录（互不干扰）。"""
    d = os.path.join(BASE_DIR, name)
    os.makedirs(d, exist_ok=True)
    return d


class _Handler(BaseHTTPRequestHandler):
    """只服务 PAGES 里登记过的路径，其余一律 404（"站点挂了"也要能测）。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        HITS[path] = HITS.get(path, 0) + 1
        body = PAGES.get(path)
        if body is None:
            data = b"not found"
            self.send_response(404)
        else:
            if callable(body):
                body = body()
            data = str(body).encode("utf-8")
            self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):      # 别把服务器日志混进自测输出
        pass


def local_fetch(url):
    """自测用 fetcher：走真实 HTTP 协议栈，但只打本地服务器（离线）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "XiaojiaoWorldSelftest/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            code = int(getattr(r, "status", 200) or 200)
            text = r.read().decode("utf-8", "replace")
        return (200 <= code < 400, text, code, "")
    except urllib.error.HTTPError as e:
        return (False, "", int(e.code), "HTTP %d" % e.code)
    except Exception as e:      # noqa: silent-ok — 自测里网络异常按"抓取失败"处理
        return (False, "", 0, str(e)[:120])


def _chk(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def _lines(path):
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


# =====================================================================
# 用例
# =====================================================================
def t01_domain_of():
    """1. domain_of：www / 端口 / 大写 / 查询串 / 非法输入"""
    m = WorldModel(os.path.join(CASE("t01"), "model.json"))
    want = [
        ("https://www.36kr.com/p/1?x=1", "36kr.com"),
        ("https://WWW.Example.COM:8080/a/b", "example.com"),
        ("http://sub.site.cn:80/", "sub.site.cn"),
        ("36kr.com", "36kr.com"),
        ("www.github.com/x", "github.com"),
        ("https://user:pw@news.36kr.com:443/p", "news.36kr.com"),
        ("http://127.0.0.1:8000/a", "127.0.0.1"),
        ("http://[::1]:8080/x", "::1"),
        ("Example.COM:8080", "example.com"),
        ("http://", ""), ("", ""), (None, ""), ("这不是网址", ""), ("hello", ""),
    ]
    bad = []
    for src, exp in want:
        got = m.domain_of(src)
        if got != exp:
            bad.append("%r → %r（期望 %r）" % (src, got, exp))
    _chk(not bad, "；".join(bad))
    return "%d 种写法全对" % len(want)


def t02_remember_site_persists():
    """2. remember_site 3 个站 → model.json 真有 3 条（读文件断言）"""
    path = os.path.join(CASE("t02"), "model.json")
    m = WorldModel(path)
    m.remember_site("https://36kr.com/p/1", type="tech_news")
    m.remember_site("https://github.com/openai/x", type="repo", trust=0.9)
    m.remember_site("https://www.zhihu.com/question/1", type="forum")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    _chk(isinstance(raw.get("sites"), dict), "model.json 缺 sites")
    _chk(len(raw["sites"]) == 3, "文件里应有 3 条站点，实际 %d" % len(raw["sites"]))
    _chk(set(raw["sites"]) == {"36kr.com", "github.com", "zhihu.com"},
         "落盘的域名不对：%s" % sorted(raw["sites"]))
    for field in ("type", "trust", "refresh", "first_seen", "last_seen", "hits", "title", "note"):
        _chk(field in raw["sites"]["36kr.com"], "站点记录缺字段 %s" % field)
    _chk(raw["sites"]["github.com"]["trust"] == 0.9, "显式 trust 没落盘：%r" % raw["sites"]["github.com"])
    _chk(raw["sites"]["36kr.com"]["refresh"] == "1h",
         "tech_news 的默认刷新周期该是 1h，实际 %r" % raw["sites"]["36kr.com"]["refresh"])
    _chk(isinstance(raw.get("relations"), list) and "updated" in raw, "缺 relations/updated")
    m2 = WorldModel(path)                      # 换一个实例读回来（证明不是只看内存）
    _chk(m2.trust_of("github.com") == 0.9 and len(m2.sites) == 3, "重新读盘后数据不对")
    return "文件里 %d 站点 / trust=%.1f / refresh=%s" % (
        len(raw["sites"]), raw["sites"]["github.com"]["trust"], raw["sites"]["36kr.com"]["refresh"])


def t03_trust_refresh_type():
    """3. trust_of / refresh_interval / type_of：周期解析 + 未知站给 default"""
    m = WorldModel(os.path.join(CASE("t03"), "model.json"))
    # ---- "1h"/"30m"/"2d"/"3600s" 解析 ----
    for s, sec in (("1h", 3600), ("30m", 1800), ("2d", 172800), ("3600s", 3600),
                   ("600", 600), ("1.5h", 5400), ("6h", 21600), ("7d", 604800)):
        _chk(world_model.parse_interval(s) == sec,
             "parse_interval(%r) 应为 %d，实际 %r" % (s, sec, world_model.parse_interval(s)))
    _chk(world_model.parse_interval("乱写", -1) == -1, "解析不了要给 default（且不抛错）")
    _chk(world_model.format_interval(1800) == "30m" and world_model.format_interval(604800) == "7d",
         "format_interval 不对：%r/%r" % (world_model.format_interval(1800),
                                          world_model.format_interval(604800)))
    # ---- 记录里的 refresh 优先于类型默认 ----
    m.remember_site("a.example.com", type="tech_news", refresh="30m")
    m.remember_site("b.example.com", type="repo", refresh="2d")
    m.remember_site("c.example.com", type="wiki", refresh="3600s")
    _chk(m.refresh_interval("a.example.com") == 1800, "记录里的 30m 该赢过 tech_news 的 1h")
    _chk(m.refresh_interval("b.example.com") == 172800, "记录里的 2d 没生效")
    _chk(m.refresh_interval("c.example.com") == 3600, "记录里的 3600s 没生效")
    # ---- 没写 refresh → 按类型表 ----
    m.remember_site("d.example.com", type="wiki")
    _chk(m.refresh_interval("d.example.com") == world_model.TYPE_REFRESH["wiki"], "wiki 该 7d")
    _chk(m.refresh_interval("news.example.com") == 3600, "域名能认出 tech_news，该 1h")
    # ---- 类型表也查不到 → 用调用方给的 default ----
    m.remember_site("e.example.com", type="weird_type")
    _chk(m.refresh_interval("e.example.com", default=123) == 123,
         "类型表查不到时该用 default")
    # ---- 未知站给 default ----
    _chk(m.trust_of("never-seen.example") == 0.5, "未知站可信度默认 0.5")
    _chk(m.trust_of("never-seen.example", default=0.9) == 0.9, "未知站该听调用方的 default")
    _chk(m.trust_of("shop.example.com", default=0.9) == 0.4, "能认出商城就该用表里的 0.4")
    _chk(m.type_of("never-seen.example") == "unknown", "未知站类型该是 unknown")
    _chk(m.type_of("never-seen.example", default="misc") == "misc", "未知站类型该听 default")
    _chk(m.type_of("github.com") == "repo", "已认识的站不该走 default")
    _chk(m.refresh_interval("never-seen.example") == world_model.TYPE_REFRESH["unknown"],
         "完全不认识的站按类型表走（unknown=6h，别频繁打扰）")
    _chk(m.trust_of("a.example.com") == world_model.TYPE_TRUST["tech_news"], "tech_news 表值 0.7")
    return "解析 8 种写法 + 未知站 default 口径全对"


def t04_infer_type():
    """4. infer_type：github→repo、36kr→tech_news、zhihu→forum、杂乱域名→unknown"""
    m = WorldModel(os.path.join(CASE("t04"), "model.json"))
    want = (
        ("https://github.com/openai/openai-python", "repo"),
        ("https://36kr.com/p/1", "tech_news"),
        ("https://www.zhihu.com/question/1", "forum"),
        ("http://misc-xyz-unknown.example/a", "unknown"),
    )
    bad = ["%s → %s（期望 %s）" % (u, m.infer_type(u), t) for u, t in want if m.infer_type(u) != t]
    _chk(not bad, "；".join(bad))
    # 优先级：具体的赢过泛词
    _chk(m.infer_type("https://api.openai.com/v1/models") == "api", "openai 该是 api 而不是 docs")
    _chk(m.infer_type("https://api.github.com/repos/a/b") == "repo", "api.github.com 本质是 repo")
    _chk(m.infer_type("https://docs.python.org/3/") == "docs", "docs 子域该是 docs")
    _chk(m.infer_type("https://news.ycombinator.com/item?id=1") == "forum", "HN 是 forum 不是 news")
    _chk(m.infer_type("https://www.jd.com/") == "shop", "jd.com 该是 shop")
    # 正文兜底：域名认不出来，靠标题/文档密度
    doc = "<html><title>小站使用文档</title><body>" + ("documentation api reference " * 6) + "</body></html>"
    _chk(m.infer_type("http://misc-xyz-unknown.example/doc", content=doc) == "docs",
         "正文有明显文档特征时该兜底成 docs")
    _chk(m.infer_type("", content="") == "unknown", "空 URL 该是 unknown（不能抛错）")
    return "域名规则 + 优先级 + 正文兜底 %d 项全对" % (len(want) + 7)


def t05_snapshot():
    """5. snapshot 本地站点 → snapshots.jsonl 有记录 / sha256·chars·title 齐全 / 世界模型被更新"""
    p = WorldPerception(fetcher=local_fetch, state_dir=CASE("t05"))
    url = BASE_URL + "/t05/normal"
    big = BASE_URL + "/t05/big"
    PAGES["/t05/normal"] = "<html><head><title>小焦世界自测页</title></head><body>正文内容 ABC</body></html>"
    PAGES["/t05/big"] = "<html><title>长页面</title>" + ("量子计算" * 700) + "</html>"
    rec = p.snapshot(url)
    body = PAGES["/t05/normal"]
    _chk(rec["ok"] is True and rec["status"] == 200, "抓本地页应成功：%r" % rec)
    _chk(rec["title"] == "小焦世界自测页", "标题抠错了：%r" % rec["title"])
    _chk(rec["chars"] == len(body), "chars 应是**全文**字数：%d vs %d" % (rec["chars"], len(body)))
    _chk(rec["sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest(), "sha256 不是全文哈希")
    _chk(rec["domain"] == "127.0.0.1", "domain 不对：%r" % rec["domain"])
    for field in ("ts", "url", "domain", "ok", "status", "sha256", "chars", "title", "head"):
        _chk(field in rec, "快照缺字段 %s" % field)
    # 读文件断言（不是只看返回值）
    mine = [r for r in _jsonl(p.snapshots_path) if r["url"] == url]
    _chk(len(mine) == 1, "snapshots.jsonl 里该有 1 条本 URL 的记录，实际 %d" % len(mine))
    _chk(mine[0]["sha256"] == rec["sha256"] and mine[0]["head"] == body, "落盘内容与返回值不一致")
    # 长页面：head 截断，chars/sha256 仍是全文（不然 logs 会被 2000 字以上撑爆）
    rec2 = p.snapshot(big)
    _chk(len(rec2["head"]) == 2000 and len(PAGES["/t05/big"]) > 2000,
         "head 该截断到 2000：%d" % len(rec2["head"]))
    _chk(rec2["chars"] == len(PAGES["/t05/big"]), "截断后 chars 仍必须是全文长度")
    _chk(rec2["sha256"] == hashlib.sha256(PAGES["/t05/big"].encode("utf-8")).hexdigest(),
         "截断后 sha256 仍必须对全文算")
    # 世界模型被更新（hits/last_seen）
    site = p.model.sites.get("127.0.0.1") or {}
    _chk(int(site.get("hits") or 0) >= 2, "hits 该 >=2，实际 %r" % site.get("hits"))
    _chk(float(site.get("last_seen") or 0) > 0, "last_seen 没写")
    _chk(site.get("title") == "长页面", "站点标题该更新成最后一次的：%r" % site.get("title"))
    return "1 普通页 + 1 长页（head 截断 2000/全文 %d 字），hits=%s" % (len(PAGES["/t05/big"]), site.get("hits"))


def t06_diff():
    """6. diff：首次→first_seen；改动→changed（detail 有新增行）；不变→unchanged 且不写 changes.jsonl"""
    p = WorldPerception(fetcher=local_fetch, state_dir=CASE("t06"))
    url = BASE_URL + "/t06/d"
    v1 = "<html><title>页面D</title><body>原来的内容\n第二行没变\n</body></html>"
    v2 = "<html><title>页面D</title><body>原来的内容\n第二行没变\n新增行XYZ\n</body></html>"
    chs = p.diff(url, v1)                     # 从没见过 → first_seen
    _chk(len(chs) == 1 and chs[0]["kind"] == "first_seen", "首次该是 first_seen：%r" % chs)
    _chk(chs[0]["url"] == url and chs[0]["domain"] == "127.0.0.1", "Change 字段不全：%r" % chs[0])
    _chk(_lines(p.changes_path) == 1, "first_seen 该写进 changes.jsonl")
    # 建立基准：真的抓一次 v1（它成为"上一次快照"）
    PAGES["/t06/d"] = v1
    p.snapshot(url)
    n_base = _lines(p.changes_path)
    # 内容改了 → changed，detail 里要有新增行
    chs = p.diff(url, v2)
    _chk(len(chs) == 1 and chs[0]["kind"] == "changed", "改动该是 changed：%r" % chs)
    _chk("新增行XYZ" in chs[0]["detail"], "detail 里该有新增行：%r" % chs[0]["detail"])
    _chk(chs[0]["new_head"].startswith("<html>") and chs[0]["old_head"] != chs[0]["new_head"],
         "old_head/new_head 不对：%r" % chs[0])
    n_after_changed = _lines(p.changes_path)
    _chk(n_after_changed == n_base + 1, "changed 该写进 changes.jsonl")
    # 内容一模一样 → unchanged，且**不新增** changes.jsonl
    # （口径：diff 是"跟**上次快照**比"，它自己**不写快照**。所以要先 snapshot 一次把 v2 变成基准，
    #   再 diff(v2) 才是那个"没变"的场景 —— 这正是 observe/watch 里"抓→比→记"的顺序。）
    PAGES["/t06/d"] = v2
    p.snapshot(url)
    chs = p.diff(url, v2)
    _chk(len(chs) == 1 and chs[0]["kind"] == "unchanged", "同内容该是 unchanged：%r" % chs)
    _chk(_lines(p.changes_path) == n_after_changed, "unchanged 绝不能写 changes.jsonl")
    # appeared / disappeared（以"空正文"为界：快照里存的是空 → 之后有内容就是 appeared）
    PAGES["/t06/d"] = ""
    p.snapshot(url)                            # 上次快照 = 空
    chs = p.diff(url, "又回来了")
    _chk(chs[0]["kind"] == "appeared", "从空恢复该是 appeared：%r" % chs)
    PAGES["/t06/d"] = v1
    p.snapshot(url)                            # 上次快照 = 有内容
    chs = p.diff(url, "")
    _chk(chs[0]["kind"] == "disappeared", "空正文该是 disappeared：%r" % chs)
    # **顺序契约**：observe（抓→比→记）必须能看出"变了"（第一版写反了顺序，这里永远是 unchanged）
    PAGES["/t06/d"] = v1
    p.snapshot(url)
    PAGES["/t06/d"] = v2
    s = p.observe([url])
    _chk(s["items"][0]["kinds"] == ["changed"],
         "observe 该按「先比后记」的顺序看出变化，实际 %r" % s["items"][0]["kinds"])
    return "first_seen→changed（detail 含新增行）→unchanged（不写日志）→disappeared→appeared + 顺序契约"


def t07_watch():
    """7. watch 持续观察：跑完 3 轮 / 有快照 / stop_event 能提前停"""
    p = WorldPerception(fetcher=local_fetch, state_dir=CASE("t07"))
    counter = {"n": 0}

    def _page():
        counter["n"] += 1
        return "<html><title>轮询页</title><body>第 %d 次抓取，内容每次都不一样</body></html>" % counter["n"]

    PAGES["/t07/w"] = _page
    url = BASE_URL + "/t07/w"
    st = p.watch([url], interval=1, max_rounds=3)
    _chk(st["rounds"] == 3, "该跑完 3 轮，实际 %r" % st["rounds"])
    _chk(st["stopped"] is False, "max_rounds 到点结束，不该标成 stopped")
    _chk(st["fetched"] >= 2, "间隔 1 秒 > 调用方周期，3 轮里至少抓 2 次，实际 %r" % st["fetched"])
    recs = [r for r in _jsonl(p.snapshots_path) if r["url"] == url]
    _chk(len(recs) >= 2, "持续观察该留下多条快照，实际 %d" % len(recs))
    _chk(st["changed"] >= 1, "页面每轮都在变，该报出变化，实际 %r" % st["changed"])
    _chk(counter["n"] == st["fetched"], "抓取次数应与 HTTP 请求数一致：%d vs %d" % (counter["n"], st["fetched"]))
    # 到期的才抓：刚看过 → 不到期；等过一个调用方周期 → 到期
    _chk(p._due(url, interval=1) is False, "刚看过的站不该立刻再抓")
    time.sleep(1.05)
    _chk(p._due(url, interval=1) is True, "过了一个观察周期就该到期")
    # stop_event 提前停（后台线程只能靠它停，不能靠杀进程）
    ev = threading.Event()
    threading.Timer(0.4, ev.set).start()
    st2 = p.watch([url], interval=1, stop_event=ev)
    _chk(st2["stopped"] is True, "stop_event 置位后该如实报告 stopped")
    _chk(st2["rounds"] < 10 and st2["elapsed_s"] < 8.0,
         "置位后该马上退出：rounds=%r elapsed=%r" % (st2["rounds"], st2["elapsed_s"]))
    return "3 轮抓 %d 次 / 变化 %d 次 / stop_event 在 %.2fs 停下" % (
        st["fetched"], st["changed"], st2["elapsed_s"])


def t08_due():
    """8. due()：last_seen 很久以前 → 到期；刚刚 → 不到期"""
    m = WorldModel(os.path.join(CASE("t08"), "model.json"))
    m.remember_site("old.example.com", type="tech_news")      # 1h
    m.remember_site("fresh.example.com", type="tech_news")    # 1h
    m.remember_site("wikiish.example.com", type="wiki")       # 7d
    now = time.time()
    m.sites["old.example.com"]["last_seen"] = now - 7200          # 2 小时前 → 该刷新
    m.sites["fresh.example.com"]["last_seen"] = now - 5           # 刚看过 → 不刷
    m.sites["wikiish.example.com"]["last_seen"] = now - 3600      # 1 小时前，但周期 7 天
    due = m.due(now=now)
    _chk("old.example.com" in due, "2 小时没看的新闻站该到期：%r" % due)
    _chk("fresh.example.com" not in due, "刚看过的站不该到期：%r" % due)
    _chk("wikiish.example.com" not in due, "百科 7 天周期，1 小时不该到期：%r" % due)
    _chk(due[0] == "old.example.com", "最久没看的该排最前：%r" % due)
    # should_refresh：从没看过 → True；刚看过 → False；很久以前 → True
    _chk(m.should_refresh("never-seen.example", now=now) is True, "没看过就该看")
    _chk(m.should_refresh("fresh.example.com", now=now) is False, "刚看过不该看")
    _chk(m.should_refresh("fresh.example.com", last_check=now - 99999, now=now) is True,
         "显式给 last_check 时该按它算")
    return "到期表 %r（最久没看的排最前），未到期 %d 个" % (due, 3 - len(due))


def t09_hot_topics():
    """9. hot_topics：塞 3 条含重复词的快照 → 提炼出该词"""
    p = WorldPerception(fetcher=local_fetch, state_dir=CASE("t09"))
    page = ("<html><title>量子计算快讯</title><body>"
            "量子计算正在改变世界。量子计算与人工智能结合。量子计算前景广阔。</body></html>")
    for i in range(3):
        path = "/t09/p%d" % i
        PAGES[path] = page
        rec = p.snapshot(BASE_URL + path)
        _chk(rec["ok"], "第 %d 条快照抓失败了" % i)
    topics = p.hot_topics(limit=10)
    words = dict(topics)
    _chk("量子计算" in words, "没提炼出该词：%r" % topics)
    _chk(words["量子计算"] >= 3, "该词次数不对：%r" % words.get("量子计算"))
    _chk(topics[0][0] == "量子计算", "最高频的该是它：%r" % topics[:3])
    _chk(all(len(w) >= 2 for w, _c in topics), "不该出单词：%r" % topics)
    return "前 3 名 %r" % (topics[:3],)


def t10_corrupt_model():
    """10. 损坏的 model.json → 不崩、能自愈、原文件被另存为 .bad"""
    path = os.path.join(CASE("t10"), "model.json")
    junk = '{"sites": {"a.com": {"type": "news", "tru'
    with open(path, "w", encoding="utf-8") as f:
        f.write(junk)
    m = WorldModel(path)                     # 关键：这一行不许抛错
    _chk(m.stats()["sites"] == 0, "坏文件该被当成空模型，实际 %r" % m.stats())
    bad = path + ".bad"
    _chk(os.path.exists(bad), "坏文件该被另存为 .bad（不能丢掉用户的旧数据）")
    with open(bad, "r", encoding="utf-8") as f:
        _chk(f.read() == junk, ".bad 里该是**原文**，一个字都不能改")
    _chk(m.bad_path == bad, "bad_path 该记下来（便于面板/自检显示）")
    # 自愈：现在能正常写入，且文件是合法 JSON
    m.remember_site("x.com", type="social")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    _chk(list(raw["sites"]) == ["x.com"], "自愈后该能正常记账：%r" % list(raw["sites"]))
    m2 = WorldModel(path)
    _chk(m2.stats()["sites"] == 1 and m2.bad_path == "", "第二次读不该再触发备份")
    # 空文件（不是"损坏"，是"还没写过"）：同样不崩
    empty = os.path.join(CASE("t10"), "empty.json")
    with open(empty, "w", encoding="utf-8") as f:
        f.write("")
    _chk(WorldModel(empty).stats()["sites"] == 0, "空文件该被当成空模型")
    return "半截 JSON → 空模型 + .bad 备份 + 自愈（%d 站点）" % m2.stats()["sites"]


def t11_default_fetch():
    """额外. 默认抓取器：先借 app 的 get、借不到用 requests、只认 http(s)、绝不抛错"""
    import types
    old = sys.modules.get("xiaojiao_app")

    def _reset():
        world_perception._APP_TRIED = False
        world_perception._APP = None

    try:
        # ① app 可用 → 走 run_tool("get")，并解析它的 JSON 返回
        fake = types.ModuleType("xiaojiao_app")
        fake.run_tool = lambda name, args, force=False: json.dumps(
            {"status": 200, "url": args.get("url"), "content": "APP 抓到的正文", "error": ""},
            ensure_ascii=False)
        sys.modules["xiaojiao_app"] = fake
        _reset()
        ok, text, status, err = world_perception.default_fetch("http://example.invalid/x")
        _chk(ok and text == "APP 抓到的正文" and status == 200,
             "该走 app 的 get：%r" % ((ok, text, status, err),))
        # ② app 坏了 → 自动兜到 requests（用本地 server 证明这条路真的通）
        def _boom(name, args, force=False):
            raise RuntimeError("app 工具炸了")
        fake.run_tool = _boom
        _reset()
        PAGES["/t11/fallback"] = "<html><title>兜底页</title><body>兜底正文</body></html>"
        ok, text, status, err = world_perception.default_fetch(BASE_URL + "/t11/fallback")
        _chk(ok and status == 200 and "兜底正文" in text,
             "app 挂了该用 requests 兜住：%r" % ((ok, status, err),))
        # ③ 协议白名单：file:// 一律不碰（身体边界里最硬的一条）
        ok, text, status, err = world_perception.default_fetch("file:///C:/Windows/win.ini")
        _chk((not ok) and "http" in err, "file:// 必须拒绝：%r" % ((ok, text, err),))
        # ④ 连不上 → 如实失败，不抛错
        ok, text, status, err = world_perception.default_fetch("http://127.0.0.1:1/nothing")
        _chk((not ok) and err, "连不上该返回失败原因：%r" % ((ok, err),))
    finally:
        if old is None:
            sys.modules.pop("xiaojiao_app", None)
        else:
            sys.modules["xiaojiao_app"] = old
        _reset()
    # ⑤ 工具返回值归一：JSON / 纯文本 / 已知失败开场白
    _chk(world_perception.parse_tool_result("纯文本正文") == (True, "纯文本正文", 200, ""), "纯文本该被认成正文")
    _chk(world_perception.parse_tool_result(json.dumps({"status": 403, "content": "", "error": "被封了"}))
         == (False, "", 403, "被封了"), "JSON 错误该被认出来")
    _chk(world_perception.parse_tool_result("❌ 抓取失败")[0] is False, "失败开场白不该当正文")
    _chk(world_perception.parse_tool_result(None)[0] is False, "None 不该抛错")
    return "app 路径 / requests 兜底 / file:// 拒绝 / 连不上不抛错 / 归一 4 种形状"


def t12_world_extras():
    """额外. 关系图 / observe 摘要 / availability / stats / reload / describe"""
    p = WorldPerception(fetcher=local_fetch, state_dir=CASE("t12"))
    url = BASE_URL + "/t12/a"
    PAGES["/t12/a"] = "<html><title>观察页</title><body>观察正文</body></html>"
    s1 = p.observe([url, MISSING_URL])
    _chk(s1["checked"] == 2 and s1["ok"] == 1 and s1["failed"] == 1,
         "observe 摘要不对：%r" % {k: s1[k] for k in ("checked", "ok", "failed")})
    _chk(s1["first_seen"] == 1 and s1["errors"], "该报出 1 个首次 + 1 个错误：%r" % s1["errors"])
    s2 = p.observe([url])
    _chk(s2["unchanged"] == 1 and s2["changed"] == 0, "内容没变该报 unchanged：%r" % s2)
    av = p.availability()
    _chk(av["ok"] >= 1 and av["down"] >= 1, "环境状态该一好一坏：%r" % {k: av[k] for k in ("ok", "down")})
    _chk(av["sites"]["127.0.0.1"]["ok"] is True, "本地站该是通的")
    # 关系图
    m = p.model
    _chk(m.add_relation("https://36kr.com/p/1", "tech", kind="category") is True, "关系该能加")
    _chk(m.add_relation("36kr.com", "tech", kind="category") is False, "重复关系该返回 False")
    _chk(m.add_relation("a.com", "a.com") is False, "自反关系该被拒（没有信息量）")
    rels = m.relations_of("36kr.com", kind="category")
    _chk(len(rels) == 1 and rels[0]["to"] == "tech" and rels[0]["from"] == "36kr.com",
         "relations_of 不对：%r" % rels)
    # reload / describe / stats
    m.remember_site("reload.example.com", type="docs")
    m3 = WorldModel(m.path)
    _chk("reload.example.com" in m3.sites, "reload 该读回磁盘上的站")
    _chk("docs" in m3.describe("reload.example.com"), "describe 该说清类型：%r" % m3.describe("reload.example.com"))
    st = p.stats()
    _chk(st["snapshots"] >= 3 and st["world"]["sites"] >= 1, "stats 不对：%r" % st)
    _chk(isinstance(m.snapshot(), dict) and "sites" in m.snapshot(), "snapshot() 该给只读快照")
    return "observe 摘要 / availability 好坏各 1 / 关系图去重 / reload / stats"


BASE_URL = ""
MISSING_URL = ""
TESTS = [t01_domain_of, t02_remember_site_persists, t03_trust_refresh_type, t04_infer_type,
         t05_snapshot, t06_diff, t07_watch, t08_due, t09_hot_topics, t10_corrupt_model,
         t11_default_fetch, t12_world_extras]


def main():
    global BASE_URL, MISSING_URL
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    BASE_URL = "http://127.0.0.1:%d" % port
    MISSING_URL = "http://localhost:%d/t12/missing" % port   # 另一个主机名 → 另一个"站点"（404）
    print("=" * 72)
    print("小焦 · 世界层自测（感知 + 世界模型）  —— 全部离线，本地站点 127.0.0.1:%d" % port)
    print("状态目录：%s" % BASE_DIR)
    print("（stderr 里那条「世界模型损坏，按空模型继续」是第 10 条用例**故意**制造的，属于预期输出）")
    print("=" * 72)
    t0 = time.time()
    passed = 0
    for i, fn in enumerate(TESTS, 1):
        title = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
        try:
            detail = fn() or ""
            passed += 1
            print("✅ %s%s" % (title, ("   —— " + detail) if detail else ""))
        except Exception as e:
            msg = "%s: %s" % (type(e).__name__, e)
            print("❌ %s\n     ← %s" % (title, msg))
            if os.environ.get("WORLD_TEST_TRACE"):
                traceback.print_exc()
        sys.stdout.flush()
    print("-" * 72)
    print("通过 %d / 共 %d    用时 %.2fs" % (passed, len(TESTS), time.time() - t0))
    httpd.shutdown()
    return 0 if passed == len(TESTS) else 1


if __name__ == "__main__":
    sys.exit(main())
