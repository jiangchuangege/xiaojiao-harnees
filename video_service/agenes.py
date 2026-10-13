# video_service/agenes.py —— Agnes 云端文生视频大脑(免费 API, 不占本地显存)
# 用法: XIAOJIAO_AGNES_KEY=<platform.agnes-ai.com 领取的 key>, 自动识别 agnes-video-2.5-flash
# 对接: 无 key 则不启用, 视频生成回落到本地 ComfyUI(Wan2.1)。
import os, time, datetime, requests, threading

BASE = "https://apihub.agnes-ai.com"
_DEFAULT_MODEL = "agnes-video-2.5-flash"

# 免费用户视频 = 1 RPM(每分钟1次请求)。用一个进程内锁 + 时间戳节流, 避免连续调用撞429。
_RPM_LOCK = threading.Lock()
_LAST_REQ = [0.0]   # 上次发请求的时间
_RPM_INTERVAL = 60  # 秒, 对应 1 RPM
# 建任务前的"准备"动作(可用于等待上一任务完成, 避免同 key 并行撞 RPM)
_pre_tasks = []

def _throttle():
    """确保两次 POST 之间至少间隔 RPM_INTERVAL 秒(1 RPM), 防止 429。"""
    with _RPM_LOCK:
        now = time.time()
        wait = _RPM_INTERVAL - (now - _LAST_REQ[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQ[0] = time.time()

def _key():
    # 环境变量 XIAOJIAO_AGNES_KEY 优先; 其次从 control 的 models 里找 agnes 系列读 api_key
    k = os.environ.get("XIAOJIAO_AGNES_KEY", "")
    if k:
        return k
    try:
        import json, os as _o
        root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        d = json.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        # 1) brain.agnese.key
        v = (d.get("brain", {}).get("agnese", {}).get("key")
             or d.get("brain", {}).get("video_agnese", {}).get("key"))
        if v:
            return v
        # 2) 遍历 models, 按优先级取第一个带 key 的:
        #    ① base_url 含 /videos(真视频端点) ② base_url 含 agnes ③ name 含 agnes/video
        cands = list(d.get("models") or [])
        def _pick(pred):
            for m in cands:
                if pred(m) and m.get("api_key"):
                    return m["api_key"]
            return ""
        v = _pick(lambda m: "videos" in (m.get("base_url") or "").lower())
        if v:
            return v
        v = _pick(lambda m: "agnes" in (m.get("base_url") or "").lower())
        if v:
            return v
        v = _pick(lambda m: ("agnes" in (m.get("name") or "").lower()
                             or "video" in (m.get("name") or "").lower()))
        if v:
            return v
        return ""
    except Exception:
        return ""

def available():
    """是否配置了 Agnes key。"""
    return bool(_key())

def model():
    try:
        import json, os as _o
        root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        d = json.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        # brain.agnese.model 优先
        v = (d.get("brain", {}).get("agnese", {}).get("model")
             or d.get("brain", {}).get("video_agnese", {}).get("model"))
        if v:
            return v
        # 从 models 找"视频"系列读 model 名。
        # ⚠️ 2026-10-13 实测教训: models[] 里那条 agnes-2.5-flash 是**对话模型**,
        #    拿它的名字去 /v1/videos 会 400「Model agnes-2.5-flash is a chat model」。
        #    所以这里必须卡"视频"字样, 只按 base_url 含 agnes 找 key 是可以的。
        for m in (d.get("models") or []):
            name = (m.get("name") or "").lower()
            url = (m.get("base_url") or "").lower()
            if "video" in name or "video" in url:
                return m.get("model") or _DEFAULT_MODEL
        return _DEFAULT_MODEL
    except Exception:
        return _DEFAULT_MODEL

def _cfg_retry():
    """云端队列满时重试几次(每次等 60 秒, 免费档 1 RPM)。

    缺省 5 次 ≈ 5 分钟。为什么不是 10: 队列满的时候干等太久, 用户那边看起来就是"卡住了";
    等不到就早点认输, 让上层回落到本地生成, 而不是一直假装在生成。
    想改成别的值: xiaojiao_control.json → {"video": {"cloud_retry": 10}}
    """
    try:
        import json, os as _o
        root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        d = json.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        v = int((d.get("video") or {}).get("cloud_retry") or 0)
        return v if v > 0 else 5
    except Exception:
        return 5


def build_body(prompt, mode="text", seconds=5, **extra):
    """拼 Agnes 的建任务请求体（**这一家的参数规矩只写在这里一份**）。

    通用适配器（`video_api_spec.py` 的 agnes 预设）也调这个函数 ——
    所以"官方那几个规矩"（mode 只认三种、seconds 是 4~12 的字符串、size 固定 720P）
    只有一份实现，不会这边改完那边没改。
    """
    _mode = str(mode or "text")
    if _mode not in ("text", "keyframe", "reference"):
        _mode = "text"                      # 老配置里的 ti2vid 之类一律归到 text，免得又 400
    body = {"model": model(), "prompt": prompt, "mode": _mode,
            "size": "720P", "aspect_ratio": "16:9"}
    try:                                    # seconds 必须是字符串，且只允许 4~12
        _sec = int(str(seconds or 5))
    except Exception:
        _sec = 5
    body["seconds"] = str(max(4, min(_sec, 12)))
    if extra:
        body.update(extra)
    return body


def query_params(video_id):
    """查任务要带的参数（文档：`video_id` + `model_name`；keyframe/reference 必须带后者）。"""
    return {"video_id": video_id, "model_name": model()}


def generate(prompt, mode="text", poll_interval=3, timeout=1800, progress_cb=None, **extra):
    """提交 Agnes 文生视频任务并轮询到完成, 返回 (本地视频路径, 远程URL)。

    【2026-10-13 按官方文档把参数改对了 —— 原来那份一发就 400：
        {"message":"invalid mode","data":{"param":"mode"}}】
      · `mode` 现在只认 **`text` / `keyframe` / `reference`**（原来写的 `ti2vid` 已废弃）；
      · `seconds` 必须是**字符串** `"4"`–`"12"`（默认 `"5"`）→ **单条最长 12 秒**；
      · `size` 固定 **`"720P"`**（别的值直接 400），画幅用 `aspect_ratio`（默认 `16:9`）；
      · 查询要带 `model_name`（`keyframe`/`reference` 模式**必须**带）；
      · 完成时视频地址在**顶层 `url`**。
      文档：https://agnes-ai.com/zh-Hans/docs/agnes-video-25-flash.md
      ⚠️ 免费档限流很严（实测 429：`rate limit for free users`），`_throttle()` 必须留着。
    """
    key = _key()
    if not key:
        raise RuntimeError("未配置 Agnes key(设 XIAOJIAO_AGNES_KEY 或 xiaojiao_control.json 的 brain.agnese.key)")
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    # ⚠️ 2026-10-13 踩过: 我们自己的内部开关(重试次数)混在 extra 里一起发给了服务器,
    #    服务器回 400 create_retry is not an allowed request field —— 先摘干净再发。
    try:
        attempts = int(extra.pop("create_retry", 0) or _cfg_retry())
    except Exception:
        attempts = _cfg_retry()
    body = build_body(prompt, mode=mode, seconds=extra.pop("seconds", 5), **extra)
    # 1. 创建任务
    #    ⚠️ 2026-10-13 实测: 免费档服务器队列经常满, 会返回
    #       503 {"code":"video_queue_full","message":"video queue is full, please retry later"}
    #    这不是参数错, 要一直重试; 429(限流)同理。400/401 之类才是配置错, 直接报出来。
    data, last = None, ""
    _throttle()   # 1 RPM 节流(≤1次/分钟)
    for attempt in range(1, max(1, attempts) + 1):
        # ⚠️ 2026-10-13 实测: 第 12 次排队时直接抛 ConnectionResetError(10054),
        #    旧代码没接住, 整个重试循环当场崩掉 —— 断线也是"再试一次", 不是"配置错"。
        try:
            r = requests.post(BASE + "/v1/videos", headers=headers, json=body, timeout=60)
        except Exception as e:
            last = "网络断了(%s: %s)" % (type(e).__name__, str(e)[:120])
            if progress_cb:
                progress_cb(-attempt)
            time.sleep(_RPM_INTERVAL)
            continue
        if r.status_code == 200:
            data = r.json()
            break
        last = "(%d) %s" % (r.status_code, r.text[:220])
        if r.status_code in (429, 500, 502, 503, 504):
            if progress_cb:
                progress_cb(-attempt)          # 负数 = 在排队重试, 不是进度
            time.sleep(_RPM_INTERVAL)          # 免费档 1 RPM, 等满一分钟再撞
            continue
        raise RuntimeError("Agnes 建任务失败" + last)
    if data is None:
        raise RuntimeError("Agnes 建任务一直排队没排上(重试 %d 次): %s" % (attempt, last))
    vid = data.get("video_id") or data.get("task_id") or data.get("id")
    if not vid:
        raise RuntimeError("Agnes 未返回任务ID: " + str(data)[:200])
    # 2. 轮询（带 model_name；文档说每 1~2 秒查一次就够）
    start = time.time()
    while time.time() - start < timeout:
        try:
            st = requests.get(BASE + "/agnesapi", headers=headers,
                              params=query_params(vid),
                              timeout=30).json()
        except Exception as e:
            st = {"status": "pending", "error": str(e)}
        s = st.get("status", "pending")
        if s == "completed":
            # 下载成片到本地
            out = os.path.join(_out_dir(), datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_agnese")
            vurl = st.get("url") or st.get("video_url") or ""
            if not vurl:
                raise RuntimeError("Agnes 完成但无 url")
            ext = os.path.splitext(vurl)[1] or ".mp4"
            out += ext
            vr = requests.get(vurl, timeout=120)
            vr.raise_for_status()
            with open(out, "wb") as f:
                f.write(vr.content)
            return out, vurl
        elif s == "failed":
            raise RuntimeError("Agnes 生成失败: " + str(st.get("error", ""))[:200])
        else:
            if progress_cb:
                progress_cb(int(st.get("progress", 0) or 0))
        time.sleep(poll_interval)
    raise TimeoutError("Agnes 生成超时")

def generate_long(prompt, seconds=15, per_clip=12, narrate=None, progress_cb=None,
                  chunk_prompts=None, **extra):
    """要 **15 秒或更长** 的云端片子: 一次最长 12 秒, 所以拆成几条生成再拼成一条。

    返回本地文件路径(拼好的那一条)。
      · seconds=15 → 两条: 12 秒 + 4 秒(API 最短 4 秒), 拼起来 16 秒, 不会少于 15;
      · narrate 给了台词就用系统中文语音念出来接上(载体配音, **不是**模型自己说话);
      · 免费档 1 RPM, 每多一条就多等一分钟起步, 这是限流的实话。
    """
    import math
    try:
        total = max(4, int(seconds))
    except Exception:
        total = 15
    per = max(4, min(int(per_clip), 12))
    n = max(1, int(math.ceil(total / float(per))))
    lens = [per] * (n - 1)
    lens.append(max(4, total - per * (n - 1)))     # 最后一条按余数, 但不少于 4 秒
    parts = []
    for i, sec in enumerate(lens):
        if chunk_prompts and i < len(chunk_prompts):
            p = chunk_prompts[i]
        elif n == 1:
            p = prompt
        else:
            p = prompt + "(第%d/%d段, 与上一段同一场景、同一主体, 镜头动作连贯不重复)" % (i + 1, n)
        path, _url = generate(p, mode=extra.pop("mode", "text"), seconds=str(sec),
                              progress_cb=progress_cb, **extra)
        parts.append(path)
    out = parts[0]
    if len(parts) > 1:
        from video_service import video_audio as _va  # 拼长轨用 ffmpeg, 与"接声音"同一套工具
        out = _va.concat(parts, out=os.path.join(_out_dir(), os.path.basename(parts[0]).replace("_agnese", "_agnese_long")))
    if narrate:
        from video_service import video_audio as _va
        out = _va.add_audio(out, text=narrate)
    return out

def _out_dir():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "videos")
    os.makedirs(d, exist_ok=True)
    return d
