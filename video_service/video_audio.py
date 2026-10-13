# video_service/video_audio.py —— 给视频"接上声音"和"接长"的工具(SAPI 中文朗读 + ffmpeg)
#
# 老实说清楚(不许粉饰):
#   · 本地 Wan2.1 **根本没有音频通道**, 它永远出不来声音, 不是"没配好"是"没这个能力"。
#   · 云端 Agnes 的视频有没有音轨, 要用 ffprobe 看(本文件 probe 就是干这个的)。
#   · 视频里没有人声时, 本模块用 **Windows 自带中文语音(Microsoft Huihui)** 把台词念成 wav,
#     再用 ffmpeg 混进画面 —— 这叫「载体替他配音」, **不是**「AI 自己想说话就说出来了」。
#   · 单次云端生成最长 12 秒; 本地 Wan2.1 单次最多 81 帧。要 15 秒以上就得多段拼(concat)。
import os, sys, json, shutil, tempfile, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "videos")
FFMPEG = shutil.which("ffmpeg") or r"C:\Users\Jiao\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
FFPROBE = shutil.which("ffprobe") or r"C:\Users\Jiao\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"


def have_ffmpeg():
    return os.path.exists(FFMPEG)


def _run(args, timeout=600):
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _even(v):
    """H.264 要求宽高是偶数。"""
    v = int(v or 0)
    return v - (v % 2) if v > 1 else 2


def probe(path):
    """看一条视频的真实情况: 时长/分辨率/有没有音轨。"""
    if not os.path.exists(path):
        return {"ok": False, "error": "文件不存在: " + path}
    rc, out, err = _run([FFPROBE, "-v", "error", "-show_streams", "-show_format",
                         "-of", "json", path], timeout=60)
    if rc != 0:
        return {"ok": False, "error": (err or "")[:300]}
    d = json.loads(out)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {"ok": True,
            "时长秒": round(float(d.get("format", {}).get("duration") or 0), 2),
            "宽度": v.get("width"), "高度": v.get("height"),
            "视频编码": v.get("codec_name"),
            "有音轨": bool(a), "音轨编码": (a or {}).get("codec_name"),
            "音轨声道": (a or {}).get("channels"),
            "文件": os.path.basename(path), "字节": os.path.getsize(path)}


def tts_wav(text, out_wav=None, rate=0, voice=None):
    """用 Windows 自带中文语音把 text 念成 wav。返回 wav 路径。

    rate: -10~10(0 正常, 负数更慢)。voice 缺省挑第一个 zh-CN 声音(Huihui)。
    """
    if not out_wav:
        out_wav = os.path.join(OUT_DIR, "tts_%s.wav" % __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out_wav), exist_ok=True)
    ps = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = %VOICE%
if ($voice) { try { $s.SelectVoice($voice) } catch {} }
$s.Rate = %RATE%
$s.SetOutputToWaveFile("%OUT%")
$s.Speak([System.IO.File]::ReadAllText("%TXT%", [System.Text.Encoding]::UTF8))
$s.Dispose()
Write-Output "ok"
'''
    txt = os.path.join(tempfile.gettempdir(), "_xiao_tts_text.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write(text or "")
    ps = (ps.replace("%OUT%", out_wav.replace("\\", "\\\\"))
            .replace("%TXT%", txt.replace("\\", "\\\\"))
            .replace("%RATE%", str(int(rate)))
            .replace("%VOICE%", ("'%s'" % voice) if voice else "''"))
    ps1 = os.path.join(tempfile.gettempdir(), "_xiao_tts.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as f:   # BOM: 让 Windows PowerShell 也认 UTF-8
        f.write(ps)
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        raise RuntimeError("找不到 PowerShell, 没法用系统语音念台词")
    rc, out, err = _run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1], timeout=180)
    if rc != 0 or not os.path.exists(out_wav):
        raise RuntimeError("系统语音念台词失败: " + ((err or out or "")[:300]))
    return out_wav


def concat(parts, out=None):
    """把多段视频按顺序拼成一条(重编码 + 统一 720P, 免得不一致失败)。返回输出路径。

    每一段都有音轨时, 声音也一起拼; 有段落没声音就只拼画面(并在返回值里说明是哪种)。
    """
    parts = [p for p in parts if os.path.exists(p)]
    if not parts:
        raise RuntimeError("没有可拼接的视频")
    if len(parts) == 1:
        return parts[0]
    if not out:
        out = os.path.join(OUT_DIR, "concat_%s.mp4" % __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = len(parts)
    keep_audio = all(probe(p).get("有音轨") for p in parts)
    first = probe(parts[0])                      # 统一到第一段的分辨率(不是硬写 720P:
    W, H = _even(first.get("宽度") or 1280), _even(first.get("高度") or 720)   # Agnes 16:9 实际是 1280x704)
    args = [FFMPEG, "-y"]
    for p in parts:
        args += ["-i", p]
    filt = "".join("[%d:v]scale=%d:%d,setsar=1[v%d];" % (i, W, H, i) for i in range(n))
    filt += "".join("[v%d]" % i for i in range(n)) + "concat=n=%d:v=1:a=0[outv]" % n
    if keep_audio:
        filt += ";" + "".join("[%d:a]" % i for i in range(n)) + "concat=n=%d:v=0:a=1[outa]" % n
    args += ["-filter_complex", filt, "-map", "[outv]"]
    if keep_audio:
        args += ["-map", "[outa]", "-c:a", "aac", "-b:a", "160k"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out]
    rc, so, se = _run(args, timeout=1800)
    if rc != 0 or not os.path.exists(out):
        raise RuntimeError("拼接失败: " + (se or so or "")[-400:])
    return out


def add_audio(video, wav=None, text=None, out=None, keep_original=False, loop_audio=False):
    """给视频接上声音。默认**以画面为准**: 台词短了就补静音, 绝不把视频剪短。

    wav 给了就用它; 没给但有 text 就用系统语音念出来。
    keep_original=True 时会把原音轨和配音混在一起(视频本来有声音就用这个);
    否则原音轨直接丢掉(视频没声音时它本来也没有)。

    ⚠️ 2026-10-13 踩过的坑: 只用 `-shortest` 而不管音频长短, ffmpeg 会以**较短的音频**收尾
    —— 15 秒的画面配 4 秒台词, 出来只剩 4 秒。这正好撞上用户那句「秒数…至少 15s」。
    现在给音频串上 `apad`(补静音)再 `-shortest`, 收尾就永远跟着画面走。
    """
    if not os.path.exists(video):
        raise RuntimeError("没有这个视频: " + video)
    if not wav:
        if not text:
            raise RuntimeError("要么给 wav, 要么给 text(我去念)")
        wav = tts_wav(text)
    if not out:
        out = os.path.join(OUT_DIR, os.path.splitext(os.path.basename(video))[0] + "_有声.mp4")
    info = probe(video)
    args = [FFMPEG, "-y", "-i", video]
    if loop_audio:
        args += ["-stream_loop", "-1"]
    args += ["-i", wav]
    if info.get("有音轨") and keep_original:
        # 原声 + 配音混音, 然后补静音到画面长度
        args += ["-filter_complex",
                 "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[mix];[mix]apad[a]",
                 "-map", "0:v", "-map", "[a]"]
    else:
        args += ["-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]"]
    args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", out]
    rc, so, se = _run(args, timeout=900)
    if rc != 0:
        # 视频流 copy 偶尔和容器不兼容, 退回重编码
        args2 = list(args)
        i = args2.index("-c:v")
        args2[i + 1] = "libx264"
        rc, so, se = _run(args2, timeout=1800)
    if rc != 0 or not os.path.exists(out):
        raise RuntimeError("配音合成失败: " + (se or so or "")[-400:])
    return out


def _main(argv):
    if len(argv) < 2:
        print("用法:")
        print("  python video_service/video_audio.py probe  <视频>")
        print("  python video_service/video_audio.py tts    \"台词\" [out.wav]")
        print("  python video_service/video_audio.py audio  <视频> \"台词\" [out.mp4]   # 念台词接进视频")
        print("  python video_service/video_audio.py concat <视频1> <视频2> ...        # 拼成一条")
        return 0
    cmd = argv[1]
    if cmd == "probe":
        print(json.dumps(probe(argv[2]), ensure_ascii=False, indent=1))
    elif cmd == "tts":
        p = tts_wav(argv[2], argv[3] if len(argv) > 3 else None)
        print(p); print(json.dumps(probe(p), ensure_ascii=False))
    elif cmd == "audio":
        p = add_audio(argv[2], text=argv[3], out=(argv[4] if len(argv) > 4 else None))
        print(p); print(json.dumps(probe(p), ensure_ascii=False, indent=1))
    elif cmd == "concat":
        p = concat(argv[2:])
        print(p); print(json.dumps(probe(p), ensure_ascii=False, indent=1))
    else:
        print("不认识的命令: " + cmd)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
