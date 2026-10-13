# tools/test_model_add_keeps_video_api.py —— 界面上改模型，**不许把手工写进配置的东西抹掉**
#
# 为什么专门测这个（2026-10-14 复现到的坑）：
#   `/api/model/add` 原来只认 5 个字段，然后**整条替换**同名条目 ——
#   于是"云视频那家的 video_api（协议适配规格）"这种手工写进配置的字段，
#   在界面上点一下保存就没了；而用户看到的现象是"接好的厂商突然不能用了"。
#   接任意厂商这件事（用户明确要的）就架在这种配置上，所以这条必须钉死。
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "video_service"))

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


def main():
    print("== 界面改模型：不许抹掉手工配置（离线自测） ==")
    import xiaojiao_app as X

    saved = {}
    X._save_control = lambda **kw: saved.update(kw)          # 绝不写真实控制文件
    store = {"models": [{
        "name": "某家云视频", "engine": "api", "base_url": "https://api.vendor.example",
        "api_key": "sk-hidden", "model": "vendor-video-3",
        "video_api": {"kind": "custom", "create_path": "/v1/videos", "id_paths": ["data.job.uuid"]},
    }]}
    X._get_models = lambda: [dict(m) for m in store["models"]]
    c = X.app.test_client()

    # ① 界面上只改了 base_url（常见操作）→ video_api 必须还在
    r = c.post("/api/model/add", json={"name": "某家云视频", "base_url": "https://api.vendor.example/v2",
                                       "api_key": "sk-hidden", "model": "vendor-video-3", "engine": "api"})
    ok("改模型返回 ok", r.status_code == 200 and r.get_json().get("ok"))
    m = saved.get("models", [{}])[0]
    ok("手工写的 video_api 没被抹掉", isinstance(m.get("video_api"), dict) and m["video_api"].get("kind") == "custom",
       json.dumps(m.get("video_api"), ensure_ascii=False)[:60])
    ok("id_paths 这种细字段也留住了", m.get("video_api", {}).get("id_paths") == ["data.job.uuid"])
    ok("改动的字段确实更新了", m.get("base_url") == "https://api.vendor.example/v2", m.get("base_url"))
    ok("没传的字段不会被写成空", m.get("engine") == "api")

    # ② 界面新增一条：只带 5 个字段也应能存
    store["models"].append({"name": "旧的", "engine": "api", "base_url": "https://x", "api_key": "k", "model": "m"})
    r = c.post("/api/model/add", json={"name": "新模型", "base_url": "https://y", "api_key": "k2", "model": "m2"})
    names = [x.get("name") for x in saved.get("models", [])]
    ok("新增模型照常加入", "新模型" in names and r.status_code == 200, names)

    # ③ 显式传空要把字段清掉（用户就是要清）—— 不许"合并"到清不掉
    r = c.post("/api/model/add", json={"name": "某家云视频", "base_url": "https://api.vendor.example/v2",
                                       "api_key": "", "model": "vendor-video-3"})
    m2 = next(x for x in saved.get("models", []) if x.get("name") == "某家云视频")
    ok("显式传空字符串 = 真的清掉", m2.get("api_key") == "", repr(m2.get("api_key")))

    # ④ 没有名字：明确报错（中文），不写盘
    saved.clear()
    r = c.post("/api/model/add", json={"name": "", "base_url": "https://z"})
    ok("没名字：明确拒绝且不写盘", r.status_code == 400 and not saved, r.status_code)

    # ⑤ 整条链路仍然认得这份配置：改成 video_api 后 cloud_video 依然能跑
    try:
        import cloud_video as cv
        cv._load_control = lambda: {"models": [{
            "name": "某家云视频", "base_url": "https://api.vendor.example", "api_key": "sk-1",
            "model": "vendor-video-3",
            "video_api": {"kind": "custom", "create_path": "/v1/videos", "query_path": "/v1/jobs/{id}"}}]}
        ok("配置存下来了，云端也就认得它", cv.available() is True and cv.runnable()[0] is True,
           cv.describe()[:50])
    except Exception as e:
        ok("配置存下来了，云端也就认得它", False, "%s: %s" % (type(e).__name__, e))

    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
