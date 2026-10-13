# tools/test_cloud_video_worker.py —— 走**主程序自己那条云端路径**接一家陌生厂商（离线、本机 HTTP）
#
# 与 test_cloud_video_spec.py 的分工：那边测引擎本身，这边测**接线**——
#   `video_api._worker()` 在云端模式下，会不会真的把任务交给云端、把进度/说明写进任务记录、
#   最后把成片地址落成 `/videos/xxx.mp4`。
# 用一家"形状很怪"的本机假厂商（任务字段 uuid、状态 ok/dead、进度 pct），
# 证明"接任意厂商只要写配置"这条在**程序里**也成立。
import os, sys, json, time, types, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "video_service"))

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


def main():
    print("== 主程序云端路径 · 接任意厂商（离线自测） ==")
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits = {"create": 0, "query": 0, "auth": "", "body": {}}

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
            n = int(self.headers.get("Content-Length") or 0)
            hits["body"] = json.loads(self.rfile.read(n) or b"{}")
            hits["auth"] = self.headers.get("X-Api-Key") or ""
            hits["create"] += 1
            return self._send(200, {"result": {"task": {"uuid": "JOB-9", "state": "queued"}}})

        def do_GET(self):
            if self.path.startswith("/jobs/JOB-9"):
                hits["query"] += 1
                if hits["query"] < 2:
                    return self._send(200, {"result": {"task": {"state": "running", "pct": 30}}})
                return self._send(200, {"result": {"task": {
                    "state": "ok", "video": "http://127.0.0.1:%d/final.mp4" % self.server.server_port}}})
            if self.path == "/final.mp4":
                return self._send(200, raw=b"FAKE-MP4-BYTES")
            return self._send(404, {"detail": "no"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port
    try:
        os.environ["XIAOJIAO_VIDEO_MODE"] = "api"       # 强制走云端分支
        import cloud_video as cv
        import video_api as va

        mock_entry = {
            "name": "某家云视频", "base_url": "http://127.0.0.1:%d" % port,
            "api_key": "MOCK-KEY", "model": "vendor-video-3",
            "video_api": {
                "kind": "custom", "create_path": "/v1/videos", "query_path": "/jobs/{id}",
                "auth": {"style": "x-api-key", "header": "X-Api-Key"},
                "create_body": {"resolution": "540p"},
                "id_paths": ("result.task.uuid",), "status_paths": ("result.task.state",),
                "url_paths": ("result.task.video",), "progress_paths": ("result.task.pct",),
                "done": ("ok",), "failed": ("dead",), "pending": ("queued", "running"),
                "poll_interval": 0, "queue_retry": 2,
            },
        }
        cv._load_control = lambda: {"models": [mock_entry]}      # 只替换"读配置"这一层
        ok("云端可用：认得出这个模型", cv.available() is True)
        ok("云端可跑：自己写的协议不受'未实测'限制", cv.runnable()[0] is True, cv.runnable()[1])
        ok("云端说明：如实写出协议来源", "配置里" in cv.describe(), cv.describe()[:60])

        jid = "test-cloud-worker"
        va._jobs[jid] = {"state": "queued", "prompt": "一只猫", "message": "排队中",
                         "ts": time.time(), "seconds": 5, "narrate": ""}
        out_dir = os.path.join(ROOT, "videos")
        before = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
        va._worker(jid, "一只猫坐在窗台上看雨")
        j = va._jobs.get(jid) or {}
        ok("worker：任务跑到了 done", j.get("state") == "done", "%s / %s" % (j.get("state"), j.get("message")))
        ok("worker：给出 /videos/ 的成片地址", str(j.get("url") or "").startswith("/videos/"), j.get("url"))
        ok("worker：云端说明写进了任务", "云端" in str(j.get("message") or ""), j.get("message"))
        f = os.path.join(out_dir, os.path.basename(str(j.get("url") or "")))
        ok("worker：成片真的落盘了", os.path.exists(f) and os.path.getsize(f) == len(b"FAKE-MP4-BYTES"),
           os.path.getsize(f) if os.path.exists(f) else "没这个文件")
        ok("worker：建任务带上配置里的固定字段", hits["body"].get("resolution") == "540p")
        ok("worker：认证头按配置发", hits["auth"] == "MOCK-KEY", hits["auth"])
        ok("worker：没有偷偷走本地（本地会去动 ComfyUI）", hits["create"] == 1 and not j.get("error"))
        # 清掉这一单的产物（只删自己刚写的那一个文件）
        try:
            if os.path.exists(f):
                os.remove(f)
            after = set(os.listdir(out_dir))
            for extra_f in (after - before):
                p = os.path.join(out_dir, extra_f)
                if os.path.isfile(p):
                    os.remove(p)
        except Exception as e:
            print("  （清理测试产物时忽略：%s）" % e)
    finally:
        srv.shutdown()
        srv.server_close()
        os.environ.pop("XIAOJIAO_VIDEO_MODE", None)

    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
