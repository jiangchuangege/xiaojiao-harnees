# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 公开电子书采集（2026-10-17）

【它是干什么的】给一个**公开**的资料站/书站，把「目录 → 条目 → 文件」这条链走完：
  1. `ebook_manifest`：抓目录页，输出书目清单（标题 + 详情链接 + 疑似格式），可存成 CSV/Markdown；
  2. `ebook_grab`：逐条进详情页，找**公开的文件直链**（pdf/epub/mobi/txt/zip），下载到本地目录。

【为什么要有它】用户实测：「帮我爬一下电子书 <网址> 下载到 G:\\dzs」——
  原来的抓取只能把网页正文贴在聊天框里，"下载到本地"这句话没人接；
  抓取意图还被"下载"这个动作词排除掉，最后模型跑去调截图，还自己编了 session_id。
  这条链补上之后，同一句话 5 秒内能真落盘（见 CHANGELOG「爬下来存到本地」那段）。

【三条边界，写死在代码里，不靠提示词求模型自觉】
  ① **不碰付费墙/登录墙**：详情页一旦出现「登录 / VIP / 会员 / 付费 / 购买 / 扫码」这类信号，
     该条目**直接跳过**并在结果里写明原因 —— 不尝试绕过、不伪装登录、不猜文件路径。
     绕过付费墙不是"能力",是侵权；这条不做，也建议你别找别的工具去做。
  ② **尊重 robots.txt**：被 Disallow 的路径一律不抓，如实说明。
  ③ **只下白名单扩展名的公开直链**，并且**验文件头**（PDF 必须是 `%PDF`，EPUB/ZIP 必须是 `PK`），
     免得把登录页/错误页当成书存进你的目录。

【只用标准库 + requests + bs4】没有额外依赖；不开浏览器，不需要 session。
【自测】`tools/test_ebook_plugin.py` 配 `tests/fake_book_site.py`（本地假站，不碰真网站）：
  公开条目能列出能下载、付费条目被跳过并说明原因、robots 禁止的不抓、文件头不对的不落盘。
"""
import csv
import ipaddress
import logging
import os
import re
import socket
import time
import urllib.parse as up
import urllib.robotparser as urp

try:
    import requests
except Exception:                      # pragma: no cover - 环境缺 requests 时插件自己降级
    requests = None

try:
    from bs4 import BeautifulSoup
except Exception:                      # pragma: no cover
    BeautifulSoup = None

LOG = logging.getLogger(__name__)

_UA = "XiaoJiao-EbookCollector/1.0 (+public-domain & open-access only)"
_FILE_EXT = ("pdf", "epub", "mobi", "azw3", "txt", "zip", "djvu")
_MAX_BYTES = 40 * 1024 * 1024          # 单文件上限 40MB（再大的一般不是"一本书"）
_RATE_GAP = 0.6                        # 同一域名两次请求的最小间隔（秒），别去敲人家服务器
_last_hit = {}                         # host -> 上次请求时间
_robots_cache = {}                     # host -> (RobotFileParser 或 None, 取回时间)
_ROBOTS_TTL = 600.0

# 付费/登录墙的信号词。命中就**不下**，只说明原因。
_PAYWALL = ("vip", "会员", "付费", "购买", "请登录", "登录后", "注册后", "积分", "金币",
            "扫码", "支付", "充值", "解锁", "权限不足", "仅限", "购买后", "网盘密码", "提取码")
# 目录页里"不算条目"的链接（导航、标签、分页、静态资源）
_NAV_SKIP = ("/tag/", "/tags/", "/page/", "/category/", "/user/", "/login", "/register",
             "/cart", "/vip", "/about", "/contact", "/feed", "/rss", "#")


def _ok(msg):
    return msg


def _err(msg):
    return "⚠️ " + msg


def _now():
    return time.time()


def _throttle(host):
    """同一域名别连着敲：两次请求至少隔 _RATE_GAP 秒。"""
    t = _last_hit.get(host, 0.0)
    gap = _RATE_GAP - (_now() - t)
    if gap > 0:
        time.sleep(gap)
    _last_hit[host] = _now()


def _ssrf_ok(url):
    """只允许 http/https 且不指向本机/内网（防止被当成内网探针）。

    自测需要打本地假站：设 `XIAOJIAO_EBOOK_ALLOW_LOCAL=1` 才放行环回地址。
    """
    try:
        p = up.urlsplit(url)
    except Exception:
        return False, "网址解析不了"
    if p.scheme not in ("http", "https"):
        return False, "只支持 http/https"
    host = p.hostname or ""
    if not host:
        return False, "网址里没有主机名"
    allow_local = os.environ.get("XIAOJIAO_EBOOK_ALLOW_LOCAL", "") == "1"
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                if allow_local and (ip.is_loopback or ip.is_private):
                    continue
                return False, "目标是内网/本机地址，已被安全策略拦下"
    except Exception:
        # 解析不了就交给 requests 去报错（这里不拦，避免把能用的站点误杀）
        pass
    return True, ""


def _robots_ok(url):
    """robots.txt 允许抓这个地址吗？读不到 robots（404/超时）按允许处理（RFC 惯例）。"""
    try:
        p = up.urlsplit(url)
        root = "%s://%s" % (p.scheme, p.netloc)
        rec = _robots_cache.get(root)
        if not rec or (_now() - rec[1]) > _ROBOTS_TTL:
            rp = None
            try:
                _throttle(p.hostname or "")
                r = requests.get(root + "/robots.txt", timeout=8, headers={"User-Agent": _UA})
                if r.status_code == 200 and r.text.strip():
                    rp = urp.RobotFileParser()
                    rp.parse(r.text.splitlines())
            except Exception as e:      # noqa: silent-ok — 取不到 robots 不等于禁止
                LOG.info("ebook：robots.txt 取不到（按允许处理）：%s", e)
            _robots_cache[root] = (rp, _now())
            rec = _robots_cache[root]
        rp = rec[0]
        if rp is None:
            return True, ""
        return (bool(rp.can_fetch(_UA, url)), "" if rp.can_fetch(_UA, url)
                else "robots.txt 不允许抓这个地址（站点明确禁止）")
    except Exception as e:              # noqa: silent-ok — 判不了就别拦，交给上层如实报
        LOG.info("ebook：robots 判定异常（按允许处理）：%s", e)
        return True, ""


def _get(url, timeout=20):
    """带限速 + 编码兜底的一次 GET。返回 (text or "", error or "")。"""
    if requests is None:
        return "", "这台机器没装 requests，抓不了网页"
    ok, why = _ssrf_ok(url)
    if not ok:
        return "", why
    allow, why2 = _robots_ok(url)
    if not allow:
        return "", why2
    try:
        _throttle(up.urlsplit(url).hostname or "")
        r = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return "", "HTTP %s（对方拒绝或页面不存在）" % r.status_code
        # 编码兜底：中文站常常不写 charset，requests 会猜错 → 手动用 apparent_encoding
        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text, ""
    except Exception as e:
        return "", "抓取失败：%s: %s" % (type(e).__name__, str(e)[:120])


def _soup(html):
    if BeautifulSoup is None:
        return None
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:                   # noqa: silent-ok — 解析不了就当没有 DOM，退回正则
        return None


def _paywall_hits(html):
    """页面里出现了哪些付费/登录信号（去标签后扫，避免把 CSS 类名当证据）。"""
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    txt = re.sub(r"(?s)<[^>]+>", " ", txt).lower()
    return [w for w in _PAYWALL if w in txt]


def _file_links(html, base):
    """从详情页里挑出**公开文件直链**（白名单扩展名，绝对化 URL）。"""
    out = []
    s = _soup(html)
    hrefs = []
    if s is not None:
        for a in s.find_all("a", href=True):
            hrefs.append(a["href"])
    else:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html or "", re.I)
    for h in hrefs:
        u = up.urljoin(base, h.strip())
        path = up.urlsplit(u).path.lower()
        ext = path.rsplit(".", 1)[-1] if "." in path else ""
        if ext in _FILE_EXT and u not in out:
            out.append(u)
    return out


def _safe_name(url, idx=0):
    """从网址取一个能落盘的文件名（去参数、解 URL 编码、清非法字符）。"""
    name = up.unquote(os.path.basename(up.urlsplit(url).path)) or ""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip() or "book"
    if idx:
        stem, dot, ext = name.rpartition(".")
        name = ("%s_%d.%s" % (stem, idx, ext)) if dot else ("%s_%d" % (name, idx))
    return name[:90]


def _magic_ok(path, ext):
    """验文件头：PDF 必须 %PDF，EPUB/ZIP 必须 PK；其它格式不验（只要求非空）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if not head:
            return False, "下载下来是空文件"
        if ext == "pdf" and not head.startswith(b"%PDF"):
            return False, "文件头不是 PDF（可能下到的是登录页/错误页）"
        if ext in ("epub", "zip") and not head.startswith(b"PK"):
            return False, "文件头不是 ZIP/EPUB（可能下到的是登录页/错误页）"
        return True, ""
    except Exception as e:
        return False, "读文件失败：%s" % str(e)[:80]


def _download(url, out_dir, idx=0):
    """下一条文件直链。返回 (落盘路径 or "", 说明 or 错误)。

    【为什么要重试一次】真机踩到：Gutenberg 那本 25MB 的 zip，第一次下到 11MB 时
    `ChunkedEncodingError / IncompleteRead`（连接被掐断）。这类中断是网络抖，不是"内容不可用"，
    直接判失败太武断 —— 重试一次，两次都不行才如实说失败。
    """
    ok, why = _ssrf_ok(url)
    if not ok:
        return "", why
    allow, why2 = _robots_ok(url)
    if not allow:
        return "", why2
    ext = up.urlsplit(url).path.lower().rsplit(".", 1)[-1]
    name = _safe_name(url, idx)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return "", "建目录失败：%s" % str(e)[:100]
    path = os.path.join(out_dir, name)
    last = ""
    have = 0                    # 已经落盘的字节数（重试时用它做断点续传）
    for attempt in (1, 2, 3):
        got, expect = have, 0
        try:
            _throttle(up.urlsplit(url).hostname or "")
            headers = {"User-Agent": _UA}
            if have:
                # 断点续传：上一次下了 24.6MB 被掐断，这次从断点接着要，不重头再来。
                headers["Range"] = "bytes=%d-" % have
            with requests.get(url, timeout=90, stream=True, headers=headers) as r:
                if r.status_code not in (200, 206):
                    last = "HTTP %s" % r.status_code
                    continue
                if r.status_code == 200 and have:
                    have = 0                    # 对方不认 Range → 只能从头写
                    got = 0
                try:
                    _cl = int(r.headers.get("Content-Length") or 0)
                except Exception:       # noqa: silent-ok — 没有长度头就不校验长度
                    _cl = 0
                expect = (have + _cl) if (r.status_code == 206 and _cl) else (_cl or 0)
                mode = "ab" if (have and r.status_code == 206) else "wb"
                with open(path, mode) as f:
                    for chunk in r.iter_content(65536):
                        if not chunk:
                            continue
                        got += len(chunk)
                        if got > _MAX_BYTES:
                            f.close()
                            os.remove(path)
                            return "", "文件超过 %dMB 上限，已放弃（不像一本书）" % (_MAX_BYTES // 1048576)
                        f.write(chunk)
            if expect and got < expect:
                have = got                      # 记下断点，下一轮续传
                last = "下载不完整（%d/%d 字节）" % (got, expect)
                continue
            okm, whym = _magic_ok(path, ext)
            if not okm:
                os.remove(path)
                return "", whym
            return path, "%d 字节%s" % (got, "" if attempt == 1 else "（第 %d 次续传后成功）" % attempt)
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:100])
            try:
                have = os.path.getsize(path)    # 连接中途断掉：保住已下的部分，下轮接着下
            except Exception:       # noqa: silent-ok — 文件都还没建就从头来
                have = 0
    if os.path.isfile(path):
        try:
            os.remove(path)                     # 三次都没下完整 → 不留半截文件骗人
        except Exception:           # noqa: silent-ok
            pass
    return "", "下载失败（试了 3 次，含断点续传）：%s" % last


def _looks_listing(links):
    """同一站内、看起来是"条目详情页"的链接够多 → 当成目录页。"""
    return len(links) >= 3


def _entry_links(html, base):
    """目录页里的条目链接：[(地址, 链接文字)]（同站、排除导航/标签/分页/静态资源）。

    为什么带上链接文字：书目清单要给人看 —— 只给一串 `/book/16463.html` 没法用，
    文字里通常就是书名。
    """
    s = _soup(html)
    base_host = up.urlsplit(base).hostname or ""
    out, seen = [], set()
    anchors = []
    if s is not None:
        for a in s.find_all("a", href=True):
            anchors.append((a["href"], a.get_text(" ", strip=True)))
    else:
        anchors = [(h, "") for h in re.findall(r'href=["\']([^"\']+)["\']', html or "", re.I)]
    for h, txt in anchors:
        u = up.urljoin(base, h.strip())
        p = up.urlsplit(u)
        if (p.hostname or "") != base_host:
            continue
        low = p.path.lower()
        if any(k in low for k in _NAV_SKIP) or low in ("", "/"):
            continue
        if low.rsplit(".", 1)[-1] in _FILE_EXT:      # 直接就是文件 → 不算"条目页"
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append((u, (txt or "").strip()[:80]))
    return out


def _title_of(html, fallback=""):
    s = _soup(html)
    if s is not None:
        t = s.find("title")
        if t and t.get_text(strip=True):
            return t.get_text(strip=True)[:80]
        h1 = s.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)[:80]
    return fallback


# ============================== 工具实现 ==============================
def do_manifest(p):
    """抓目录页 → 书目清单（标题 + 链接 + 疑似格式）。"""
    url = str(p.get("url") or "").strip()
    if not url:
        return _err("ebook_manifest 需要 url（要抓的目录页地址）")
    try:
        limit = int(p.get("limit") or 50)
    except Exception:
        limit = 50
    limit = max(1, min(limit, 200))
    html, why = _get(url)
    if why:
        return _err("目录页没抓到：%s" % why)
    links = _entry_links(html, url)
    if not links:
        return _ok("这一页里没找到「条目」链接（可能不是目录页，或者条目都是异步加载的）。\n"
                   "建议：把具体的书目页地址给我，或改用 ebook_grab 直接抓某个条目页。")
    rows = []
    for i, (u, txt) in enumerate(links[:limit], 1):
        rows.append({"序号": i, "书名": txt or _safe_name(u).replace("_", " "), "链接": u})
    out = p.get("out") or ""
    note = ""
    if out:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
            if str(out).lower().endswith(".md"):
                with open(out, "w", encoding="utf-8") as f:
                    f.write("# 书目清单（来源：%s）\n\n" % url)
                    f.write("| 序号 | 书名 | 链接 |\n| --- | --- | --- |\n")
                    for r in rows:
                        f.write("| %d | %s | %s |\n" % (r["序号"], r["书名"], r["链接"]))
            else:
                with open(out, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=["序号", "书名", "链接"])
                    w.writeheader()
                    w.writerows(rows)
            note = "\n\n已存清单：`%s`（%d 条）" % (out, len(rows))
        except Exception as e:
            note = "\n\n（清单没能存到 `%s`：%s）" % (out, str(e)[:100])
    head = ("📚 **目录页解析结果**（%s）\n共找到 %d 个条目链接，先列前 %d 条：\n\n"
            % (url, len(links), len(rows)))
    body = "\n".join("%d. %s\n   %s" % (r["序号"], r["书名"], r["链接"]) for r in rows[:30])
    more = ("\n\n…（还有 %d 条，用更小的 limit 或看清单文件）" % (len(rows) - 30)
            if len(rows) > 30 else "")
    return _ok(head + body + more + note + _policy_note())


def _policy_note():
    return ("\n\n—— 只采集**公开**内容：遇到登录/付费墙会跳过并说明原因，不绕过。"
            "请确认目标站点允许下载，或内容本身是公有领域/开放授权。")


def do_grab(p):
    """逐条进详情页找公开直链并下载到目录。"""
    url = str(p.get("url") or "").strip()
    out_dir = str(p.get("out_dir") or p.get("out") or "").strip()
    if not url:
        return _err("ebook_grab 需要 url（书目页或详情页地址）")
    if not out_dir:
        return _err("ebook_grab 需要 out_dir（存到哪个目录，例如 G:\\dzs）")
    try:
        limit = int(p.get("limit") or 10)
    except Exception:
        limit = 10
    limit = max(1, min(limit, 30))

    html, why = _get(url)
    if why:
        return _err("这一页没抓到：%s" % why)
    hits = _paywall_hits(html)
    entries = _entry_links(html, url)
    # 两种页面，两种走法（真机把这条试出来了）：
    #   · **详情页**（Gutenberg 的书页）→ 本页就有 pg1342-h.zip，只抓本页。
    #     不能顺手把页面里的 help/ browse/ author/ 也当"章节"去抓 —— 那是站点导航，
    #     实测会白跑 5 个请求、结果里出现一串"跳过：没有文件直链"的噪音。
    #   · **目录页**（列表页，本页没有文件直链）→ 按 limit 逐条进详情页。
    own_files = _file_links(html, url)
    todo = []
    if own_files:
        todo.append((url, html))
    else:
        for u, _t in entries[:limit]:
            if u != url:
                todo.append((u, None))
    if not todo:
        todo.append((url, html))

    ok_files, skipped, failed = [], [], []
    for page, pre_html in todo:
        page_html, why2 = (pre_html, "") if pre_html is not None else _get(page)
        if why2:
            failed.append((page, "详情页没抓到：%s" % why2))
            continue
        wall = _paywall_hits(page_html)
        flinks = own_files if page == url else _file_links(page_html, page)
        if wall:
            skipped.append((page, "需登录/付费（页面出现：%s）→ **未采集**" % "、".join(sorted(set(wall))[:5])))
            continue
        if not flinks:
            skipped.append((page, "这一页没有公开的文件直链（pdf/epub/txt…）→ 未采集"))
            continue
        for j, fu in enumerate(flinks[:3], 1):        # 一条条目最多下 3 个文件
            path, note = _download(fu, out_dir, idx=j if len(flinks) > 1 else 0)
            if path:
                ok_files.append((path, fu, note))
                LOG.info("ebook：已下载 %s（%s）", path, note)
            else:
                failed.append((fu, note))

    lines = ["📥 **采集结果**（来源：%s → `%s`）" % (url, out_dir)]
    if ok_files:
        lines.append("\n**成功 %d 个**：" % len(ok_files))
        for path, fu, note in ok_files:
            lines.append("- `%s`（%s）\n  ← %s" % (path, note, fu))
    if skipped:
        lines.append("\n**跳过 %d 个**（如实说明，不硬来）：" % len(skipped))
        for page, why3 in skipped[:10]:
            lines.append("- %s\n  %s" % (page, why3))
        if len(skipped) > 10:
            lines.append("- …还有 %d 个同样跳过" % (len(skipped) - 10))
    if failed:
        lines.append("\n**失败 %d 个**：" % len(failed))
        for page, why3 in failed[:8]:
            lines.append("- %s\n  %s" % (page, why3))
    if not ok_files:
        lines.append("\n这次**一个文件都没下下来**。上面每条都写了原因；"
                     "如果是付费/登录墙，那不是我该绕的东西 —— 你登录后再说，或者直接给我文件直链。")
    if hits and not ok_files:
        lines.append("\n（这一页本身也命中了付费/登录信号：%s）" % "、".join(sorted(set(hits))[:5]))
    return _ok("\n".join(lines) + _policy_note())


_TOOLS = [
    {
        "name": "ebook_manifest",
        "description": "解析公开书站目录页成书目清单（可存 CSV/MD）。什么时候用：要书目一览；输入 url；输出清单",
        "parameters": {
            "url": {"type": "string", "description": "目录页地址（http/https）"},
            "out": {"type": "string", "description": "清单保存路径（可选，.csv 或 .md）"},
            "limit": {"type": "integer", "description": "最多列多少条（默认 50，上限 200）"},
        },
        "required": ["url"],
    },
    {
        "name": "ebook_grab",
        "description": "把公开电子书的文件下载到本地，遇付费墙跳过并说明。什么时候用：要成批存书；输入 url+out_dir",
        "parameters": {
            "url": {"type": "string", "description": "目录页或条目页地址"},
            "out_dir": {"type": "string", "description": "保存目录，例如 G:\\dzs"},
            "limit": {"type": "integer", "description": "最多处理多少个条目（默认 10，上限 30）"},
        },
        "required": ["url", "out_dir"],
    },
]


class EbookPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        try:
            if tool_name == "ebook_manifest":
                return do_manifest(params)
            if tool_name == "ebook_grab":
                return do_grab(params)
            return ("电子书插件里没有「%s」这个工具（它只有 ebook_manifest、ebook_grab）。"
                    % tool_name)
        except Exception as e:          # noqa: silent-ok — 插件内部异常必须转成中文说明
            LOG.warning("ebook 插件内部异常（已转成说明）：%s: %s", type(e).__name__, e)
            return ("⚠️ 电子书插件内部出错了（%s: %s）。先确认网址能打开、"
                    "保存目录可写；换个小一点的 limit 再试一次。"
                    % (type(e).__name__, str(e)[:120]))


_PLUGIN = EbookPlugin()


def get_plugin():
    return _PLUGIN
