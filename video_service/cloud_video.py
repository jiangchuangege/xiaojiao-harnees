# video_service/cloud_video.py —— 通用云端视频大脑适配器
# 不针对某一家: 按 base_url 特征自动识别视频 API 协议, 让"加了视频模型就能用"最大化。
# 已支持协议:
#   agnes      -> POST {base}/videos  + GET /agnesapi (Bearer, mode=ti2vid)
#   openai 类  -> 相关厂商若是 OpenAI 兼容 /v1/videos 或 /v1/generations, 按 OpenAI 视频格式
#   gemini 类  -> Gemini 视频生成原生端点
# 未知协议会给出"需接入"的明确提示。
import os, time, datetime, json, threading, requests

# ---------- 免费用户节流(1 RPM, 防止撞 429) ----------
_RPM_LOCK = threading.Lock()
_LAST_REQ = [0.0]
_RPM_INTERVAL = 60
def _throttle():
    with _RPM_LOCK:
        now = time.time()
        wait = _RPM_INTERVAL - (now - _LAST_REQ[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQ[0] = time.time()

def _load_control():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        return json.load(open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
    except Exception:
        return {}

def _video_models():
    """从控制文件 models 里挑出所有视频模型。

    判据（任一命中即算，2026-10-14 起）：
      · 条目里**自己声明了 `video_api`** —— 这是接任意厂商的正路（见 `video_api_spec.py`）；
      · base_url 含 videos / /video，或 name 含 video；
      · base_url / name 含 agnes —— Agnes 的视频端点和它的对话模型共用域名，靠 video 字样认不出来
        （2026-10-13 真踩过：认不出来就永远 available()=False，一直悄悄回落到本地）。
    """
    out = []
    for m in _load_control().get("models", []):
        name = (m.get("name") or "")
        url = (m.get("base_url") or "")
        low_url, low_name = url.lower(), name.lower()
        if (m.get("video_api") or "videos" in low_url or "/video" in low_url or "video" in low_name
                or "agnes" in low_url or "agnes" in low_name):
            out.append(m)
    return out

def _detect_provider(base_url, model_name):
    """按 base_url / model_name 特征猜协议(provider)。"""
    u = (base_url or "").lower()
    m = (model_name or "").lower()
    if "agnes" in u or "agnes" in m:
        return "agnes"
    if "generativelanguage" in u or "gemini" in u:
        return "gemini"
    if "openai" in u or "api.openai" in u:
        return "openai"
    if u.endswith("/v1") or "/v1/videos" in u or "videos" in u:
        return "openai"   # OpenAI 兼容视频
    return "unknown"

def _pick_video_model():
    """兼容老调用方：返回 (协议 kind, 模型名, api_key, base_url)；没有可用模型返回 None。

    ⚠️ 协议那一栏现在取自 `video_api_spec.spec_for()`（配置里声明的 video_api 说了算），
    不再是"按域名猜出来的厂商名"。新代码请直接用 `provider()` / `model()` / `spec()`。
    """
    m = _pick_video_model_entry()
    if not m:
        return None
    try:
        import sys as _sys
        if os.path.dirname(os.path.abspath(__file__)) not in _sys.path:
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        return (_spec_mod().spec_for(m).get("kind"), model(), m.get("api_key") or "",
                (m.get("base_url") or "").rstrip("/"))
    except Exception:
        return (_detect_provider(m.get("base_url"), m.get("model") or m.get("name")),
                model(), m.get("api_key") or "", (m.get("base_url") or "").rstrip("/"))

def available():
    """是否配置了任意视频模型(有 key)。"""
    return _pick_video_model_entry() is not None

def runnable():
    """这家现在**真能跑吗**：返回 (能不能, 为什么不能)。

    和 `available()` 的区别：`available()` 只说"配了个带 key 的模型"，
    这里连"协议实没实测过、base_url/key 齐不齐"一起判 —— 免得点了生成才发现跑不了。
    放行未实测预设的开关：控制文件 `video.allow_unverified: true`（默认不放过）。
    """
    m = _pick_video_model_entry()
    if not m:
        return False, "没有带 key 的云端视频模型"
    try:
        V = _spec_mod()
        sp = V.spec_for(m)
        allow = False
        try:
            import json as _j, os as _o
            root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
            d = _j.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
            allow = bool((d.get("video") or {}).get("allow_unverified"))
        except Exception as e:      # noqa: silent-ok — 读不到就当不放行
            LOG_ = None
        return V.check_runnable(sp, allow_unverified=allow)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])

def provider():
    """这家走的是什么协议（agnes / openai-video / custom …）。

    ⚠️ 2026-10-14 起这里返回的是**适配规格里那个 kind**，不再是"猜出来的厂商名"：
    用户那句「云端 Agnes 这个不一定是 agnes 要兼容任意的」就是冲这里来的 ——
    载体不该按域名判断"你是不是 Agnes"，而应该按**这个模型自己声明的协议**去说话。
    """
    m = _pick_video_model_entry()
    if not m:
        return None
    try:
        return _spec_mod().spec_for(m).get("kind")
    except Exception:
        return None

def _spec_mod():
    """拿到 video_api_spec.py（app 里是直接 import，包内自查是相对导入）。"""
    try:
        import video_api_spec as _v
        return _v
    except ImportError:
        from video_service import video_api_spec as _v
        return _v

def _pick_video_model_entry():
    """挑出第一个**带 key 的**视频模型条目（原样返回配置，不加工）。"""
    for m in _video_models():
        if m.get("api_key"):
            return m
    return None

def _agenes_mod():
    """拿到 agenes.py 模块。app 跑的时候 video_service 在 sys.path 里(直接 import agenes),
    我用 `python -c "from video_service import ..."` 自查时是包内导入 —— 两种都认。"""
    try:
        import agenes as _ag
        return _ag
    except ImportError:
        from video_service import agenes as _ag
        return _ag

def model():
    """这个视频模型**对外叫什么**（发给服务器的 model 字段）。

    Agnes 那条以 `agenes.py` 为准（默认 `agnes-video-2.5-flash`）—— 配置里那条
    `agnes-2.5-flash` 是**对话模型**的名字，拿它去 /v1/videos 会 400（2026-10-13 真踩过）。
    """
    m = _pick_video_model_entry()
    if not m:
        return None
    try:
        spec = _spec_mod().spec_for(m)
        return spec.get("model") or m.get("name")
    except Exception:
        return m.get("model") or m.get("name")

def spec():
    """当前这套云端视频的适配规格（给界面/日志看：协议、实没实测过、哪儿不确定）。"""
    m = _pick_video_model_entry()
    if not m:
        return None
    try:
        return _spec_mod().spec_for(m)
    except Exception:
        return None

def describe():
    """一句话说清"现在云端走的是谁、什么协议、靠不靠得住"。"""
    sp = spec()
    if not sp:
        return "没有可用的云端视频模型（模型管理里加一个带 key 的）"
    return _spec_mod().describe(sp)

def generate(prompt, mode=None, poll_interval=20, timeout=1800, progress_cb=None, **extra):
    """通用云端文生视频入口 —— **任何厂商都走同一套引擎**，返回 (本地路径, 远程URL)。

    这家叫什么名字、字段叫什么，全由它自己的 `video_api` 声明（见 `video_api_spec.py` 顶部）。
    `mode` 是历史参数（老代码传 ti2vid）：新引擎不认识就原样交给厂商的 param_builder，
    Agnes 那条会把它归一成 text（`agenes.build_body` 的规矩）。
    """
    m = _pick_video_model_entry()
    if not m:
        raise RuntimeError("未配置可用的视频模型（需要在模型管理里添加一个带 key 的视频模型）")
    V = _spec_mod()
    sp = V.spec_for(m)
    kw = dict(extra)
    if mode is not None:
        kw.setdefault("mode", mode)
    if poll_interval:
        kw.setdefault("poll_interval", min(float(poll_interval), float(sp.get("poll_interval") or 5)))
    return V.generate(sp, prompt, timeout=timeout, progress_cb=progress_cb, **kw)

# ---------- Agnes(⚠️ 已被上面的 agenes.py 委托取代, 保留只为对照旧参数, 不要再调用) ----------
def _gen_agnes(prompt, key, base, model, poll, timeout, cb, **extra):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    body = {"model": model, "prompt": prompt}
    body.update({"mode": extra.get("mode") or "ti2vid"})
    body.update(extra)
    _throttle()
    r = requests.post((base.rstrip("/") if not base.rstrip("/").endswith("/videos") else base.rstrip("/")) + "/videos"
                      if not base.rstrip("/").endswith("/videos") else base.rstrip("/"), headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        raise RuntimeError("视频建任务失败(%d): %s" % (r.status_code, r.text[:200]))
    data = r.json()
    vid = data.get("video_id") or data.get("task_id") or data.get("id")
    if not vid:
        raise RuntimeError("未返回任务ID: " + str(data)[:200])
    start = time.time()
    while time.time() - start < timeout:
        try:
            st = requests.get((base.rstrip("/").split("/videos")[0]) + "/agnesapi",
                              headers=headers, params={"video_id": vid}, timeout=30).json()
        except Exception as e:
            st = {"status": "pending", "error": str(e)}
        s = st.get("status", "pending")
        if s == "completed":
            return _download(st.get("video_url") or st.get("url") or "", "_agnese")
        elif s == "failed":
            raise RuntimeError("生成失败: " + str(st.get("error", ""))[:200])
        else:
            if cb: cb(int(st.get("progress", 0) or 0))
        time.sleep(poll)
    raise TimeoutError("视频生成超时")

# ---------- OpenAI 兼容视频(如部分厂商 /v1/videos, 用 POST + 轮询 /v1/videos/{id}) ----------
def _gen_openai(prompt, key, base, model, poll, timeout, cb, **extra):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    body = {"model": model, "prompt": prompt}
    body.update(extra)
    _throttle()
    # 尝试 /v1/videos 或 /v1/video/generations
    for ep in ["/v1/videos", "/v1/video/generations", "/v1/videos/generations"]:
        url = base.rstrip("/").split("/v1")[0] + ep if not base.rstrip("/").endswith("/v1") else base.rstrip("/") + ("/videos" if ep == "/v1/videos" else ep)
        try:
            r = requests.post(url, headers=headers, json=body, timeout=60)
            if r.status_code in (200, 201):
                data = r.json()
                vid = data.get("id") or data.get("video_id") or data.get("task_id") or (data.get("data") or [{}])[0].get("id")
                if not vid:
                    raise RuntimeError("未返回任务ID: " + str(data)[:200])
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        sr = requests.get(url + "/" + str(vid), headers=headers, timeout=30)
                        st = sr.json()
                    except Exception as e:
                        st = {"status": "pending", "error": str(e)}
                    status = (st.get("status") or "").lower()
                    vurl = st.get("url") or st.get("video_url") or ""
                    if status in ("completed", "succeeded") or vurl:
                        return _download(vurl, "_cloud")
                    elif status in ("failed", "error"):
                        raise RuntimeError("生成失败: " + str(st.get("error", ""))[:200])
                    else:
                        if cb: cb(0)
                    time.sleep(poll)
                raise TimeoutError("视频生成超时")
        except Exception as e:
            if "失败" in str(e):
                raise
            continue
    raise RuntimeError("OpenAI 兼容视频端点尝试失败")

# ---------- Gemini ----------
def _gen_gemini(prompt, key, base, model, poll, timeout, cb, **extra):
    raise RuntimeError("Gemini 视频适配暂未完整实现，请补充 endpoint 后接入")

# ---------- 下载 ----------
def _download(vurl, tag):
    if not vurl:
        raise RuntimeError("完成但无视频 URL")
    out = os.path.join(_out_dir(), datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + tag)
    ext = os.path.splitext(vurl)[1] or ".mp4"
    out += ext
    vr = requests.get(vurl, timeout=120)
    vr.raise_for_status()
    with open(out, "wb") as f:
        f.write(vr.content)
    return out, vurl

def _out_dir():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "videos")
    os.makedirs(d, exist_ok=True)
    return d

# 兼容旧引用
def _key():
    return _pick_video_model()[2] if _pick_video_model() else ""
