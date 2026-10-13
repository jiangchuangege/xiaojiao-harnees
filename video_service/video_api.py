# video_service/video_api.py —— Web 扩展（Blueprint）：真·文生视频（ComfyUI + Wan2.1）
# 模型按需切换：卸载大脑 → 起 ComfyUI → 生成 → 卸载 ComfyUI → 恢复大脑（对用户透明）
# 任务状态用普通 dict 读写（GIL 安全），不持锁 —— 避免模型切换/任务线程把状态接口堵死。
import os, json, threading, datetime, time, math
import re as _re      # 判"这句描述像不像人写的"(见 _prompt_is_plausible)
from flask import Blueprint, request, jsonify
import config, model_switch as ms, comfy_client as cc
import logging  # noqa: F401  （由 tools/fix_silent_except.py 注入）
try:
    from xiaojiao_log import get_logger
except Exception:  # 独立运行时退化为标准 logging
    def get_logger(name=None):
        return logging.getLogger(name or 'xiaojiao')
LOG = get_logger(__name__)

bp = Blueprint("video_service", __name__)
_jobs = {}
_JOBS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_jobs.json")

def video_mode():
    """视频大脑模式: 'api'(云端 Agnes API) 或 'local'(本地 ComfyUI+Wan)。
    环境变量 XIAOJIAO_VIDEO_MODE 优先, 其次控制文件 brain.video_mode, 默认 api。"""
    m = os.environ.get("XIAOJIAO_VIDEO_MODE", "").strip().lower()
    if m in ("api", "local"):
        return m
    try:
        import json as _j, os as _o
        root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        d = _j.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        mm = (d.get("brain", {}).get("video_mode", "") or "").strip().lower()
        if mm in ("api", "local"):
            return mm
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 25, e)
    return "api"

def _sweep():
    """清理卡死/超时(30分钟)的 switching/generating 任务，避免'请稍候'死锁。"""
    now = time.time()
    for jid, j in list(_jobs.items()):
        if j.get("state") in ("switching", "generating") and now - j.get("ts", 0) > 600:
            j["state"] = "error"
            j["message"] = "生成超时(30分钟)，请重新生成"


def _schedule_warm_idle(job_id, minutes=15):
    """视频生成完后: keep_warm=false 时, 温存 N 分钟(ComfyUI不关,连续视频秒级), 超时无新任务则冷启动释放内存。"""
    def _tick():
        import time as _t
        _t.sleep(minutes * 60)
        try:
            # 无新视频任务(还在 switching/generating) 就不停
            busy = any(j.get("state") in ("switching", "generating", "queued") for j in _jobs.values())
            if not busy and not _keep_warm_flag():
                import model_switch as _ms
                _ms.stop_comfy()
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 49, e)
    threading.Thread(target=_tick, daemon=True).start()


def _keep_warm_flag():
    try:
        import json as _j, os as _o
        root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        d = _j.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        return bool(d.get("brain", {}).get("keep_warm", False))
    except Exception:
        return False


def _local_segments(want_sec, fps=16, max_frames=81):
    """本地 Wan2.1 要凑够 want_sec 秒, 拆成几段、每段几帧。

    Wan 只吃 4k+1 帧(9/33/81/...), 一次最多 81 帧。81 帧 @16fps ≈ 5.06 秒 → 15 秒 = 3 段。
    返回 [(帧数, fps), ...], 最后一段按余数收尾。
    """
    clip_sec = float(max_frames) / float(fps)
    n = max(1, int(math.ceil(float(want_sec) / clip_sec)))
    out = []
    for i in range(n):
        seg_sec = min(clip_sec, want_sec - clip_sec * i)
        frames = int(math.ceil(seg_sec * fps))
        # 往**上**取到 4k+1, 宁可多一两帧也不要短于用户要的秒数
        frames = max(9, min(max_frames, ((frames - 1 + 3) // 4) * 4 + 1))
        out.append((frames, fps))
    return out


def _job_seconds(job_id):
    """这一单要几秒。用户要的是「至少 15 秒」, 所以缺省目标就是 15 秒(而不是以前的 1.4 秒)。"""
    try:
        v = int(float(_jobs[job_id].get("seconds") or 0))
    except Exception:
        v = 0
    if v <= 0:
        try:
            import json as _j, os as _o
            root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
            d = _j.load(open(_o.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
            v = int(d.get("video", {}).get("seconds") or 0)
        except Exception:
            v = 0
    if v <= 0:
        v = 15            # 用户 2026-10-13: 「秒数…至少15s」
    return max(4, min(v, 120))


def _persist():
    try:
        json.dump(_jobs, open(_JOBS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 67, e)

try:
    _jobs.update(json.load(open(_JOBS_FILE, encoding="utf-8")))
except Exception as e:
    LOG.debug("忽略异常(%s:%d): %s", __file__, 79, e)

# ⚠️ 2026-10-13: 任务是存盘续跑的, 但**执行它的线程**跟着进程一起没了。
#    重开程序后那些"正在生成"的旧记录会永远停在那儿, /api/video 也会一直回"正在生成，请稍候"——
#    用户看到的就是"点了没反应"。启动时把上一次没跑完的如实标成中断。
for _j in _jobs.values():
    if _j.get("state") in ("queued", "switching", "generating"):
        _j["state"] = "error"
        _j["error"] = "上次运行时中断(程序重启了)"
        _j["message"] = "上次这一单被中断了(程序重启过)，请重新生成一次"

def _load_workflow(prompt, ckpt, num_frames=None, fps=None, seed=None, width=None, height=None):
    """装 Wan2.1 工作流。可覆盖帧数/fps/种子/分辨率 —— 帧数和 fps 决定**成片几秒**:
    33 帧 @24fps 只有 1.4 秒, 用户要 15 秒就得 81 帧 @16fps ≈ 5.06 秒 × 3 段拼。"""
    wf = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow_wan.json"), encoding="utf-8"))
    model_opt = os.environ.get("XIAOJIAO_WAN_MODEL", "wan2.6-t2v")
    for node in wf.values():
        for k, v in node.get("inputs", {}).items():
            if isinstance(v, str):
                v = v.replace("__CKPT__", ckpt).replace("__POS__", prompt).replace("__MODEL__", model_opt)
                node["inputs"][k] = v
    # 按节点号精确覆盖, 不乱改其它节点的同名键
    n4 = wf.get("4", {}).get("inputs", {})
    if num_frames:
        n4["num_frames"] = int(num_frames)
    if width:
        n4["width"] = int(width)
    if height:
        n4["height"] = int(height)
    if fps:
        wf.get("8", {}).get("inputs", {})["fps"] = int(fps)
    if seed is not None:
        wf.get("5", {}).get("inputs", {})["seed"] = int(seed)
    return wf


def _base_url():
    """当前大脑 base_url(llama-swap)。"""
    try:
        import json as _j
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = _j.load(open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        return d.get("brain", {}).get("api", {}).get("base_url") or "http://127.0.0.1:9292/v1"
    except Exception:
        return "http://127.0.0.1:9292/v1"


def _translate_zh(_p):
    """把英文提示词翻译成一句简洁中文。失败则返回输入。"""
    try:
        import requests as _r
        r = _r.post(_base_url().rstrip("/") + "/chat/completions",
                    json={"model": _llm_model(),
                          "messages": [{"role": "system", "content": "把这段英文视频提示词翻译成一句简洁中文（只说中文，不要英文、不要解释）。"},
                                       {"role": "user", "content": _p}],
                          "max_tokens": 60, "temperature": 0.3, "chat_template_kwargs": {"enable_thinking": False}}, timeout=15)
        if r.status_code == 200:
            c = (r.json()["choices"][0].get("message", {}).get("content") or "").strip()
            if c:
                return c
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 110, e)
    return _p


def _llm_model():
    """小焦大脑当前模型名(与控制文件一致, llama-swap 路由用)。"""
    try:
        import json as _j
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = _j.load(open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        return d.get("brain", {}).get("api", {}).get("model") or "xiaojiao"
    except Exception:
        return "xiaojiao"


def _kb():
    """小脑「电影设计提示词学习库」(向量库, self_learn/vstore)。"""
    try:
        import sys as _sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _sys.path.insert(0, os.path.join(root, "self_learn"))
        import vstore
        return vstore
    except Exception:
        return None


def _prompt_is_plausible(raw):
    """这句描述像不像"人写的场景"? 不像就不许学进库、也不许拿库里的东西顶替。

    ⚠️ 2026-10-13 真事: 我用 PowerShell 发 JSON 时中文被编成了 `???????????, ...`,
    这种垃圾被当成"用户描述"学进了提示词库; 之后用户写「一只橘猫坐在窗台上看雨」
    在库里按 0.35 的相似度命中了那条垃圾, 于是**生成出来的是一个男人的脸** ——
    用户问的就是"我让它做 A 它给我 B"。判据: 至少要有中文或拉丁字母;
    连着三个问号基本就是编码坏了的痕迹。
    """
    s = (raw or "").strip()
    if len(s) < 2:
        return False
    if "???" in s:
        return False
    return bool(_re.search(r"[\u4e00-\u9fff]", s) or _re.search(r"[A-Za-z]{2,}", s))


def _refine_prompt(raw, save=True):
    """用小焦大脑精炼出电影级提示词。①先查小脑学习库(向量库命中=用学过的) ②大脑精炼并学进库 ③模板兜底。绝不给用户看思考过程。

    ⚠️ 2026-10-13 改两处(实测踩到"要猫给人脸"):
      · 库命中要求**像**才用: 阈值 0.35 → 0.62。0.35 太松, 一条坏掉的样本能顶掉任何新描述;
      · 描述不像人写的就不学(见 _prompt_is_plausible), 免得垃圾进库以后一直往外冒。
      阈值可以用 xiaojiao_control.json 的 video.kb_threshold 调。
    """
    raw = (raw or "").strip()
    if not raw: return raw
    V = _kb()
    if V and _prompt_is_plausible(raw):
        try:
            thr = 0.62
            try:
                import json as _jj, os as _oo
                _root = _oo.path.dirname(_oo.path.dirname(_oo.path.abspath(__file__)))
                _c = _jj.load(open(_oo.path.join(_root, "xiaojiao_control.json"), encoding="utf-8"))
                thr = float((_c.get("video") or {}).get("kb_threshold") or thr)
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 203, e)
            r = V.search("用户: " + raw, k=1, threshold=thr)
            if r["hit"] and r["best"][1]:
                best = r["best"][1]
                if "-> 精炼: " in best:
                    best = best.split("-> 精炼: ", 1)[1]
                return best
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 151, e)
    try:
        import json as _j, requests as _r, re as _re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = _j.load(open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        base = (cfg.get("brain", {}).get("api", {}).get("base_url") or "http://127.0.0.1:8080/v1")
        sys_p = ("你是专业电影导演。把用户的视频描述**简洁**改写成一段英文电影提示词(主体/光线/镜头/风格)，不超过 80 字。只输出提示词，不要解释、不要引号、不要思考。")
        r = _r.post(base.rstrip("/") + "/chat/completions",
                    json={"model": _llm_model(),
                          "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": raw}],
                          "max_tokens": 400, "temperature": 0.6, "chat_template_kwargs": {"enable_thinking": False}},
                    timeout=6)
        if r.status_code == 200:
            msg = r.json()["choices"][0].get("message", {})
            out = (msg.get("content") or "").strip()
            if not out:
                rc = (msg.get("reasoning_content") or "")
                drafts = _re.findall(r"(?:Draft|Final Prompt|最终提示词|结果|Final)[^\\n]*?[:：]\\s*([^\\n]{8,})", rc)
                if drafts:
                    out = drafts[-1].strip()
                else:
                    lines = [l.strip() for l in rc.split("\\n") if l.strip() and len(l.strip()) > 8]
                    out = lines[-1] if lines else ""
            if out:
                if len(out) > 300: out = out[-300:]
                if save and _prompt_is_plausible(raw):
                    V = _kb()
                    if V:
                        try:
                            V.add("用户: %s -> 精炼: %s" % (raw, out), tag="video_prompt")
                        except Exception as e:
                            LOG.debug("忽略异常(%s:%d): %s", __file__, 182, e)
                return out
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 185, e)
    # 模板兜底(秒出): 加电影级修饰词
    return raw + ", cinematic, high detail, dramatic lighting, smooth motion, film quality"


def _worker(job_id, prompt):
    confirmed = _jobs[job_id].get("confirmed_refined") or ""
    want_sec = _job_seconds(job_id)
    narrate = (_jobs[job_id].get("narrate") or "").strip()
    # === 模式判定: api(云端任意厂商) vs local(本地 ComfyUI) ===
    use_cloud = video_mode() == "api"
    if use_cloud:
        try:
            import cloud_video as _cv
            use_cloud = _cv.available()   # api 模式下还得有配置好的视频模型(带key)才走云端
            if use_cloud:
                _ok_run, _why_run = _cv.runnable()
                try:
                    LOG.info("云端视频：%s", _cv.describe())
                except Exception as e:      # noqa: silent-ok — 只是记一行说明
                    LOG.debug("忽略异常(%s:%d): %s", __file__, 297, e)
                if not _ok_run:
                    # 配了模型但跑不了（没实测过的协议 / 缺 base_url 等）—— 如实说清再回落本地
                    LOG.warning("云端视频这家**现在跑不了**：%s → 这一单走本地", _why_run)
                    print("[video] 云端跑不了：%s → 回落本地" % _why_run, flush=True)
                    _jobs[job_id]["cloud_note"] = _why_run
                    use_cloud = False
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 300, e)
            use_cloud = False
    if use_cloud:
        # api 模式: 不卸载大脑/不占显存/不本地精炼, 直接透传给云端(通用适配器自动识别协议)
        refined = confirmed or prompt
        _jobs[job_id]["prompt"] = prompt
        _jobs[job_id]["refined_prompt"] = refined
        _persist()
        _jobs[job_id].update(state="generating", message="正在生成视频…(云端 %s)" % _cv.provider())
        _persist()
        try:
            def _ap(v):
                try:
                    if v is not None and int(v) < 0:
                        # 负数 = 云端队列满, 正在排队重试(免费档 1 RPM, 每次等 60 秒)
                        _jobs[job_id]["message"] = "云端排队中(队列满, 每 60 秒再试一次)…"
                        _persist()
                        return
                    _jobs[job_id]["progress"] = {"value": v, "max": 100}
                except Exception as e:
                    LOG.debug("忽略异常(%s:%d): %s", __file__, 213, e)
            _jobs[job_id].update(state="generating",
                                 message="正在生成视频…(云端 %s, 目标 %d 秒)" % (_cv.provider(), want_sec))
            _persist()
            try:
                import agenes as _ag
            except ImportError:
                from video_service import agenes as _ag
            have_agnes = _cv.provider() == "agnes"
            if have_agnes and want_sec > 12:
                # 云端一次最长 12 秒 → 15 秒要拆两条再拼(video_audio.concat)
                out = _ag.generate_long(refined, seconds=want_sec, narrate=narrate or None,
                                        progress_cb=_ap)
                vurl = ""
            else:
                out, vurl = _cv.generate(refined, mode="text", seconds=str(min(want_sec, 12)),
                                         progress_cb=_ap)
                if narrate:
                    # 视频本身没音轨时, 用系统中文语音把台词念进画面(载体配音, 不是模型自己说话)
                    import video_audio as _va
                    out = _va.add_audio(out, text=narrate)
            _jobs[job_id].update(state="done", message="完成(云端 %s)" % _cv.provider(),
                                 url="/videos/" + os.path.basename(out), video_url=vurl)
            _persist()
            return
        except Exception as e:
            print("[video] 云端视频生成失败, 回落本地: %s" % e, flush=True)

    # === 本地 ComfyUI 模式(卸载大脑→切换→生成→恢复, 带精炼) ===
    _jobs[job_id].update(state="switching", message="精炼提示词…")
    _persist()
    refined = confirmed or _refine_prompt(prompt)
    _jobs[job_id]["prompt"] = prompt
    _jobs[job_id]["refined_prompt"] = refined
    _persist()

    _jobs[job_id].update(state="switching", message="卸载大脑，腾出显存…")
    _persist()
    try:
        import brain_manager as _bm
        _bm.switch_to("video")
        prompt = refined
        ckpt = config.find_checkpoint() or "dit_fp8.safetensors"
        # 本地 Wan2.1 一次最多 81 帧; 16fps × 81 帧 ≈ 5.06 秒。要 15 秒就生成 3 段再拼。
        # (以前固定 33 帧 @24fps = 1.4 秒, 这就是用户说的「秒数…至少15s」的由来)
        plan = _local_segments(want_sec)
        segs = len(plan)
        outs = []
        for i, (frames, seg_fps) in enumerate(plan):
            _jobs[job_id].update(state="generating",
                                 message="正在生成视频…(Wan2.1 FP8, 第 %d/%d 段, %d 帧)" % (i + 1, segs, frames))
            _persist()
            seg_prompt = prompt if segs == 1 else "%s(第%d/%d段, 同一场景同一主体, 镜头连贯)" % (prompt, i + 1, segs)
            wf = _load_workflow(seg_prompt, ckpt, num_frames=frames, fps=seg_fps, seed=42 + i)
            pid = cc.submit_workflow(wf)
            def _prog(value, maxv):
                try:
                    _jobs[job_id]["progress"] = {"value": value, "max": maxv}
                except Exception as e:
                    LOG.debug("忽略异常(%s:%d): %s", __file__, 244, e)
            fn, sub, ftype = cc.wait_output(pid, progress_cb=_prog)
            name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_wan%d" % i
            seg_out = os.path.join(config.OUT_DIR, name + (os.path.splitext(fn)[1] or ".mp4"))
            cc.download_video(fn, sub, ftype, seg_out)
            outs.append(seg_out)
        if len(outs) > 1:
            import video_audio as _va
            out = _va.concat(outs, out=os.path.join(config.OUT_DIR,
                                                    datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_wan_long.mp4"))
        else:
            out = outs[0]
        if narrate:
            import video_audio as _va2
            out = _va2.add_audio(out, text=narrate)
        _jobs[job_id].update(state="switching", message="卸载视频模型…")
        import brain_manager as _bm2
        _bm2.switch_to("chat")
        _jobs[job_id].update(state="done", message="完成", url="/videos/" + os.path.basename(out))
        if not _keep_warm_flag():
            _schedule_warm_idle(job_id)  # 温存15分钟,超时自动释放内存
    except Exception as e:
        try:
            import brain_manager as _bm3
            _bm3.switch_to("chat")
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 260, e)
        _jobs[job_id].update(state="error", error=str(e), message="生成失败，已尽力恢复大脑")
    _persist()

@bp.route("/api/video/refine")
def api_video_refine():
    """只精炼提示词(不学习/不切换)——供前端"确认提示词"流程用。"""
    prompt = (request.args.get("prompt") or "").strip()[:80] or (request.get_json(silent=True) or {}).get("prompt", "")
    refined = _refine_prompt(prompt, save=False)
    # 中文大意(给用户看懂): 简单概括原始场景
    zh = prompt
    def _zh(_p):
        try:
            import json as _j, requests as _r
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cfg = _j.load(open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
            base = (cfg.get("brain", {}).get("api", {}).get("base_url") or "http://127.0.0.1:8080/v1")
            r = _r.post(base.rstrip("/") + "/chat/completions", json={"model":_llm_model(),"messages":[{"role":"system","content":"把这段英文视频提示词翻译成一句简洁中文（只说中文，不要英文、不要解释）。"},{"role":"user","content":_p}],"max_tokens":60,"temperature":0.3,"chat_template_kwargs":{"enable_thinking":False}}, timeout=10)
            if r.status_code == 200:
                c = (r.json()["choices"][0].get("message",{}).get("content") or "").strip()
                return c or _p
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 282, e)
        return _p
    zh = _translate_zh(refined) if len(refined) > 15 else prompt
    return jsonify({"ok": True, "refined": refined, "zh": zh})


def cloud_info():
    """云端这一家的实况（给界面看）：能不能用、跑不跑得了、走的是什么协议。

    【为什么要它】2026-10-14 起云端不再只认一家（见 `video_api_spec.py`），
    界面就不能再写死「云端 Agnes API」—— 得如实显示**当前接的是谁、什么协议、实没实测过**。
    """
    try:
        import cloud_video as _cv
        ok_run, why = _cv.runnable()
        return {"available": bool(_cv.available()), "model": _cv.model(),
                "provider": _cv.provider(), "runnable": bool(ok_run), "why": why,
                "describe": _cv.describe()}
    except Exception as e:
        return {"available": False, "runnable": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120]),
                "describe": "云端模块读不出来"}


@bp.route("/api/video/mode", methods=["GET", "POST"])
def api_video_mode():
    """读/切视频大脑模式: api(云端任意厂商) / local(本地 ComfyUI)。写入 brain.video_mode。

    GET 时顺带回报云端实况（`cloud_info()`），界面据此显示"现在接的是谁、能不能用"。
    """
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        m = (d.get("mode") or "").strip().lower()
        if m not in ("api", "local"):
            return jsonify({"ok": False, "error": "mode 只能是 api 或 local"}), 400
        try:
            import json as _j, os as _o
            root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
            p = _o.path.join(root, "xiaojiao_control.json")
            cfg = _j.load(open(p, encoding="utf-8"))
            cfg.setdefault("brain", {})["video_mode"] = m
            _j.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "mode": m, "cloud": cloud_info()})
    return jsonify({"ok": True, "mode": video_mode(), "cloud": cloud_info(),
                    "default_seconds": _job_seconds("__none__")})


@bp.route("/api/video", methods=["POST"])
def api_video():
    _sweep()
    d = request.get_json(force=True, silent=True) or {}
    prompt = (d.get("prompt") or "").strip()[:80]
    if not prompt:
        return jsonify({"ok": False, "error": "请输入场景"}), 400
    for j in list(_jobs.values()):
        if j.get("state") in ("switching", "generating"):
            return jsonify({"ok": False, "busy": True, "error": "正在生成/切换模型中，请稍候"}), 200
    job_id = datetime.datetime.now().strftime("%H%M%S%f")
    try:
        secs = int(float(d.get("seconds") or 0))
    except Exception:
        secs = 0
    _jobs[job_id] = {"state": "queued", "prompt": prompt, "message": "排队中", "ts": time.time(),
                     "seconds": secs, "narrate": (d.get("narrate") or "").strip()[:200]}
    _persist()
    threading.Thread(target=_worker, args=(job_id, prompt), daemon=True).start()
    return jsonify({"ok": True, "job": job_id, "seconds": _job_seconds(job_id)})

@bp.route("/api/video/status")
def api_video_status():
    job = request.args.get("job", "")
    j = _jobs.get(job)
    if j is None:
        return jsonify({"state": "unknown"})
    return jsonify(j)

@bp.route("/api/video/current")
def api_video_current():
    active = None
    for j in list(_jobs.values()):
        if j.get("state") in ("queued", "switching", "generating"):
            active = j; break
    if active is None:
        active = list(_jobs.values())[-1] if _jobs else None
    if active is None:
        return jsonify({"none": True})
    st = ms.get_state()
    return jsonify({"job": active, "phase": st.get("phase"), "busy": st.get("busy")})

@bp.route("/api/video/promptkb")
def api_video_promptkb():
    """小脑「电影设计提示词学习库」统计+最近学到的(给用户看学了什么)。

    【2026-09-18 修一处真 bug】这个接口原来按自己的 `__file__` 去读
    `video_service/knowledge_vec.json` —— 而精炼提示词写进的是**小脑学习库**
    `self_learn/knowledge_vec.json`（`_kb()` 走的 `self_learn/vstore`，见 `_refine_prompt` 第 2 步）。
    结果是：**写入方和读取方从来不是同一个文件**，那个文件不存在 → 抛异常被吞掉 →
    `count` 永远 0 → 这个接口**永远展示不出"学到了什么"**（连报错都没有）。
    现在**走同一个库**（直接问 `vstore`），写入与读取只有一份事实来源；
    读不到就如实返回 0，不再假装读了另一个文件。
    """
    V = _kb(); n = 0; recent = []
    if V:
        try:
            # 优先用 vstore 自己的读法（它就是写入方），拿不到 API 才退回直读同一个文件
            items = None
            for _name in ("entries", "all", "items"):
                _f = getattr(V, _name, None)
                if callable(_f):
                    try:
                        items = _f()
                        break
                    except Exception as e:
                        LOG.debug("忽略异常(%s:%d): %s", __file__, 366, e)
            if items is None:
                import json as _j
                _p = getattr(V, "VS", "")
                items = (_j.load(open(_p, encoding="utf-8")) or {}).get("entries", []) if _p else []
            for e in (items or []):
                if e.get("tag") == "video_prompt":
                    n += 1
                    recent.append(e.get("text", ""))
            recent = recent[-6:][::-1]
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 360, e)
    return jsonify({"count": n, "recent": recent})


@bp.route("/api/video/state")
def api_video_state():
    st = ms.get_state()
    busy = any(j.get("state") in ("queued", "switching", "generating") for j in _jobs.values())
    return jsonify(dict(st, busy=busy))

@bp.route("/videos/<path:name>")
def serve_video(name):
    from flask import send_from_directory
    return send_from_directory(config.OUT_DIR, name)


@bp.route("/media/<path:name>")
def serve_media(name):
    from flask import send_from_directory
    media_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media")
    return send_from_directory(media_dir, name)
