# tools/test_video_ui_wiring.py —— 界面到后端的**接线**自测（离线，不真生成视频）
#
# 为什么专门测这个（2026-10-14 复现到的真缺口）：
#   界面上那个「🎬 生成视频」弹窗原来只发 {prompt, refined} —— 没有时长、没有台词。
#   后果就是用户最早问的两件事从界面上根本做不到：
#     · 「秒数…至少15s」：只能吃后端默认值，界面上没法选；
#     · 「他生成的视频都没有声音呢」：台词那一栏根本不存在，于是**从界面生成的视频永远是哑的**。
#   后端其实早就支持 seconds / narrate 了（`/api/video` 收、`_worker` 用），是**界面没接上**。
# 这套测试钉的就是这条线：界面发得出去、后端收得到、默认值也诚实。
import os, sys, json, time

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

    # ---- 界面里能填/能验视频协议（2026-10-14 加）----
    import xiaojiao_app as X
    c2 = X.app.test_client()
    X._get_models = lambda: [{"name": "某家云视频", "base_url": "https://api.vendor.example",
                              "api_key": "sk-1", "model": "v3",
                              "video_api": {"kind": "custom", "create_path": "/v1/videos",
                                            "query_path": "/v1/jobs/{id}", "id_paths": ["data.job.uuid"]}}]
    r5 = c2.get("/api/model/videoapi?name=某家云视频").get_json()
    ok("能读回已保存的视频协议", r5.get("ok") and isinstance(r5.get("video_api"), dict), str(r5)[:70])
    r6 = c2.get("/api/model/videoapi?name=不存在的").get_json()
    ok("没有这个模型时如实回 null（不编默认值）", r6.get("video_api") is None and r6.get("ok") is False)
    r7 = c2.post("/api/video/provider/test", json={"name": "某家云视频"}).get_json()
    ok("自检：拿已保存的协议拼出请求", r7.get("ok") is True and r7.get("kind") == "custom", str(r7)[:70])
    ok("自检：告诉用户请求会发到哪",
       str(r7.get("create_url") or "").startswith("https://api.vendor.example"), r7.get("create_url"))
    ok("自检：查任务 URL 也拼得出来", "jobs/" in str(r7.get("query_url") or ""), r7.get("query_url"))
    r8 = c2.post("/api/video/provider/test",
                 json={"name": "手填的", "base_url": "https://api.x.com/v1", "api_key": "k", "model": "m",
                       "video_api": {"kind": "custom", "create_path": "/v1/videos",
                                     "query_path": "/v1/tasks/{id}"}}).get_json()
    ok("自检：手填的协议也能验（不受未实测拦截）", r8.get("ok") is True, str(r8)[:60])
    r9 = c2.post("/api/video/provider/test", json={"name": "没配的", "video_api": {"kind": "custom"}}).get_json()
    ok("自检：缺 base_url 时明确说跑不了", r9.get("ok") is False and "base_url" in str(r9.get("why")), r9.get("why"))
    ok("界面上有协议折叠框与三个按钮",
       'id="s_m_vapi"' in src and "checkVideoApi()" in src and "loadVideoApi()" in src)
    ok("界面会拦住非法 JSON（不许把坏 JSON 存进去）", "不是合法 JSON" in src)

    # ---- 弹窗排版：引擎与时长不许再挤在一行（2026-10-14 截图里被挤到弹窗外面那件事）----
    blk = src[src.index('id="videoBg"'): src.index('id="addLocalBg"')]
    head = blk.split('id="vq"')[0]
    ok("视频弹窗上半部分不再用横向 flex（挤爆的根因）", "display:flex" not in head)
    ok("引擎与时长各自成行、宽度撑满", head.count("width:100%") >= 2 and
       'id="vengine"' in head and 'id="vsecs"' in head)
    ok("状态说明放在它自己那一行（可换行，不再被压成竖字）",
       'id="vmodeH"' in head and "word-break:break-word" in head)

    # ---- 显存让位：本地视频在跑时，不许把聊天模型装回显存（2026-10-14 实测慢 3 倍的那个坑）----
    va._jobs.clear()
    ok("没有视频任务时：不算占用", va.video_busy() is False)
    va._jobs["g"] = {"state": "generating", "ts": time.time()}
    ok("视频生成中：算占用", va.video_busy() is True)
    ok("视频在跑时：看门狗不去拉大脑（源码里那道门在）",
       "_video_holds_vram()" in src and "_video_holds_vram" in src)
    ok("视频在跑时：内部调用不装大脑", "显存正让给本地视频生成" in src)
    va._jobs["g"] = {"state": "done", "ts": time.time()}
    ok("视频做完：占用解除", va.video_busy() is False)
    va._jobs.clear()

    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
