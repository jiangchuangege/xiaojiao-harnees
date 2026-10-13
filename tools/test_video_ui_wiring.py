# tools/test_video_ui_wiring.py —— 界面到后端的**接线**自测（离线，不真生成视频）
#
# 为什么专门测这个（2026-10-14 复现到的真缺口）：
#   界面上那个「🎬 生成视频」弹窗原来只发 {prompt, refined} —— 没有时长、没有台词。
#   后果就是用户最早问的两件事从界面上根本做不到：
#     · 「秒数…至少15s」：只能吃后端默认值，界面上没法选；
#     · 「他生成的视频都没有声音呢」：台词那一栏根本不存在，于是**从界面生成的视频永远是哑的**。
#   后端其实早就支持 seconds / narrate 了（`/api/video` 收、`_worker` 用），是**界面没接上**。
# 这套测试钉的就是这条线：界面发得出去、后端收得到、默认值也诚实。
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "video_service"))

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


def main():
    print("== 生成视频：界面 → 后端 接线自测 ==")
    import flask
    import video_api as va

    # ---- 后端：收得到、也记得住 ----
    app = flask.Flask("video_ui_test")
    app.register_blueprint(va.bp)
    c = app.test_client()
    started = []
    va._worker = lambda jid, prompt: started.append((jid, prompt))     # 不真跑，只看接线
    r = c.post("/api/video", json={"prompt": "一只橘猫坐在窗台上看雨", "seconds": 12,
                                   "narrate": "下雨天，小乔陪着你看窗外的灯光。"})
    d = r.get_json()
    ok("POST /api/video 返回 ok", r.status_code == 200 and d.get("ok"), json.dumps(d, ensure_ascii=False)[:80])
    ok("后端回报了这次的目标秒数", d.get("seconds") == 12, d.get("seconds"))
    job = va._jobs.get(d.get("job")) or {}
    ok("时长存进了任务", job.get("seconds") == 12, job.get("seconds"))
    ok("台词存进了任务", "听" in str(job.get("narrate")) or "雨" in str(job.get("narrate")), job.get("narrate"))
    ok("任务已交给 worker 线程", len(started) == 1, started[:1])

    # ---- 默认值：不填也要"至少 15 秒"（用户 2026-10-13 的原话）----
    r2 = c.post("/api/video", json={"prompt": "海边日落"})
    d2 = r2.get_json()
    ok("不填时长时默认 15 秒（用户要的「至少15s」）", d2.get("seconds") == 15, d2.get("seconds"))
    job2 = va._jobs.get(d2.get("job")) or {}
    ok("不填台词时为空（不会硬凑一句）", job2.get("narrate") == "", repr(job2.get("narrate")))

    # ---- 越界要有边界（别让界面把 9999 秒塞进来）----
    r3 = c.post("/api/video", json={"prompt": "测试", "seconds": 9999})
    ok("离谱的时长被夹到上限内", r3.get_json().get("seconds") <= 120, r3.get_json().get("seconds"))

    # ---- /api/video/mode 要如实回云端实况（界面据此显示接的是谁）----
    r4 = c.get("/api/video/mode")
    dd = r4.get_json()
    ok("mode 接口返回云端实况", isinstance(dd.get("cloud"), dict), json.dumps(dd.get("cloud"), ensure_ascii=False)[:80])
    for k in ("available", "runnable", "describe", "provider"):
        ok("云端实况里有 %s" % k, k in (dd.get("cloud") or {}))
    ok("云端说明不是写死某一家（写的是协议名）",
       "协议=" in str((dd.get("cloud") or {}).get("describe")), str((dd.get("cloud") or {}).get("describe"))[:40])

    # ---- 前端源码：这两栏真的发出去了么（界面是老式内联 JS，直接查源码最实在）----
    src = open(os.path.join(ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
    ok("界面 POST 里带上了 seconds 与 narrate",
       "seconds:secs" in src and "narrate:line" in src)
    ok("界面上有时长选择框", 'id="vsecs"' in src and "15 秒" in src)
    ok("界面上有台词输入框", 'id="vline"' in src)
    ok("界面上说清了「声音是载体配音」", "载体替他配音" in src)
    ok("界面不再写死「云端 Agnes API」", "云端 Agnes API（免费" not in src)
    ok("界面会显示接的是谁/实没实测", "window._vcloud" in src and "未实测" in src)

    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
