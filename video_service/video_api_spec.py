# video_service/video_api_spec.py —— **任意云端视频 API** 的通用适配引擎
#
# 【为什么要这个文件】2026-10-14 用户说的原话：
#   「云端 Agnes 这个不一定是 agnes 要兼容任意的」。
#   之前那份 `cloud_video.py` 是按"猜域名"分发的：认得出 agnes 就走 Agnes 那一套写死的参数，
#   认不出就说"暂未支持的协议"。等于**把某一家的规矩写进了载体** ——
#   换一家（可灵、海螺、万相、Veo、Replicate…）就得改代码，这不是载体的做法。
#
# 现在改成**配置驱动**：接一家新厂商 = 在控制文件里给这个模型写一块 `video_api`，**不用改代码**。
# 引擎只做三件通用的事：① 按模板发建任务请求 ② 按 JSON 路径轮询状态 ③ 取回成片。
#
# ── 一个模型的 `video_api` 可以写这些（全部可选，缺的用默认/预设）──────────────
#   kind          : agnes / openai-video / custom   （预设名；custom 就全靠下面这些字段）
#   create_path   : 建任务路径，可带 {model} 占位     默认按 kind
#   query_path    : 查任务路径，可带 {id} {model}     默认按 kind
#   create_body   : 建任务请求体里**额外**的固定字段（如 {"resolution":"1080p"}）
#   auth          : {style: bearer|x-api-key|query|header|none, header, scheme, param}
#   headers       : 额外的固定请求头
#   id_paths      : 从建任务响应里取任务 id 的候选路径（按顺序试）
#   status_paths  : 取状态字段的候选路径
#   url_paths     : 取成片地址的候选路径
#   progress_paths: 取进度(0~100)的候选路径
#   error_paths   : 取错误信息的候选路径
#   done / failed / pending : 状态值的字面量（不区分大小写；"成功/失败/进行中"也认）
#   result_kind   : url(默认) / base64 —— 有的厂商直接回一段 base64
#   poll_interval / queue_retry : 轮询间隔、队列满时的重试次数
#   verified      : 自己声明"这套字段我实测过"。false 的预设**默认拒绝执行**，
#                   要显式 allow_unverified=true 才跑（免得拿没验过的协议去烧用户的钱）。
#
# ⚠️ 诚实标注：下面 `PRESETS` 里只有 `agnes` 标了 verified=True（2026-10-13 按官方文档实测过：
#   参数、轮询、成片地址都真调通了，只是免费档排队一直满）。`openai-video` 按官方文档的形状写，
#   本机**没有**对应的 key，没法实测，所以标 False；其他厂商一律不给预设 ——
#   我不知道它们的字段名就不编，谁接谁按上面的字段单子填 `video_api`，填完就能用。
import os, json, time, base64, datetime

# 状态词的字面量（不区分大小写）。多写几种是因为各家叫法确实不一样。
_DONE = ("completed", "complete", "succeeded", "success", "done", "finished", "ready", "成功", "已完成", "完成")
_FAILED = ("failed", "fail", "error", "canceled", "cancelled", "rejected", "失败", "已失败", "错误", "取消")
_PENDING = ("pending", "processing", "queued", "queueing", "running", "in_progress", "inprogress",
            "created", "submitted", "waiting", "进行中", "排队", "处理中", "生成中")

# 建任务时**绝不发**的内部字段（我们自己的开关，发出去会被服务器判 400）
_INTERNAL_KEYS = ("create_retry", "poll_interval", "timeout", "progress_cb", "queue_retry",
                  "allow_unverified", "spec", "download")

PRESETS = {
    # ---- Agnes：2026-10-13 照官方文档实测过（参数/轮询/成片地址都真调通）----
    "agnes": {
        "verified": True,
        "create_path": "/v1/videos",
        "query_path": "/agnesapi",
        # 查询端点在**根**上（文档：https://apihub.agnes-ai.com/agnesapi?...），不带 base_url 里的 /v1
        "query_base": "origin",
        "auth": {"style": "bearer"},
        "id_paths": ("video_id", "id", "task_id"),
        "status_paths": ("status",),
        "url_paths": ("url", "video_url"),
        "progress_paths": ("progress",),
        "error_paths": ("error", "message"),
        "query_params": {"video_id": "{id}", "model_name": "{model}"},
        "queue_retry": 5,
        "poll_interval": 3,
        "param_builder": "agenes",     # ← 参数规矩交给 agenes.py（那边一份，别抄两遍）
        "note": "seconds 只收 4~12 的字符串、size 固定 720P、mode 只认 text/keyframe/reference",
    },
    # ---- OpenAI 官方 Videos API 的形状（文档形状；本机没 key，**未实测**）----
    "openai-video": {
        "verified": False,
        "create_path": "/v1/videos",
        "query_path": "/v1/videos/{id}",
        "auth": {"style": "bearer"},
        "create_body": {"model": "{model}"},
        "id_paths": ("id", "video_id", "task_id", "data.0.id", "data.id"),
        "status_paths": ("status", "data.status", "state"),
        "url_paths": ("url", "video_url", "output.url", "data.url", "data.0.url"),
        "progress_paths": ("progress", "data.progress"),
        "error_paths": ("error", "error.message", "detail", "message"),
        "poll_interval": 10,
        "queue_retry": 3,
        "note": "OpenAI 兼容视频端点常见形状；换厂商先把 id/status/url 三个路径按它的返回对一遍",
    },
}


def spec_for(model_entry):
    """把一个模型配置条目变成一个**可执行的适配规格**。

    优先级：① 条目里显式写的 `video_api`（最全，接新厂商走这条）
            ② `video_api.kind` 或域名/名字能认出的预设
            ③ 兜底成 openai-video 预设（并且**如实标出"这是猜的、未实测"**）
    返回的 dict 里带 `_source`（这份规格哪来的）与 `_warnings`（不确定的地方），
    调用方（和界面）据此如实告诉用户"这家是实测过的、还是猜的"。
    """
    m = dict(model_entry or {})
    base = (m.get("base_url") or "").rstrip("/")
    name = str(m.get("name") or "")
    model_name = m.get("model") or name
    declared = m.get("video_api") or {}
    if not isinstance(declared, dict):
        declared = {}
    kind = str(declared.get("kind") or "").strip().lower()
    warnings = []
    if kind and kind in PRESETS:
        spec = dict(PRESETS[kind])
        spec["kind"] = kind
        spec["_source"] = "预设 %s" % kind
    elif declared:
        spec = {"kind": "custom", "_source": "配置里自己写的 video_api"}
    else:
        # 没有任何声明：按域名/名字猜一个预设，猜不出就当 OpenAI 兼容形状，并如实标注
        low = (base + " " + name).lower()
        if "agnes" in low:
            spec = dict(PRESETS["agnes"]); spec["kind"] = "agnes"
            spec["_source"] = "按域名猜是 Agnes"
        elif "generativelanguage" in low or "gemini" in low or "veo" in low:
            # Gemini/Veo 的字段我没实测过，也**不编**：给个骨架 + 明确警告
            spec = {"kind": "custom", "_source": "看起来是 Gemini/Veo，但字段未实测"}
            warnings.append("这家（Gemini/Veo）的建任务/轮询字段本机没实测过，请在 video_api 里按它的文档填")
        else:
            spec = dict(PRESETS["openai-video"]); spec["kind"] = "openai-video"
            spec["_source"] = "没声明协议 → 按 OpenAI 兼容视频形状试（未实测）"
            warnings.append("这家没有声明 video_api，我按 OpenAI 兼容形状试；对不上就请按返回填 id/status/url 三个路径")
    # 声明里写的东西**覆盖**预设（接新厂商时通常只需要写两三个字段）
    for k, v in declared.items():
        if k == "kind":
            continue
        spec[k] = v
    spec.setdefault("_warnings", [])
    spec["_warnings"] = list(spec.get("_warnings") or []) + warnings
    spec["base_url"] = base
    spec["api_key"] = m.get("api_key") or ""
    spec["model"] = model_name
    # ⚠️ Agnes 那家的"视频模型名"必须问 `agenes.py`（默认 agnes-video-2.5-flash）：
    #    配置里那条 `agnes-2.5-flash` 是**对话模型**的名字，拿去建任务会 400
    #    「Model agnes-2.5-flash is a chat model」（2026-10-13 真踩过）。查询参数也要用同一个名字。
    if spec.get("param_builder") == "agenes":
        try:
            import agenes as _ag            # app 里 video_service 在 sys.path 上
        except ImportError:
            from video_service import agenes as _ag
        try:
            spec["model"] = _ag.model()
        except Exception:      # noqa: silent-ok — 读不到就退回配置里的名字
            pass
    spec.setdefault("create_path", "/v1/videos")
    spec.setdefault("query_path", "/v1/videos/{id}")
    spec.setdefault("auth", {"style": "bearer"})
    spec.setdefault("id_paths", ("id", "video_id", "task_id"))
    spec.setdefault("status_paths", ("status", "state"))
    spec.setdefault("url_paths", ("url", "video_url", "output.url", "data.url"))
    spec.setdefault("progress_paths", ("progress",))
    spec.setdefault("error_paths", ("error", "message", "detail"))
    spec.setdefault("poll_interval", 5)
    spec.setdefault("queue_retry", 3)
    spec.setdefault("result_kind", "url")
    return spec


def json_path(data, path, default=None):
    """按 `a.b.0.c` 这种路径取值（列表用下标）。取不到就返回 default —— 不抛。

    【为什么要它】各家返回的嵌套差得很远：`{"status":...}`、`{"data":{"status":...}}`、
    `{"data":[{"status":...}]}` 都见过。写死一种就等于只支持一家。
    """
    cur = data
    for part in str(path or "").split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                return default
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except Exception:
                return default
        else:
            return default
    return cur if cur is not None else default


def first_path(data, paths, default=None):
    """按候选路径顺序取第一个非空值。"""
    for p in paths or ():
        v = json_path(data, p)
        if v not in (None, "", [], {}):
            return v
    return default


def status_of(spec, data):
    """把响应里的状态归一成 done / failed / pending（认不出来的**算 pending**，不当成功）。"""
    raw = first_path(data, spec.get("status_paths") or (), "")
    s = str(raw or "").strip().lower()
    if not s:
        return "pending", raw
    for w in spec.get("done") or _DONE:
        if str(w).lower() == s:
            return "done", raw
    for w in spec.get("failed") or _FAILED:
        if str(w).lower() == s:
            return "failed", raw
    for w in spec.get("pending") or _PENDING:
        if str(w).lower() == s:
            return "pending", raw
    # 认不出来的状态：按"还没好"处理（宁可多等一会，也不把半成品当成品）
    return "pending", raw


def build_headers(spec, extra=None):
    """按 spec 组装请求头（认证方式各家不同：Bearer / x-api-key / 自定义头 / 不认证）。"""
    h = {"Content-Type": "application/json"}
    auth = spec.get("auth") or {}
    style = str(auth.get("style") or "bearer").lower()
    key = spec.get("api_key") or ""
    if key and style != "none":
        if style == "bearer":
            h[auth.get("header") or "Authorization"] = "%s %s" % (auth.get("scheme") or "Bearer", key)
        elif style == "x-api-key":
            h[auth.get("header") or "x-api-key"] = key
        elif style == "header":
            h[auth.get("header") or "Authorization"] = key
        # style == "query" 的 key 由调用方放进 params（见 auth_params）
    for k, v in (spec.get("headers") or {}).items():
        h[str(k)] = str(v)
    for k, v in (extra or {}).items():
        h[str(k)] = str(v)
    return h


def auth_params(spec):
    """认证要放进 query 的那种（?key=...）。"""
    auth = spec.get("auth") or {}
    if str(auth.get("style") or "").lower() == "query" and spec.get("api_key"):
        return {auth.get("param") or "key": spec["api_key"]}
    return {}


def _origin(url):
    """取 url 的 scheme://host（Agnes 的查询端点就在根上：`/agnesapi`，不带 /v1）。"""
    try:
        from urllib.parse import urlsplit
        s = urlsplit(str(url or ""))
        return "%s://%s" % (s.scheme, s.netloc) if s.scheme and s.netloc else str(url or "")
    except Exception:      # noqa: silent-ok — 拆不出来就原样返回
        return str(url or "")


def _join(base, path):
    """把 base 和 path 拼起来，**避免把 /v1 写两遍**。

    ⚠️ 2026-10-14 实测踩到：base_url 是 `https://apihub.agnes-ai.com/v1`，
    预设里写 `create_path=/v1/videos`，直接相加就成了 `/v1/v1/videos`（404）。
    各家给的 base_url 有的带 /v1 有的不带，所以这里统一处理：重复的前缀只留一个。
    """
    b = str(base or "").rstrip("/")
    p = "/" + str(path or "").lstrip("/")
    if not b:
        return p
    from urllib.parse import urlsplit
    s = urlsplit(b)
    bpath = (s.path or "").rstrip("/")
    # 把 base 路径里的每一段与 path 的前缀做重叠消除（只处理完全相同的整段）
    bsegs = [x for x in bpath.split("/") if x]
    psegs = [x for x in p.split("/") if x]
    while bsegs and psegs and bsegs[-1] == psegs[0]:
        # base 结尾那一段和 path 开头那一段一样（比如都是 v1）→ 只留一个
        psegs.pop(0)
    root = "%s://%s" % (s.scheme, s.netloc) if s.scheme and s.netloc else ""
    if not root:                      # base 不是完整 URL 时按纯字符串拼
        return b + p
    return root + "/" + "/".join(bsegs + psegs)


def _fill(text, spec, vid=""):
    """把路径/参数里的 {id} {model} {base} 占位换掉。"""
    return (str(text).replace("{id}", str(vid))
                   .replace("{model}", str(spec.get("model") or ""))
                   .replace("{base}", str(spec.get("base_url") or "")))


def _base_for(spec, which):
    """建任务/查任务分别用哪个 base（`query_base="origin"` = 只用域名，不带 /v1）。"""
    key = "query_base" if which == "query" else "create_base"
    base = spec.get(key)
    if not base:
        base = spec.get("base_url")
    if str(base).strip().lower() == "origin":
        base = _origin(spec.get("base_url"))
    return base


def build_create(spec, prompt, **kw):
    """拼建任务请求：URL、body、（query 认证时的）params。

    `param_builder="agenes"` 时，body 交给 `agenes.build_body()` —— 那一家的参数规矩只有一份。
    """
    url = _fill(spec.get("create_path") or "/v1/videos", spec)
    if not str(url).lower().startswith("http"):
        url = _join(_base_for(spec, "create"), url)
    body = {}
    for k, v in (spec.get("create_body") or {}).items():
        body[str(k)] = _fill(v, spec) if isinstance(v, str) else v
    builder = spec.get("param_builder")
    if builder == "agenes":
        import agenes as _ag            # ← app 里 video_service 在 sys.path 上
        body.update(_ag.build_body(prompt, mode=kw.get("mode") or "text",
                                   seconds=kw.get("seconds", 5),
                                   **{k: v for k, v in kw.items()
                                      if k not in ("mode", "seconds") and k not in _INTERNAL_KEYS}))
    else:
        body.setdefault("prompt", prompt)
        if spec.get("model") and "model" not in body:
            body["model"] = spec["model"]
        for k, v in kw.items():
            if k in _INTERNAL_KEYS or v is None:
                continue
            body[str(k)] = v
    params = dict(auth_params(spec))
    return url, body, params


def build_query(spec, vid):
    """拼查任务请求：URL、params。"""
    url = _fill(spec.get("query_path") or "/v1/videos/{id}", spec, vid)
    if not str(url).lower().startswith("http"):
        url = _join(_base_for(spec, "query"), url)
    params = dict(auth_params(spec))
    for k, v in (spec.get("query_params") or {}).items():
        params[str(k)] = _fill(v, spec, vid)
    return url, params


def check_runnable(spec, allow_unverified=False):
    """这家能不能跑。**未实测的预设默认拒绝**（并说清怎么放行）。

    理由很直接：拿没验过的协议去跑，用户花的是自己的钱和时间，
    报错时还看不出是"协议不对"还是"服务不行"。
    """
    if not spec.get("base_url"):
        return False, "这个模型没有 base_url，没法发请求"
    if not spec.get("api_key"):
        return False, "这个模型没有 api_key（模型管理里补一个）"
    if not spec.get("verified") and not allow_unverified and spec.get("kind") in PRESETS:
        return False, ("这家用的预设 %s **本机没实测过**。确认字段对得上就加 allow_unverified=true，"
                       "或者直接在模型的 video_api 里按它的返回填 id/status/url 三个路径" % spec.get("kind"))
    return True, ""


def generate(spec, prompt, timeout=1800, progress_cb=None, download_dir=None, **kw):
    """按 spec 跑完一条：建任务 → 轮询 → 下载。返回 (本地路径, 远程URL)。

    【两条硬规矩】
      · 状态认不出来一律当"还没好"，**绝不**把半成品当成品交出去；
      · 队列满 / 限流 / 断线属于"再试一次"，参数错(400/401)才当场报出来 —— 两种代价不对等。
    """
    import requests
    ok, why = check_runnable(spec, allow_unverified=kw.pop("allow_unverified", False))
    if not ok:
        raise RuntimeError(why)
    headers = build_headers(spec, kw.pop("headers", None))
    url, body, params = build_create(spec, prompt, **kw)
    queue_retry = int(kw.get("queue_retry") or spec.get("queue_retry") or 3)
    poll_interval = float(kw.get("poll_interval") or spec.get("poll_interval") or 5)
    # 1) 建任务（队列满/限流/断线都重试）
    data, last = None, ""
    sleep_s = float(spec.get("queue_wait") or 60)
    for attempt in range(1, max(1, queue_retry) + 1):
        try:
            r = requests.post(url, headers=headers, json=body, params=params or None, timeout=60)
        except Exception as e:
            last = "网络断了（%s: %s）" % (type(e).__name__, str(e)[:120])
            if progress_cb:
                progress_cb(-attempt)
            time.sleep(sleep_s)
            continue
        if r.status_code in (200, 201, 202):
            try:
                data = r.json()
            except Exception:
                raise RuntimeError("建任务返回的不是 JSON：%s" % r.text[:200])
            break
        last = "(%d) %s" % (r.status_code, r.text[:220])
        if r.status_code in (408, 425, 429, 500, 502, 503, 504):
            if progress_cb:
                progress_cb(-attempt)          # 负数 = 在排队重试，不是进度
            time.sleep(sleep_s)
            continue
        raise RuntimeError("建任务失败" + last)
    if data is None:
        raise RuntimeError("建任务一直没排上（重试 %d 次）：%s" % (queue_retry, last))
    vid = first_path(data, spec.get("id_paths") or ())
    if not vid:
        raise RuntimeError("建任务成功但取不到任务 id（返回：%s）。"
                           "请在 video_api.id_paths 里加上它的 id 字段路径" % str(data)[:200])
    # 2) 轮询
    qurl, qparams = build_query(spec, vid)
    start = time.time()
    while time.time() - start < timeout:
        try:
            st = requests.get(qurl, headers=headers, params=qparams or None, timeout=30).json()
        except Exception as e:
            st = {"_net_error": str(e)}
        state, raw_state = status_of(spec, st)
        if state == "done":
            vurl = first_path(st, spec.get("url_paths") or (), "")
            kind = str(spec.get("result_kind") or "url").lower()
            if kind == "base64":
                return _save_b64(first_path(st, spec.get("url_paths") or (), ""), spec, download_dir)
            if not vurl:
                raise RuntimeError("任务完成了但取不到成片地址（返回：%s）。"
                                   "请在 video_api.url_paths 里加上它的地址字段路径" % str(st)[:200])
            return download(vurl, download_dir), vurl
        if state == "failed":
            err = first_path(st, spec.get("error_paths") or (), "") or raw_state
            raise RuntimeError("生成失败：%s" % str(err)[:200])
        if progress_cb:
            p = first_path(st, spec.get("progress_paths") or (), None)
            try:
                progress_cb(int(float(p)))
            except Exception:
                progress_cb(0)
        time.sleep(poll_interval)
    raise TimeoutError("云端生成超时（%.0f 秒）" % timeout)


def _out_dir(download_dir=None):
    d = download_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "videos")
    os.makedirs(d, exist_ok=True)
    return d


def download(vurl, download_dir=None, tag="_cloud"):
    """把成片下到本地。返回本地路径。"""
    import requests
    out = os.path.join(_out_dir(download_dir),
                       datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + tag + (os.path.splitext(vurl)[1] or ".mp4"))
    r = requests.get(vurl, timeout=300)
    r.raise_for_status()
    with open(out, "wb") as f:
        f.write(r.content)
    return out


def _save_b64(b64, spec, download_dir=None):
    """有的厂商直接把视频塞在 base64 字段里（result_kind=base64）。"""
    if not b64:
        raise RuntimeError("任务完成了但取不到 base64 内容（检查 video_api.url_paths）")
    raw = str(b64)
    if "," in raw[:80] and "base64" in raw[:80]:
        raw = raw.split(",", 1)[1]
    out = os.path.join(_out_dir(download_dir),
                       datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_b64.mp4")
    with open(out, "wb") as f:
        f.write(base64.b64decode(raw))
    return out, ""


def describe(spec):
    """给界面/日志用的一句话：这家是什么协议、实没实测过、哪儿不确定。"""
    bits = ["协议=%(kind)s" % spec, "来自 %s" % spec.get("_source", "?")]
    bits.append("已实测" if spec.get("verified") else "**未实测**")
    for w in spec.get("_warnings") or []:
        bits.append("注意：" + str(w))
    if spec.get("note"):
        bits.append(str(spec["note"]))
    return " ｜ ".join(bits)
