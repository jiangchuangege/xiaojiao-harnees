# -*- coding: utf-8 -*-
"""一个**假的书站**，只给自测用（2026-10-17 加）

为什么要有它：`plugins/ebook.py` 是采集插件，自测**不能去打真网站** ——
一是别人的服务器不该被测试流量敲，二是测试必须确定性（真站点会改版、会限流、会挂）。
所以这里起一个本地 http 服务，把五种情况都摆出来：

    /books            目录页：4 个条目 + 1 个直接文件链接
    /book/1.html      公开条目 → 页面里有 /files/a.pdf（真 PDF 文件头）
    /book/2.html      **付费墙**条目（页面出现 VIP / 会员 / 请登录）→ 必须跳过并说明
    /secret/3.html    **robots.txt 禁止**的目录（Disallow: /secret/）→ 必须不抓
    /book/4.html      页面里有 /files/fake.pdf，但那"pdf"其实是 HTML（登录页）→ 必须靠**验文件头**拦下
    /robots.txt       User-agent: * / Disallow: /secret/

用法：
    python tests/fake_book_site.py            # 起来看看（打印端口）
    在自测里：srv = start(); srv.base; srv.stop()
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 最小可用 PDF：文件头必须是 %PDF（插件会验这个）
PDF_BYTES = (b"%PDF-1.4\n"
             b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
             b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
             b"trailer<</Root 1 0 R>>\n%%EOF\n")

LISTING = """<!doctype html><html><head><meta charset="utf-8"><title>电子书目录</title></head><body>
<nav><a href="/tag/paoni">分类</a> <a href="/page/2">下一页</a> <a href="/login">登录</a></nav>
<ul>
  <li><a href="/book/1.html">公开书一（PDF）</a></li>
  <li><a href="/book/2.html">要会员的书二（PDF）</a></li>
  <li><a href="/secret/3.html">藏在禁止目录里的书三（PDF）</a></li>
  <li><a href="/book/4.html">书四（链接是假的）</a></li>
</ul>
<p><a href="/about">关于本站</a></p>
</body></html>"""

PAGE_PUBLIC = """<!doctype html><html><head><meta charset="utf-8"><title>公开书一</title></head><body>
<h1>公开书一</h1>
<p>公有领域内容，可自由下载。</p>
<a href="/files/a.pdf">下载 PDF</a>
</body></html>"""

PAGE_PAYWALL = """<!doctype html><html><head><meta charset="utf-8"><title>要会员的书二</title></head><body>
<h1>要会员的书二</h1>
<p>本资源为 VIP 会员专享，请登录后购买或开通会员再下载。</p>
<a href="/files/b.pdf">下载 PDF</a>
</body></html>"""

PAGE_SECRET = """<!doctype html><html><head><meta charset="utf-8"><title>书三</title></head><body>
<a href="/files/c.pdf">下载 PDF</a>
</body></html>"""

PAGE_FAKE = """<!doctype html><html><head><meta charset="utf-8"><title>书四</title></head><body>
<p>链接看着像 PDF，其实是登录页。</p>
<a href="/files/fake.pdf">下载 PDF</a>
</body></html>"""

ROBOTS = "User-agent: *\nDisallow: /secret/\n"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):     # 静音：测试输出里不要一堆访问日志
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):                      # noqa: N802 — http.server 的命名约定
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            return self._send(200, ROBOTS, "text/plain; charset=utf-8")
        if path in ("/books", "/books/"):
            return self._send(200, LISTING)
        if path == "/book/1.html":
            return self._send(200, PAGE_PUBLIC)
        if path == "/book/2.html":
            return self._send(200, PAGE_PAYWALL)
        if path == "/book/4.html":
            return self._send(200, PAGE_FAKE)
        if path == "/secret/3.html":
            return self._send(200, PAGE_SECRET)
        if path in ("/files/a.pdf", "/files/b.pdf", "/files/c.pdf"):
            return self._send(200, PDF_BYTES, "application/pdf")
        if path == "/files/fake.pdf":
            # 故意错：扩展名是 pdf，内容却是 HTML（模拟"点了下载其实是登录页"）
            return self._send(200, "<!doctype html><html><body>请登录</body></html>")
        return self._send(404, "<h1>404</h1>")


class FakeBookSite:
    """本地假站：start() 起来，stop() 关掉，base 是根地址。"""

    def __init__(self):
        self._srv = None
        self._th = None
        self.base = ""

    def start(self):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.base = "http://127.0.0.1:%d" % self._srv.server_address[1]
        self._th = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._th.start()
        return self

    def stop(self):
        try:
            self._srv.shutdown()
            self._srv.server_close()
        except Exception:                  # noqa: silent-ok — 关不掉也不影响结论
            pass


if __name__ == "__main__":
    s = FakeBookSite().start()
    print("假书站已启动：", s.base)
    print("  目录页：", s.base + "/books")
    print("  公开页：", s.base + "/book/1.html")
    print("  付费页：", s.base + "/book/2.html")
    print("  禁止目录：", s.base + "/secret/3.html")
    try:
        input("回车退出…")
    except Exception:                      # noqa: silent-ok
        pass
    s.stop()
