# tools/test_video_audio.py —— 视频"接声音/接长"的离线测试(只用 ffmpeg + 系统语音, 不联网)
# 为什么要有这个测试: 2026-10-13 用户问"他生成的视频都没有声音呢…秒数…至少15s"。
#   本地 Wan2.1 没有音频通道 → 声音只能靠配音接; 时长只能靠拼。这两件事都要能自证。
import os, sys, json, shutil, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "video_service"))

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


def _ffmpeg():
    return shutil.which("ffmpeg") or r"C:\Users\Jiao\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"


def make_clip(path, sec=2, size="320x180", rate=24):
    r = subprocess.run([_ffmpeg(), "-y", "-f", "lavfi", "-i",
                        "testsrc=size=%s:rate=%d:duration=%d" % (size, rate, sec),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and os.path.exists(path)


def main():
    print("== 视频接声音/接长 离线自测 ==")
    import video_audio as va

    ok("ffmpeg 在", va.have_ffmpeg(), va.FFMPEG)
    tmp = tempfile.mkdtemp(prefix="xiaojiao_videoaudio_")
    a = os.path.join(tmp, "a.mp4")
    b = os.path.join(tmp, "b.mp4")
    ok("造得出测试片", make_clip(a, 2) and make_clip(b, 2))

    p = va.probe(a)
    ok("probe 读得出时长", p.get("ok") and abs(p.get("时长秒", 0) - 2) < 0.3, p.get("时长秒"))
    ok("probe 认出没音轨(裸视频)", p.get("ok") and p.get("有音轨") is False)
    ok("probe 认不出文件时不炸", va.probe(os.path.join(tmp, "没有这个.mp4")).get("ok") is False)

    wav = va.tts_wav("小焦测试一句中文台词。", os.path.join(tmp, "t.wav"))
    ok("系统语音念出台词(wav)", os.path.exists(wav) and os.path.getsize(wav) > 1000,
       os.path.getsize(wav) if os.path.exists(wav) else 0)

    out = va.add_audio(a, wav=wav, out=os.path.join(tmp, "a_sound.mp4"))
    pa = va.probe(out)
    ok("配音接上了(有音轨)", pa.get("有音轨") is True, pa.get("音轨编码"))
    ok("配音后时长没被拉坏", abs(pa.get("时长秒", 0) - 2) < 0.5, pa.get("时长秒"))

    out2 = va.add_audio(a, text="这是一句现念的台词。", out=os.path.join(tmp, "a_sound2.mp4"))
    ok("只给台词也能接声音", va.probe(out2).get("有音轨") is True)

    c = va.concat([a, b], out=os.path.join(tmp, "c.mp4"))
    pc = va.probe(c)
    ok("两段拼成一条", pc.get("ok") and abs(pc.get("时长秒", 0) - 4) < 0.6, pc.get("时长秒"))
    ok("拼接后统一到第一段的分辨率", (pc.get("宽度"), pc.get("高度")) == (320, 180),
       "%sx%s" % (pc.get("宽度"), pc.get("高度")))

    # 每段都有声音时, 拼接要把声音也带上(不然"拼完就没声了")
    a2 = va.add_audio(a, text="第一段台词。", out=os.path.join(tmp, "a2.mp4"))
    b2 = va.add_audio(b, text="第二段台词。", out=os.path.join(tmp, "b2.mp4"))
    c2 = va.concat([a2, b2], out=os.path.join(tmp, "c2.mp4"))
    ok("每段都有声音时拼接保住了声音", va.probe(c2).get("有音轨") is True)

    # 15 秒场景: 3 段 5 秒拼起来 → 再配音 = 一条 15 秒有声片
    clips = []
    for i in range(3):
        pth = os.path.join(tmp, "s%d.mp4" % i)
        make_clip(pth, 5)
        clips.append(pth)
    long15 = va.concat(clips, out=os.path.join(tmp, "long15.mp4"))
    p15 = va.probe(long15)
    ok("3×5 秒能拼到 15 秒", abs(p15.get("时长秒", 0) - 15) < 1.0, p15.get("时长秒"))
    final = va.add_audio(long15, text="这是十五秒的视频, 而且它有声音。", out=os.path.join(tmp, "long15_sound.mp4"))
    pf = va.probe(final)
    ok("15 秒 + 有声音 一起成立", abs(pf.get("时长秒", 0) - 15) < 1.0 and pf.get("有音轨") is True,
       json.dumps({"秒": pf.get("时长秒"), "音轨": pf.get("有音轨")}, ensure_ascii=False))

    # agenes 的模型名绝不能是对话模型(踩过: models[] 里那条 agnes-2.5-flash 是 chat 模型)
    try:
        import agenes
        m = agenes.model()
        ok("Agnes 用的是视频模型名(不是对话模型)", "video" in (m or "").lower(), m)
    except Exception as e:
        ok("Agnes 模块可导入", False, e)

    # 内部开关绝不能混进发给云端的请求体(踩过: create_retry 一起发出去 → 400)
    try:
        import agenes as ag
        sent = []

        class _R:
            status_code = 400
            text = "stop"

            def json(self):
                return {}
        _post, _throttle = ag.requests.post, ag._throttle
        ag.requests.post = lambda url, headers=None, json=None, timeout=None: (sent.append(json), _R())[1]
        ag._throttle = lambda: None
        try:
            try:
                ag.generate("测试", mode="text", seconds="5", create_retry=1)
            except Exception:
                pass
        finally:
            ag.requests.post, ag._throttle = _post, _throttle
        ok("内部开关不会发给服务器", bool(sent) and "create_retry" not in sent[0],
           sorted(sent[0].keys()) if sent else "没发出请求")
        ok("发出去的参数就是官方那几个",
           bool(sent) and set(sent[0]) == {"model", "prompt", "mode", "size", "aspect_ratio", "seconds"})
    except Exception as e:
        ok("能自查发给云端的请求体", False, "%s: %s" % (type(e).__name__, e))

    # 本地"至少 15 秒"的拆段计划: 每段帧数必须是 4k+1, 且合计不能短于用户要的秒数
    try:
        import video_api as vapi
        ok("本地 15 秒计划合计不短于 15 秒",
           sum(f for f, _ in vapi._local_segments(15)) / 16.0 >= 15,
           vapi._local_segments(15))
        ok("每段帧数都是 4k+1", all((f - 1) % 4 == 0 for f, _ in vapi._local_segments(15)),
           vapi._local_segments(15))
        ok("每段不超过 81 帧(8G 显存上限)", all(f <= 81 for f, _ in vapi._local_segments(60)),
           vapi._local_segments(60))
        wf = vapi._load_workflow("提示词", "ckpt", num_frames=81, fps=16, seed=9)
        ok("工作流能按节点改帧数/fps/种子",
           wf["4"]["inputs"]["num_frames"] == 81 and wf["8"]["inputs"]["fps"] == 16
           and wf["5"]["inputs"]["seed"] == 9)
        ok("工作流占位符替换正常",
           wf["3"]["inputs"]["positive_prompt"] == "提示词" and wf["1"]["inputs"]["model"] == "ckpt")
    except Exception as e:
        ok("video_api 可导入并检查拆段计划", False, "%s: %s" % (type(e).__name__, e))

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
