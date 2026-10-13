# tools/test_cloud_video_spec.py —— 「接任意云端视频 API」的离线自测（不联网、不花钱）
#
# 为什么要有这套：2026-10-14 用户说「云端 Agnes 这个不一定是 agnes 要兼容任意的」。
# 之前那份适配器是按域名猜厂商、认不出就说"暂未支持"，等于把某一家的规矩写进了载体。
# 现在改成配置驱动 —— 于是必须能自证这几件事：
#   ① 接一家**从没听过**的厂商，只写 video_api 就能跑通（建任务 → 轮询 → 下载）；
#   ② 各家返回的嵌套形状再怪，也能按 JSON 路径取到 id / 状态 / 地址；
#   ③ 状态词、认证方式、base_url 带不带 /v1 这些差异都处理得掉；
#   ④ **没实测过的预设默认拒绝执行**（不许拿没验过的协议去烧用户的钱和时间）；
#   ⑤ Agnes 那一家的参数规矩仍然只有一份实现（走 agenes.build_body）。
import os, sys, json, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "video_service"))

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


class FakeResp:
    def __init__(self, status_code=200, payload=None, text="", content=b"VIDEOBYTES"):
        self.status_code = status_code
        self._p = payload
        self.text = text or json.dumps(payload, ensure_ascii=False)
        self.content = content

    def json(self):
        if self._p is None:
            raise ValueError("不是 JSON")
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)


class FakeRequests(types.ModuleType):
    """假的 requests：把每个请求记下来，按脚本回响应。用于离线验证整套流程。"""

    def __init__(self, create=None, query=None, download=b"VIDEOBYTES"):
        super().__init__("requests")
        self.calls = []
        self._create = create
        self._query = query if isinstance(query, list) else [query] * 10
        self._download = download
        self._q_i = 0

    def post(self, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append({"m": "POST", "url": url, "headers": headers or {}, "json": json, "params": params or {}})
        return self._create

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"m": "GET", "url": url, "headers": headers or {}, "params": params or {}})
        if url.startswith("http") and ("video" in url and url.endswith(".mp4")):
            return FakeResp(200, None, "bytes")
        r = self._query[min(self._q_i, len(self._query) - 1)]
        self._q_i += 1
        return r


def with_fakes(fn):
    """把 video_api_spec 里的 requests 换成假的（它是在函数内 import 的，所以要先塞进 sys.modules）。"""
    import video_api_spec as V
    real = sys.modules.get("requests")
    sys.modules["requests"] = fn
    return real


def restore(real):
    if real is None:
        sys.modules.pop("requests", None)
    else:
        sys.modules["requests"] = real


def main():
    print("== 云端视频「兼容任意厂商」离线自测 ==")
    import video_api_spec as V

    # ---------- ① JSON 路径：各家嵌套都能取 ----------
    nested = {"data": [{"task": {"id": "t-9", "state": "生成中", "output": {"video_url": "https://x/v.mp4"}}}]}
    ok("JSON 路径：嵌套 dict", V.json_path(nested, "data.0.task.id") == "t-9")
    ok("JSON 路径：取不到返回默认值(不抛)", V.json_path(nested, "data.9.nope", "无") == "无")
    ok("候选路径：按顺序取第一个非空", V.first_path(nested, ("a.b", "data.0.task.id")) == "t-9")

    # ---------- ③ 状态词：英文/中文/大写都能认 ----------
    sp = V.spec_for({"name": "x", "base_url": "https://api.x.com", "api_key": "k", "model": "m"})
    ok("状态：completed 算完成", V.status_of(sp, {"status": "COMPLETED"})[0] == "done")
    ok("状态：中文「生成中」算没完成", V.status_of(sp, {"status": "生成中"})[0] == "pending")
    ok("状态：failed 算失败", V.status_of(sp, {"status": "failed"})[0] == "failed")
    ok("状态：认不出来的状态**不当成功**", V.status_of(sp, {"status": "weird-new-state"})[0] == "pending")
    ok("状态：没有 status 字段也不当成功", V.status_of(sp, {})[0] == "pending")

    # ---------- ③ base_url 带不带 /v1 都要对 ----------
    ok("URL：base 带 /v1 不重复", V._join("https://a.com/v1", "/v1/videos") == "https://a.com/v1/videos")
    ok("URL：base 不带 /v1 也拼对", V._join("https://a.com", "/v1/videos") == "https://a.com/v1/videos")
    ok("URL：查重只按整段算", V._join("https://a.com/v1/foo", "/videos") == "https://a.com/v1/foo/videos")

    # ---------- ③ 认证方式 ----------
    h = V.build_headers({"api_key": "K", "auth": {"style": "bearer"}})
    ok("认证：Bearer", h.get("Authorization") == "Bearer K", h.get("Authorization"))
    h = V.build_headers({"api_key": "K", "auth": {"style": "x-api-key"}})
    ok("认证：x-api-key", h.get("x-api-key") == "K")
    h = V.build_headers({"api_key": "K", "auth": {"style": "query", "param": "key"}})
    ok("认证：query 方式不塞请求头", "Authorization" not in h)
    ok("认证：query 方式放进 params", V.auth_params({"api_key": "K", "auth": {"style": "query", "param": "key"}}) == {"key": "K"})
    h = V.build_headers({"api_key": "K", "auth": {"style": "none"}})
    ok("认证：none 一个都不带", "Authorization" not in h and "x-api-key" not in h)

    # ---------- ④ 没实测过的预设默认拒绝 ----------
    unverified = {"name": "openai-video-x", "base_url": "https://api.openai.com", "api_key": "k", "model": "sora-x"}
    sp_openai = V.spec_for(unverified)
    ok("未实测的预设：被识别为未实测", sp_openai.get("verified") is False, sp_openai.get("kind"))
    ok_v, why_v = V.check_runnable(sp_openai)
    ok("未实测的预设：默认拒绝执行并说清怎么办", (ok_v is False) and "allow_unverified" in why_v, why_v[:60])
    ok_v2, _ = V.check_runnable(sp_openai, allow_unverified=True)
    ok("未实测的预设：显式放行后可以跑", ok_v2 is True)
    ok_v3, why3 = V.check_runnable({"base_url": "", "api_key": "k"})
    ok("没 base_url：明确拒绝", ok_v3 is False, why3[:30])
    ok_v4, why4 = V.check_runnable({"base_url": "https://x", "api_key": ""})
    ok("没 key：明确拒绝", ok_v4 is False, why4[:30])

    # ---------- ① 接一家从没听过的厂商：全程只写配置 ----------
    entry = {
        "name": "某家视频", "base_url": "https://api.vendor.example/v1",
        "api_key": "VK", "model": "vid-1",
        "video_api": {
            "kind": "custom",
            "create_path": "/v1/videos",
            "query_path": "/v1/tasks/{id}",
            "auth": {"style": "x-api-key", "header": "X-Key"},
            "create_body": {"resolution": "1080p"},
            "id_paths": ("data.task.id",),
            "status_paths": ("data.task.status",),
            "url_paths": ("data.task.result.video",),
            "progress_paths": ("data.task.percent",),
            "done": ("SUCCESS",), "failed": ("FAIL",),
            "poll_interval": 0, "queue_retry": 1,
        },
    }
    sp = V.spec_for(entry)
    ok("陌生厂商：声明说了算(不再猜域名)", sp.get("kind") == "custom" and sp.get("_source").startswith("配置里"))
    ok("陌生厂商：认得出自己没实测过吗", sp.get("verified") is not True)
    u, b, p = V.build_create(sp, "一只猫在窗台", seconds=6)
    ok("陌生厂商：建任务 URL 对", u == "https://api.vendor.example/v1/videos", u)
    ok("陌生厂商：把配置里的固定字段带上了", b.get("resolution") == "1080p")
    ok("陌生厂商：自己的参数也发得出去", b.get("prompt") == "一只猫在窗台" and b.get("seconds") == 6)
    ok("陌生厂商：model 字段自动带上", b.get("model") == "vid-1")
    qu, qp = V.build_query(sp, "T-7")
    ok("陌生厂商：查任务 URL 用 {id} 占位", qu == "https://api.vendor.example/v1/tasks/T-7", qu)
    hd = V.build_headers(sp)
    ok("陌生厂商：自定义认证头生效", hd.get("X-Key") == "VK", json.dumps(hd, ensure_ascii=False))

    # 全流程：建任务 → 轮询(先 pending 后 done) → 下载
    fake = FakeRequests(
        create=FakeResp(200, {"data": {"task": {"id": "T-7", "status": "RUNNING"}}}),
        query=[FakeResp(200, {"data": {"task": {"status": "RUNNING", "percent": 40}}}),
               FakeResp(200, {"data": {"task": {"status": "SUCCESS", "result": {"video": "https://cdn/v.mp4"}}}})],
    )
    real = with_fakes(fake)
    try:
        prog = []
        tmpd = os.path.join(ROOT, "logs", "_tmp_spec_test")
        os.makedirs(tmpd, exist_ok=True)
        out, vurl = V.generate(sp, "一只猫在窗台", seconds=6, timeout=30,
                               progress_cb=prog.append, download_dir=tmpd)
        ok("全流程：拿到本地文件", os.path.exists(out) and os.path.getsize(out) > 0, out)
        ok("全流程：远程地址取对了", vurl == "https://cdn/v.mp4", vurl)
        ok("全流程：进度回调收到了 40", 40 in prog, prog)
        ok("全流程：建任务只发一次", sum(1 for c in fake.calls if c["m"] == "POST") == 1)
        ok("全流程：轮询发到了对的 URL", any(c["url"] == "https://api.vendor.example/v1/tasks/T-7" for c in fake.calls))
        ok("全流程：POST 的 body 就是配置里那套",
           fake.calls[0]["json"].get("resolution") == "1080p" and fake.calls[0]["json"].get("prompt") == "一只猫在窗台")
        try:
            os.remove(out)
            os.rmdir(tmpd)
        except Exception:
            pass
    finally:
        restore(real)

    # ---------- ④ 取不到 id / 地址时：明确说该填哪个字段 ----------
    fake = FakeRequests(create=FakeResp(200, {"weird": "nope"}))
    real = with_fakes(fake)
    try:
        try:
            V.generate(sp, "x", timeout=5)
            ok("取不到任务 id：必须报错", False)
        except RuntimeError as e:
            ok("取不到任务 id：明确告诉用户改哪个字段", "id_paths" in str(e), str(e)[:60])
    finally:
        restore(real)

    # ---------- ② 队列满 / 限流要重试，参数错要当场报 ----------
    class Seq:
        def __init__(self, seq):
            self.seq = list(seq)
            self.n = 0

        def __call__(self, url, headers=None, json=None, params=None, timeout=None):
            r = self.seq[min(self.n, len(self.seq) - 1)]
            self.n += 1
            return r
    import time as _t
    real_sleep = _t.sleep
    _t.sleep = lambda s: None
    try:
        # 503 队列满 → 第二次成功
        fake2 = types.ModuleType("requests")
        fake2.calls = []
        post = Seq([FakeResp(503, {"code": "video_queue_full"}, "queue full"),
                    FakeResp(200, {"data": {"task": {"id": "T-1"}}})])
        fake2.post = lambda url, headers=None, json=None, params=None, timeout=None: post(url)
        fake2.get = lambda url, headers=None, params=None, timeout=None: FakeResp(
            200, {"data": {"task": {"status": "SUCCESS", "result": {"video": "https://cdn/a.mp4"}}}})
        real = with_fakes(fake2)
        try:
            tmpd = os.path.join(ROOT, "logs", "_tmp_spec_test2")
            os.makedirs(tmpd, exist_ok=True)
            out, _ = V.generate(sp, "x", timeout=10, download_dir=tmpd, queue_retry=2)
            ok("队列满：会重试到成功", os.path.exists(out))
            os.remove(out)
            os.rmdir(tmpd)
        except Exception as e:
            ok("队列满：会重试到成功", False, "%s: %s" % (type(e).__name__, e))
        finally:
            restore(real)
        # 400 参数错 → 立刻报出来，不许一直重试
        fake3 = types.ModuleType("requests")
        fake3.post = lambda url, headers=None, json=None, params=None, timeout=None: FakeResp(400, {"detail": "bad param"}, "bad param")
        fake3.get = lambda url, headers=None, params=None, timeout=None: FakeResp(200, {})
        real = with_fakes(fake3)
        try:
            try:
                V.generate(sp, "x", timeout=5)
                ok("参数错(400)：立刻报出来", False)
            except RuntimeError as e:
                ok("参数错(400)：立刻报出来", "建任务失败" in str(e), str(e)[:40])
        finally:
            restore(real)
    finally:
        _t.sleep = real_sleep

    # ---------- ⑤ Agnes：规矩只有一份（走 agenes.build_body） ----------
    ag = V.spec_for({"name": "agnes-2.5-flash", "base_url": "https://apihub.agnes-ai.com/v1",
                     "api_key": "k"})
    ok("Agnes：按域名认出预设", ag.get("kind") == "agnes")
    ok("Agnes：标着已实测", ag.get("verified") is True)
    ok("Agnes：视频模型名不是对话模型名", ag.get("model") == "agnes-video-2.5-flash", ag.get("model"))
    u, b, _p = V.build_create(ag, "一只猫", mode="ti2vid", seconds=99)
    ok("Agnes：建任务 URL 不带两个 /v1", u == "https://apihub.agnes-ai.com/v1/videos", u)
    ok("Agnes：老 mode 归一成 text", b.get("mode") == "text")
    ok("Agnes：seconds 超范围收到 12 且是字符串", b.get("seconds") == "12")
    ok("Agnes：size 固定 720P", b.get("size") == "720P")
    qu, qp = V.build_query(ag, "V1")
    ok("Agnes：查询端点在根上(不带 /v1)", qu == "https://apihub.agnes-ai.com/agnesapi", qu)
    ok("Agnes：查询必须带 model_name", qp.get("model_name") == "agnes-video-2.5-flash", json.dumps(qp))
    ok("Agnes：内部开关不进请求体", "create_retry" not in b and "poll_interval" not in b)

    # ---------- 给界面用的一句话说明 ----------
    d = V.describe(ag)
    ok("说明里写清了协议和「已实测」", "agnes" in d and "已实测" in d, d[:50])
    d2 = V.describe(sp)
    ok("自己写的配置也说得清来源", "配置里" in d2, d2[:60])

    # ---------- ⑥ 真起一个"没听说过的厂商"：只写配置，走真 HTTP 跑通 ----------
    # 这一节是这套测试的重点：用**真 sockets**（本机 http.server）证明"接任意厂商只需写配置"。
    # 它故意用一套不标准的形状：任务字段叫 uuid、状态叫 queued/running/ok、
    # 进度叫 pct、成片地址埋在 file.mp4 里、认证用 x-api-key。
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits = {"create": 0, "query": 0, "download": 0}

    class MockProvider(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, raw=None):
            body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/octet-stream" if raw else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/v1/videos":
                return self._send(404, {"detail": "no such path"})
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            hits["create"] += 1
            hits["auth"] = self.headers.get("X-Api-Key") or ""
            hits["body"] = payload
            return self._send(200, {"data": {"job": {"uuid": "J-1", "state": "queued"}}})

        def do_GET(self):
            if self.path.startswith("/v1/jobs/J-1"):
                hits["query"] += 1
                if hits["query"] < 2:
                    return self._send(200, {"data": {"job": {"state": "running", "pct": 55}}})
                return self._send(200, {"data": {"job": {
                    "state": "ok", "file": {"mp4": "http://127.0.0.1:%d/out.mp4" % self.server.server_port}}}})
            if self.path == "/out.mp4":
                hits["download"] += 1
                return self._send(200, raw=b"REAL-VIDEO-BYTES")
            return self._send(404, {"detail": "no such path"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockProvider)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    port = srv.server_port
    try:
        entry = {
            "name": "某家云视频", "base_url": "http://127.0.0.1:%d" % port,
            "api_key": "MOCK-KEY", "model": "vendor-video-3",
            "video_api": {
                "kind": "custom",
                "create_path": "/v1/videos",
                "create_body": {"resolution": "1080p", "duration": "6"},
                "query_path": "/v1/jobs/{id}",
                "auth": {"style": "x-api-key", "header": "X-Api-Key"},
                "id_paths": ("data.job.uuid",),
                "status_paths": ("data.job.state",),
                "url_paths": ("data.job.file.mp4",),
                "progress_paths": ("data.job.pct",),
                "done": ("ok",), "failed": ("dead",), "pending": ("queued", "running"),
                "poll_interval": 0, "queue_retry": 2,
            },
        }
        sp2 = V.spec_for(entry)
        prog = []
        tmpd = os.path.join(ROOT, "logs", "_tmp_any_provider")
        os.makedirs(tmpd, exist_ok=True)
        out, vurl = V.generate(sp2, "一只橘猫在窗台上看雨", timeout=30,
                               progress_cb=prog.append, download_dir=tmpd)
        ok("真 HTTP：没有改一行代码就接上了陌生厂商", os.path.exists(out) and os.path.getsize(out) == len(b"REAL-VIDEO-BYTES"),
           "%d 字节" % (os.path.getsize(out) if os.path.exists(out) else 0))
        ok("真 HTTP：成片地址取的是 file.mp4 那条", vurl.startswith("http://127.0.0.1:") and vurl.endswith("/out.mp4"), vurl)
        ok("真 HTTP：认证头按配置发过去了", hits.get("auth") == "MOCK-KEY", "收到的 X-Api-Key=%r" % hits.get("auth"))
        ok("真 HTTP：配置里的固定字段到了请求体", hits["body"].get("resolution") == "1080p" and hits["body"].get("duration") == "6")
        ok("真 HTTP：prompt 也发了", hits["body"].get("prompt") == "一只橘猫在窗台上看雨")
        ok("真 HTTP：进度读的是 pct 字段", 55 in prog, prog)
        ok("真 HTTP：不标准的 done 值(ok)也认得出", hits["query"] >= 2)
        try:
            os.remove(out)
            os.rmdir(tmpd)
        except Exception:
            pass
    finally:
        srv.shutdown()
        srv.server_close()

    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
