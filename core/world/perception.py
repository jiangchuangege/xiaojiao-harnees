# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是“模型平等”和“变形金刚”的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层 · 世界感知（互联网不是工具箱，是它的**世界**）

这一层和"上网查资料"最大的区别，是**谁来决定看什么**：
  · 工具箱：用户问了才看，看完就忘（`run_tool("get")` 就是这个模式）；
  · 世界：**它自己一直在看**（watch 持续观察），看到的变化记下来（diff → changes.jsonl），
    并且记住"哪个站该多久看一次"（WorldModel）。
所以感知层由三件事组成：
  ① 看（snapshot）：抓一页 → 存快照（sha256 对全文、正文只留前 2000 字）→ 更新世界模型；
  ② 比（diff）：跟上次比，是"首次/变了/冒出来/消失了/没变"，变化的行单独留档；
  ③ 一直看（watch / observe）：按世界模型的周期决定谁到期了，只抓到期的。

落盘（全部在 logs/world/ 下，logs/ 已被 .gitignore 忽略）：
  model.json      脑子里的地图（见 core/world/model.py）
  snapshots.jsonl 每一次看的现场（追加式，只增不改）
  changes.jsonl   只记**真的变了**的那些（没变不写，否则日志会被"什么都没发生"淹没）

身体边界（写在最前面，因为这是原则问题，不是实现细节）：
  能碰：公开页面、公开 API。不能碰：需要登录的、付费的、版权保护的。
  发布内容、花钱 → 必须先问用户。**红线：不能删任何文件** —— 世界感知只追加、不删除。
  本模块只做"超时 + 异常兜底 + 只认 http/https"，更细的 SSRF/robots 由上层（scrapling_bridge 的
  SecurityGuard / app 的 get 工具）负责：感知层不重复造一套安全策略，但**自己绝不越权**。

关于"私网段"的说明：spec 里那句 "拒绝 localhost/内网 IP 之外的私网段以外的 SSRF 由上层管"
本身是绕的，这里按**能落地**的口径执行：
  · 本模块只管超时与异常兜底（8 秒 + 绝不抛错）；
  · 协议白名单只放 http/https（file://、ftp:// 一律不碰）—— 这是"身体边界"里最硬的一条；
  · 目标地址是否内网/是否该拒，交给上层的 SecurityGuard 判（它有完整的 SSRF 防护与 robots 检查）。
  为什么不在这里再判一遍内网：两套判断标准必然打架（比如本地自测用的 127.0.0.1 服务），
  到时候"到底谁说了算"会成为 bug 温床。**一个策略只有一个负责人。**
"""
import difflib
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

try:
    from .model import WORLD_DIR, WorldModel, domain_of_url, format_interval
except ImportError:            # 直接 `python core/world/perception.py` 时没有包上下文
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from model import WORLD_DIR, WorldModel, domain_of_url, format_interval

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_CHARS = 2000       # 快照只留正文前 2000 字
MAX_SNAPSHOT_LINES = 20000      # 读 jsonl 只读末尾这么多行（追加式文件，越老越没用）
_LAST_LOOKBACK = 500            # "这个 URL 上次什么时候看的"最多回看多少行
MAX_HOT_SNAPSHOTS = 200         # 提炼热点时最多看最近多少条快照
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 XiaojiaoWorld/1.0")
_FETCH_TIMEOUT = 8              # 秒。为什么是 8：比人等待的耐心短，比慢站的响应长
_APP_TRIED = False              # 是否已经试过拿 xiaojiao_app（只试一次，别每次抓取都 import）
_APP = None
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_MD_TITLE_RE = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", re.M)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_EN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#._\-]{2,}")
_TAG_RE = re.compile(r"<[^>]{0,400}>")
# 工具的"失败开场白"：这些开头说明它不是正文，别当成内容存进快照。
_FAIL_PREFIX = ("❌", "〔待确认〕", "抓取失败", "截屏失败", "截图失败", "（这句话里没有")

# 中文功能词/页面模板词：它们高频但**不代表"今天互联网在讨论什么"**。
# 不过滤的话 hot_topics 永远是「我们/可以/首页/登录」——看着像热点，实际是网页噪音。
_HOT_STOP = {
    "我们", "你们", "他们", "她们", "可以", "什么", "这个", "那个", "这些", "那些", "一个", "没有",
    "就是", "因为", "所以", "但是", "如果", "已经", "以及", "对于", "关于", "进行", "使用", "通过",
    "表示", "目前", "今日", "最新", "最近", "首页", "登录", "注册", "更多", "详情", "相关", "推荐",
    "广告", "网站", "页面", "内容", "查看", "了解", "点击", "我们", "我的", "他的", "不是", "还是",
    "这样", "那样", "时候", "问题", "方式", "为了", "而且", "或者", "并且", "然后", "另外", "因此",
    "以下", "以上", "全部", "所有", "一些", "很多", "非常", "可能", "应该", "需要", "提供", "支持",
}
_HOT_STOP_EN = {"http", "https", "www", "com", "the", "and", "for", "with", "this", "that", "you",
                "are", "was", "not", "from", "have", "has", "his", "her", "its", "our", "but",
                "html", "body", "title", "head", "div", "span", "class", "href", "src", "nbsp"}


# ------------------------------------------------------------------ 工具返回值归一
def parse_tool_result(out):
    """把工具（get/fetch）的返回值统一成 `(ok, text, status, error)`。

    为什么需要它：小焦的抓取工具有两条路 —— app 的 `get`（走 scrapling，
    返回 `{"status":..,"content":..,"error":..}` 的 JSON 字符串）和本模块的 requests 兜底。
    上层只想要"成没成、正文是什么、什么状态码"，这里把两种形状抹平。
    为什么还要认纯文本：老插件/别的实现可能直接回正文，硬按 JSON 解析会把正常内容判成失败。
    去掉它：任何抓取结果都得在每个调用点各写一遍解析，早晚会有地方把错误当正文存下来。
    """
    if out is None:
        return (False, "", 0, "工具返回空")
    if isinstance(out, dict):
        d = out
    else:
        s = str(out).strip()
        if not s:
            return (False, "", 0, "工具返回空")
        for p in _FAIL_PREFIX:
            if s.startswith(p):
                return (False, s[:200], 0, s[:200])
        try:
            d = json.loads(s)
        except Exception:
            return (True, s, 200, "")          # 纯文本（老插件）→ 当正文
    if isinstance(d, dict):
        err = str(d.get("error") or "").strip()
        try:
            status = int(d.get("status") or 0)
        except Exception:
            status = 0
        content = d.get("content")
        content = "" if content is None else str(content)
        if err:
            return (False, content, status, err[:200])
        if content.strip():
            return (True, content, status or 200, "")
        return (False, "", status, "工具没拿到正文")
    return (True, str(d), 200, "")


def _app_module():
    """惰性拿 xiaojiao_app（拿不到就 None）。**只试一次**，失败也记住。

    为什么必须惰性：感知层要能**独立 import**（不拖 Flask、不在 import 期启动任何东西）。
    为什么只试一次：`_default_fetch` 是热路径（持续观察里每秒都可能调），
    每次都去 `import` 一个巨型模块，代价会堆在每一次抓取上。
    """
    global _APP_TRIED, _APP
    if _APP_TRIED:
        return _APP
    _APP_TRIED = True
    try:
        import sys
        app = sys.modules.get("xiaojiao_app")
        if app is None or not hasattr(app, "run_tool"):
            try:
                # 惰性导入：只有真的要抓网页时才把小焦主程序拉进来（感知层不依赖它也能活）
                import xiaojiao_app as app
            except Exception:
                app = None
        _APP = app if (app is not None and hasattr(app, "run_tool")) else None
    except Exception:      # noqa: silent-ok — 拿不到就退回 requests，绝不因此报错
        _APP = None
    return _APP


def default_fetch(url):
    """默认抓取器：先借小焦自己的 `get` 工具，借不到就用 requests 自己抓。**任何情况都不抛错**。

    返回 `(ok, text, status, error)`。

    为什么是"先借再兜"：app 的 `get`（scrapling）自带反爬、robots、SSRF 防护、
    正文提取（HTML→Markdown），比裸 requests 强得多 —— 能借就借，别重复造。
    为什么还要 requests 兜底：感知层会被**独立**使用（后台观察进程、自测、脚本），
    那时 app 根本没被 import。没有兜底，"持续观察"就只能在整站启动后才活着。
    为什么只认 http/https：这是身体边界里最硬的一条 —— file:// 能读本机任意文件，
    而它看起来就像一次普通抓取。去掉这层白名单，世界感知立刻变成任意文件读取漏洞。
    """
    u = str(url or "").strip()
    if not (u.lower().startswith("http://") or u.lower().startswith("https://")):
        return (False, "", 0, "只支持 http/https")
    app_err = ""
    app = _app_module()
    if app is not None:
        try:
            ok, text, status, err = parse_tool_result(app.run_tool("get", {"url": u}))
            if ok:
                return (True, text, status, "")
            app_err = err
        except Exception as e:
            app_err = "app.get 异常：%s" % str(e)[:120]
    try:
        import requests
    except Exception as e:      # noqa: silent-ok — 连 requests 都没有：如实回报，不抛错
        return (False, "", 0, "requests 不可用（%s）%s" % (str(e)[:80], app_err))
    try:
        r = requests.get(u, timeout=_FETCH_TIMEOUT,
                         headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,*;q=0.5"})
        code = int(getattr(r, "status_code", 0) or 0)
        body = r.text or ""
        ok = 200 <= code < 400
        note = "" if ok else "HTTP %d" % code
        if app_err:
            note = (note + "；" if note else "") + "app 路径：" + app_err
        return (ok, body, code, note)
    except Exception as e:      # noqa: silent-ok — 网络异常是**常态**（站点会挂、会超时），必须吞下
        note = str(e)[:150]
        if app_err:
            note += "；app 路径：" + app_err
        return (False, "", 0, note)


def _sha256(text):
    return hashlib.sha256(str(text or "").encode("utf-8", "replace")).hexdigest()


def extract_title(text):
    """从 HTML / Markdown 抠标题（HTML 的 <title> 优先，其次 Markdown 一级标题）。"""
    t = str(text or "")
    m = _TITLE_RE.search(t)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    m = _MD_TITLE_RE.search(t)
    return (m.group(1).strip()[:200] if m else "")


def _norm_fetch_result(res):
    """把自定义 fetcher 的返回值也归一（元组/字典/字符串都认）。

    为什么放宽：`fetcher` 是注入点（自测、别的模块、mcp 桥都可能传自己的实现）。
    这里多认几种形状，比在每个调用点写 `if isinstance(...)` 便宜得多。
    """
    if isinstance(res, tuple) and len(res) >= 3:
        ok = bool(res[0])
        text = "" if res[1] is None else str(res[1])
        try:
            status = int(res[2] or 0)
        except Exception:
            status = 0
        err = str(res[3]) if len(res) > 3 and res[3] else ""
        return ok, text, status, err
    if isinstance(res, dict):
        try:
            status = int(res.get("status") or 0)
        except Exception:
            status = 0
        text = res.get("text")
        if text is None:
            text = res.get("content")
        return (bool(res.get("ok")), "" if text is None else str(text), status,
                str(res.get("error") or ""))
    if isinstance(res, str):
        return (True, res, 200, "")
    return (False, "", 0, "抓取器返回值无法识别：%s" % type(res).__name__)


def _tail_lines(path, max_lines):
    """只读 JSONL 末尾 max_lines 行。

    为什么不 readlines()：snapshots.jsonl 是"一直在长"的文件（持续观察一天就是几万行，
    每行还带 2000 字正文）。整文件读进内存再切尾巴，内存和启动时间都会被它拖住。
    从尾部按 64KB 块反读，代价固定在"最近 N 条"，跟文件多大无关。
    读不到（文件不存在/被占用）返回 []，让调用方按"没有历史"处理。
    """
    if max_lines <= 0:
        return []
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size <= 0:
        return []
    chunk = 64 * 1024
    buf = b""
    try:
        with open(path, "rb") as f:
            pos = size
            while pos > 0 and buf.count(b"\n") <= max_lines:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
    except OSError:
        return []
    return buf.decode("utf-8", "replace").splitlines()[-max_lines:]


def _load_jsonl(path, max_lines):
    """读 JSONL 尾部 → list[dict]。**坏行直接跳过**（一行写坏不该让整段历史读不出来）。"""
    out = []
    for line in _tail_lines(path, max_lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# ------------------------------------------------------------------ 感知
class WorldPerception:
    """看世界的那只眼睛：抓 → 存 → 比 → 记。

    `fetcher(url) -> (ok, text, status, error)` 是可注入的：
    默认 `default_fetch`（app 的 get → requests 兜底），自测/别的模块可以换成自己的实现。
    注入点是**故意的** —— 感知层不该和任何抓取实现绑死（否则"模型平等"之外还得再加一条"抓取器平等"）。
    """

    def __init__(self, fetcher=None, model=None, state_dir=None):
        self.state_dir = state_dir or WORLD_DIR
        try:
            os.makedirs(self.state_dir, exist_ok=True)
        except Exception as e:      # noqa: silent-ok — 建不了目录也要能跑（后面写文件会如实失败）
            logger.warning("世界状态目录创建失败：%s", e)
        self.model = model if model is not None else WorldModel(os.path.join(self.state_dir, "model.json"))
        self.snapshots_path = os.path.join(self.state_dir, "snapshots.jsonl")
        self.changes_path = os.path.join(self.state_dir, "changes.jsonl")
        self.fetcher = fetcher or default_fetch
        self._wlock = threading.Lock()      # 追加写日志用（后台观察线程 + 主线程会同时写）
        self.last_error = ""

    # ---- 底层：追加写 ----
    def _append(self, path, rec):
        """追加一行 JSON。**只追加，永不删改** —— 世界的历史一旦写了就不许被抹掉。"""
        try:
            line = json.dumps(rec, ensure_ascii=False)
        except Exception as e:      # noqa: silent-ok — 序列化失败只丢这一条日志
            logger.warning("世界日志序列化失败：%s", e)
            return False
        try:
            with self._wlock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            return True
        except Exception as e:      # noqa: silent-ok — 写不进日志不能中断观察
            logger.warning("世界日志写入失败(%s)：%s", path, e)
            return False

    # ---- ① 看 ----
    def _fetch_and_record(self, url, with_diff=False):
        """抓一页 →（可选）跟上一次比 → 落快照 → 更新世界模型。返回 `(record, full_text, changes)`。

        **顺序是这一步的全部意义**（第一版写反了，自测第 6/7 条立刻抓到）：
        必须"先比、后写快照"。因为 `diff` 的基准是 **最后一次快照**，
        如果先把本次内容写进 jsonl，再调 diff，就是拿本次内容跟自己比 ——
        永远 unchanged，页面天天改也报"什么都没发生"。
        自测里这个 bug 的表现：observe() 永远 first_seen/unchanged，watch() 的 changed 恒为 0。

        为什么要把**全文**交回调用方（而不是让它去读 jsonl 的 head）：
        head 只有 2000 字（为了别把 logs 撑爆），diff 需要的是真内容。
        传回来最省事，也避免"为了比对再抓一次"（那是对站点的二次打扰）。
        """
        u = str(url or "").strip()
        dom = domain_of_url(u) or u.lower()
        t0 = time.time()
        try:
            ok, text, status, error = _norm_fetch_result(self.fetcher(u))
        except Exception as e:      # noqa: silent-ok — 抓取器异常=这一次失败，不是世界末日
            ok, text, status, error = False, "", 0, "抓取器异常：%s" % str(e)[:150]
        text = text or ""
        if not ok and not error:
            error = "抓取失败"
        sha = _sha256(text)
        title = extract_title(text) if ok else ""
        rec = {
            "ts": round(time.time(), 3),
            "url": u,
            "domain": dom,
            "ok": bool(ok),
            "status": int(status or 0),
            "sha256": sha,                  # 对**全文**算：head 会被截断，哈希不能跟着失真
            "chars": len(text),             # 全文有多少字（head 只有前 2000）
            "title": title,
            "head": text[:MAX_SNAPSHOT_CHARS],
        }
        if error:
            # 只在失败时多带一个字段。成功记录严格保持 spec 的 7 个字段，
            # 失败的原因必须留痕（否则面板上只看到"红了"，不知道为什么红）。
            rec["error"] = str(error)[:200]
        self.last_error = "" if ok else str(error)[:200]
        try:
            if ok:
                self.model.remember_site(u, title=title)
            self.model.mark_seen(u, status=rec["status"], chars=rec["chars"])
        except Exception as e:      # noqa: silent-ok — 世界模型写失败也要把快照留下（快照是事实）
            logger.warning("更新世界模型失败(%s)：%s", u, e)
        changes = []
        if with_diff and ok:
            try:
                changes = self.diff(u, text)
            except Exception as e:      # noqa: silent-ok — 比不了也要把"看过"这件事记下来
                logger.warning("diff 失败(%s)：%s", u, e)
        self._append(self.snapshots_path, rec)
        rec["ms"] = int((time.time() - t0) * 1000)
        return rec, text, changes

    def ingest(self, url, content, status=200, title=""):
        """**内容已经在手**时用它：比 → 记快照 → 更新世界模型。返回 `(record, changes)`。

        为什么需要这个入口（而不是让调用方自己拼记录）：
        对话里"用户点名的抓取"这条路上，正文是**上层工具已经抓回来的** ——
        再调 `snapshot()` 就是**对同一个站点的二次打扰**（多一次真实网络请求，
        还是个可能被风控的请求）。而 `diff(url, new_content)` 只比不记，
        调用方自己拼快照记录就必须复制一遍 `_fetch_and_record` 里的字段口径
        （sha256 对全文、head 截断、失败才带 error）—— 复制出来的第二份口径迟早会和第一份不一致。
        所以把"手里已有正文"这件事做成**一等入口**：口径只有一处，抓取只发生一次。
        """
        u = str(url or "").strip()
        dom = domain_of_url(u) or u.lower()
        text = content or ""
        try:
            changes = self.diff(u, text) if text else []
        except Exception as e:      # noqa: silent-ok — 比不了也要把"看过"这件事记下来
            logger.warning("ingest 比对失败(%s)：%s", u, e)
            changes = []
        rec = {
            "ts": round(time.time(), 3),
            "url": u,
            "domain": dom,
            "ok": bool(text),
            "status": int(status or 0),
            "sha256": _sha256(text),
            "chars": len(text),
            "title": title or extract_title(text),
            "head": text[:MAX_SNAPSHOT_CHARS],
            "via": "chat",              # 标明"这一条是对话路径顺手记的"，不是观察线程抓的
        }
        try:
            self.model.remember_site(u, title=rec["title"])
            self.model.mark_seen(u, status=rec["status"], chars=rec["chars"])
        except Exception as e:      # noqa: silent-ok — 模型写失败也要把快照留下
            logger.warning("ingest 更新世界模型失败(%s)：%s", u, e)
        self._append(self.snapshots_path, rec)
        return rec, changes

    def snapshot(self, url):
        """抓一页 → 记快照 → 更新世界模型。返回快照记录（含 sha256/chars/title/head）。

        为什么每次都记（哪怕内容没变）："没变"本身是重要信息 ——
        它证明了"我看过、它当时是这样"，也是 diff 的基准。
        去掉这一步：diff 就没有"上一次"，永远只能报 first_seen。
        注意口径：`snapshot` **只记不比**（要"记 + 比"用 observe/watch）——
        这样"看一眼"和"看它变没变"是两个动作，调用方想只存档也不会被塞一堆 change。
        """
        rec, _text, _chs = self._fetch_and_record(url)
        return rec

    # ---- ② 比 ----
    def _last_snapshot(self, url):
        """这个 URL 最近一条快照（没有就 None）。

        只回看末尾 `_LAST_LOOKBACK` 行：观察线程每一轮都要为每个 URL 调它一次，
        如果每次都把整个 jsonl（每行带 2000 字正文）解析一遍，观察就会变成"读日志比赛"。
        代价写清楚：如果某个 URL 的最后一条快照落在窗口之外（观察了很多 URL 才会发生），
        这里会当"没看过" → 最多多抓一次。**宁可多抓一次，也不把日志全塞进内存。**
        """
        u = str(url or "").strip()
        for rec in reversed(_load_jsonl(self.snapshots_path, _LAST_LOOKBACK)):
            if rec.get("url") == u:
                return rec
        return None

    def _change(self, kind, detail, url, domain, old_head="", new_head="", **extra):
        c = {"kind": kind, "detail": detail, "url": url, "domain": domain,
             "old_head": old_head, "new_head": new_head}
        c.update(extra)
        return c

    def diff(self, url, new_content):
        """跟**上一次快照**比，返回 Change 列表（kind ∈ first_seen/changed/appeared/disappeared/unchanged）。

        判定口径（写清楚，因为调用方会依赖它）：
          · 从没见过这个 URL（没有快照）  → first_seen
          · 全文 sha256 与上次相同        → unchanged（**不算变化，不写 changes.jsonl**）
          · 上次是空的、现在有内容        → appeared（页面"冒出来"了，典型是抓失败后的恢复）
          · 上次有内容、现在是空的        → disappeared（页面/站点消失了）
          · 其余                          → changed，detail 是前 10 条变化行（unified_diff）

        **顺序契约**：本函数拿"最后一次快照"当基准，所以调用方必须
        "先 diff、后写快照"。这就是 `_fetch_and_record(with_diff=True)` 里那个顺序的原因 ——
        写反了会变成自己跟自己比，永远 unchanged（自测第 6/7 条就是专门守这条的）。

        为什么哈希相同就直接放过：正文一模一样就是没变，
        再去跑行级 diff 只会得到"空白差异/编码差异"这种噪音，白烧 CPU 还污染 changes.jsonl。
        """
        u = str(url or "").strip()
        dom = domain_of_url(u) or u.lower()
        text = str(new_content or "")
        sha = _sha256(text)
        new_head = text[:MAX_SNAPSHOT_CHARS]
        last = self._last_snapshot(u)
        if last is None:
            ch = self._change("first_seen",
                              "第一次看到这个页面（%s）" % (extract_title(text) or dom or u),
                              u, dom, "", new_head, sha256=sha)
            self._append(self.changes_path, dict(ch, ts=round(time.time(), 3)))
            return [ch]
        old_sha = str(last.get("sha256") or "")
        old_head = str(last.get("head") or "")
        if old_sha and old_sha == sha:
            return [self._change("unchanged", "内容与上次完全一致（sha256 相同）",
                                 u, dom, old_head, new_head, sha256=sha)]
        if not old_head.strip() and new_head.strip():
            ch = self._change("appeared", "页面出现内容（上次是空的/抓取失败）",
                              u, dom, old_head, new_head, sha256=sha, old_sha256=old_sha)
        elif old_head.strip() and not new_head.strip():
            ch = self._change("disappeared", "页面内容消失了（抓到了空正文）",
                              u, dom, old_head, new_head, sha256=sha, old_sha256=old_sha)
        else:
            lines = []
            for ln in difflib.unified_diff(old_head.splitlines(), new_head.splitlines(),
                                           lineterm="", n=0):
                if ln.startswith(("+++", "---")):
                    continue
                if ln.startswith(("+", "-")):
                    lines.append(ln)
                if len(lines) >= 10:        # 只要前 10 条：detail 是给人扫一眼的，不是补丁
                    break
            detail = "\n".join(lines) or "哈希变了但没有可读的行级差异（可能是空白/编码差异）"
            ch = self._change("changed", detail, u, dom, old_head, new_head,
                              sha256=sha, old_sha256=old_sha)
        self._append(self.changes_path, dict(ch, ts=round(time.time(), 3)))
        return [ch]

    # ---- ③ 一直看 ----
    def observe(self, urls, model=None):
        """一次性看一批（逐个 snapshot + diff），返回摘要。

        和 watch 的分工：observe 是"现在就走一遍"，watch 是"按节奏一直走"。
        为什么两个都要：用户说"帮我盯一下这几个站"是 watch，app 启动时摸一遍环境是 observe。
        """
        if model is not None:
            self.model = model
        summary = {"checked": 0, "ok": 0, "failed": 0, "changed": 0, "first_seen": 0,
                   "unchanged": 0, "appeared": 0, "disappeared": 0, "errors": [], "items": []}
        for u in (urls or []):
            u = str(u or "").strip()
            if not u:
                continue
            try:
                rec, _text, chs = self._fetch_and_record(u, with_diff=True)
                summary["checked"] += 1
                summary["ok" if rec.get("ok") else "failed"] += 1
                if not rec.get("ok"):
                    summary["errors"].append("%s：%s" % (u, str(rec.get("error") or "")[:120]))
                for ch in chs:
                    k = ch.get("kind")
                    if k in summary:
                        summary[k] += 1
                    if k != "unchanged":
                        summary["changed"] += 1
                summary["items"].append({"url": u, "ok": bool(rec.get("ok")),
                                         "title": rec.get("title", ""), "chars": rec.get("chars", 0),
                                         "kinds": [c.get("kind") for c in chs]})
            except Exception as e:      # noqa: silent-ok — 一个 URL 出问题不能拖垮整批
                summary["errors"].append("%s：%s" % (u, str(e)[:120]))
        return summary

    def _last_seen_ts(self, url):
        """上次**抓取**这个 URL 的时间（取快照 ts；没有就 None）。"""
        rec = self._last_snapshot(url)
        try:
            return float(rec.get("ts")) if rec else None
        except Exception:
            return None

    def _due(self, url, interval=3600, now=None):
        """这个 URL 这轮该不该抓。

        两层判定：
          ① 世界模型说了算（`should_refresh`：按站点自己的类型周期，比如新闻 1h、百科 7d）；
          ② 但**调用方的观察周期更短时，以调用方为准** ——
             调用方显式写 `interval=60`，意思是"我就要每分钟看一眼"，
             这时不该被"这个站是百科、7 天再看"拦住（那是调用方的知情选择）。
        `interval` 的比较留 5% 余量：轮间是用 `Event.wait(interval)` 等的，
        它保证"不早于超时返回"，但时钟精度/调度延迟会让差值在边界上抖。
        """
        now = time.time() if now is None else float(now)
        last = self._last_seen_ts(url)
        try:
            if self.model.should_refresh(url, last_check=last, now=now):
                return True
        except Exception:      # noqa: silent-ok — 模型判定失败时"该看就看"，宁可多看一次
            return True
        try:
            iv = float(interval or 0)
        except Exception:
            iv = 0.0
        if iv > 0 and last and (now - last) >= iv * 0.95:
            return True
        return False

    def watch(self, urls, interval=3600, stop_event=None, max_rounds=None):
        """**持续观察**：不是用户问了才看，是自己一直在看。

        为什么必须存在（这是"世界"和"工具箱"的分水岭）：
        工具箱模式的感知是"被调用才发生"，那互联网永远只是工具箱；
        只有它自己按节奏睁眼，互联网才真的是"它生活的世界"。

        daemon 友好：全程可被打断（`stop_event.wait(interval)` 而不是 `time.sleep`），
        每轮 try/except（一个站挂了不影响别的站、不影响下一轮），
        `max_rounds` 让"跑几轮就收工"成为可能（自测/一次性巡检）。
        返回统计：rounds/fetched/ok/failed/changed/stopped/elapsed_s/errors。
        去掉 `stop_event`：后台线程只能靠"杀进程"停，会把世界模型写在半路（见 model.save 的原子写）。
        """
        urls = [str(u or "").strip() for u in (urls or [])]
        urls = [u for u in urls if u]
        stats = {"rounds": 0, "fetched": 0, "ok": 0, "failed": 0, "changed": 0,
                 "stopped": False, "elapsed_s": 0.0, "errors": []}
        t0 = time.time()
        limit = int(max_rounds) if max_rounds else 0
        while True:
            if stop_event is not None and stop_event.is_set():
                stats["stopped"] = True
                break
            if limit and stats["rounds"] >= limit:
                break
            stats["rounds"] += 1
            for u in urls:
                if stop_event is not None and stop_event.is_set():
                    stats["stopped"] = True
                    break
                try:
                    if not self._due(u, interval=interval):
                        continue
                    rec, _text, chs = self._fetch_and_record(u, with_diff=True)
                    stats["fetched"] += 1
                    stats["ok" if rec.get("ok") else "failed"] += 1
                    if not rec.get("ok"):
                        stats["errors"].append("%s：%s" % (u, str(rec.get("error") or "")[:120]))
                    elif chs and chs[0].get("kind") != "unchanged":
                        stats["changed"] += 1
                except Exception as e:      # noqa: silent-ok — 观察线程绝不能因为一个站崩掉
                    stats["errors"].append("%s：%s" % (u, str(e)[:120]))
            if stats["stopped"]:
                break
            if limit and stats["rounds"] >= limit:
                break          # 最后一轮不再等待（自测跑 3 轮就只花 2 个 interval）
            try:
                wait = max(0.0, float(interval or 0))
            except Exception:
                wait = 0.0
            if stop_event is not None:
                if stop_event.wait(wait):       # 置位立刻醒，不等满
                    stats["stopped"] = True
                    break
            elif wait > 0:
                time.sleep(wait)
        stats["elapsed_s"] = round(time.time() - t0, 2)
        return stats

    # ---- ④ 世界现在什么样 ----
    def availability(self):
        """各站点最近一次抓取的 ok/状态码 → 环境状态感知。

        为什么要有：小焦该知道"世界现在通不通"。被墙/被限流/某个站挂了，
        回答时就应该说"我这会儿连不上"，而不是装作自己看过。
        数据来自快照日志（失败的抓取也记），所以"红"是有据可查的。
        """
        latest = {}
        for rec in _load_jsonl(self.snapshots_path, 2000):
            d = str(rec.get("domain") or "")
            if d:
                latest[d] = rec                 # 顺序覆盖 → 最后一条就是最近一条
        sites = {}
        try:
            known = list(self.model.sites.keys())
        except Exception:
            known = []
        for d in list(dict.fromkeys(known + list(latest.keys()))):
            rec = latest.get(d)
            sites[d] = {
                "ok": (bool(rec.get("ok")) if rec else None),
                "status": int((rec or {}).get("status") or 0),
                "ts": (rec or {}).get("ts"),
                "chars": int((rec or {}).get("chars") or 0),
                "error": str((rec or {}).get("error") or "")[:200],
                "seen": bool(rec),
            }
        ok = sum(1 for v in sites.values() if v["ok"] is True)
        down = sum(1 for v in sites.values() if v["ok"] is False)
        return {"sites": sites, "total": len(sites), "ok": ok, "down": down,
                "updated": round(time.time(), 3)}

    def hot_topics(self, limit=10):
        """**今天互联网在讨论什么**：最近快照里高频的 2~4 字中文词 + 英文词。

        为什么值得做：世界感不是"我看过 37 个页面"，而是"我知道现在大家在聊什么"。
        这是"一直在看"的产出物 —— 只有持续观察攒下的快照，才提炼得出热点。
        口径说明（诚实的部分）：
          · 只取最近 MAX_HOT_SNAPSHOTS 条快照的标题 + 正文前 300 字（够代表主题，又不至于全站噪音）；
          · 只保留**出现 ≥2 次**的词 —— 只出现一次的多半是页面模板/人名/一次性琐事；
          · 被更长同频词包含的短词会被跳过（列了「人工智能」就不再列「人工」「智能」）；
          · 返回 [(词, 次数)]，按次数降序、同次数长的优先。
        **已知局限（别当 bug）**：这里没有分词器，所以"跨词边界"的 4-gram 会混进来 ——
        比如标题「量子计算快讯」会额外产出「计算快讯」「子计算快」这种假词。
        榜单**第一名是可靠的**（真词的出现次数通常远高于边界碎片），越往后越要人工判断。
        要彻底解决得挂一个中文分词（额外依赖 + 额外维护），而这一层的目标是
        "今天大概在聊什么"，不是词法分析 —— 所以这里选择**接受噪音并说明它**，
        而不是让感知层多背一个词典依赖。
        去掉 hot_topics：小焦能看到页面，却说不出"世界现在什么样" —— 那就是有眼睛、没脑子。
        """
        texts = []
        for rec in _load_jsonl(self.snapshots_path, MAX_HOT_SNAPSHOTS):
            if rec.get("ok") is False:
                continue
            body = str(rec.get("head") or "")[:300]
            texts.append((str(rec.get("title") or "") + " " + body).strip())
        counter = Counter()
        for t in texts:
            if not t:
                continue
            # 先剥标签再数词：不剥的话 top10 里会混进 title/body/html/div 这些**标点之外的噪音**
            # （第一版自测就撞上了：第 2、3 名是 'title' 和 'body'）。它们是网页的零件，不是话题。
            t = _TAG_RE.sub(" ", t)
            for run in _CJK_RE.findall(t):
                for n in (2, 3, 4):
                    for i in range(len(run) - n + 1):
                        g = run[i:i + n]
                        if g in _HOT_STOP:
                            continue
                        counter[g] += 1
            for w in _EN_RE.findall(t):
                if w.lower() in _HOT_STOP_EN:
                    continue
                counter[w] += 1
        cands = [(w, c) for w, c in counter.items() if c >= 2]
        cands.sort(key=lambda x: (-x[1], -len(x[0]), x[0]))
        out = []
        for w, c in cands:
            if any(w != o and w in o for o, _ in out):
                continue
            out.append((w, c))
            if len(out) >= int(limit or 10):
                break
        return out

    def stats(self):
        """感知层的体检数字（自检/面板用）：看过多少页、变了多少次、环境通不通。"""
        snaps = _load_jsonl(self.snapshots_path, 2000)
        chgs = _load_jsonl(self.changes_path, 2000)
        kinds = Counter(str(c.get("kind") or "") for c in chgs)
        return {"snapshots": len(snaps), "changes": len(chgs), "by_kind": dict(kinds),
                "sites_seen": len({str(s.get("domain") or "") for s in snaps if s.get("domain")}),
                "world": self.model.stats(), "last_error": self.last_error,
                "snapshots_path": self.snapshots_path, "changes_path": self.changes_path}

    def describe_interval(self, url):
        """这个站多久看一次（人话版，方便面板显示）。"""
        sec = self.model.refresh_interval(url)
        return format_interval(sec) or "%ds" % sec

    def __repr__(self):
        return "<WorldPerception dir=%s %s>" % (self.state_dir, self.model)
