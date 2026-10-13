# tools/test_agnes_live.py —— 真连 Agnes 云端的活体测试(要网络 + 要 key, 不进 run_all_tests)
# 用法: python tools/test_agnes_live.py
# 干的四件事: 1) 从 xiaojiao_control.json 读 key/model  2) 真提交一条 5 秒任务
#             3) 下载成片  4) ffprobe 看有没有音轨(判断云端视频是不是哑巴)
import os, sys, json, shutil, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from video_service import agenes  # noqa: E402

PROMPT = "一只橘猫坐在窗台上看雨, 窗外是模糊的城市灯光, 镜头缓慢推近, 电影感"


def _prog(p):
    if p < 0:
        print("  排队中(第 %d 次撞队列, 等 60s 再试)…" % (-p), flush=True)
    else:
        print("  progress", p, flush=True)


def ffprobe(path):
    exe = shutil.which("ffprobe") or r"C:\Users\Jiao\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"
    if not os.path.exists(exe):
        return "没找到 ffprobe, 跳过音轨检查"
    r = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format",
                        "-of", "json", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return "ffprobe 失败: " + (r.stderr or "")[:300]
    d = json.loads(r.stdout)
    streams = [{"type": s.get("codec_type"), "codec": s.get("codec_name"),
                "dur": s.get("duration"), "sr": s.get("sample_rate")}
               for s in d.get("streams", [])]
    kinds = [s["type"] for s in streams]
    has_audio = "audio" in kinds
    return json.dumps({"streams": streams,
                       "容器时长": d.get("format", {}).get("duration"),
                       "有音轨": has_audio,
                       "结论": "✅ 有声音通道" if has_audio else "🔇 纯视频, 没有音轨"},
                      ensure_ascii=False, indent=1)


def main():
    print("key 配了吗：", bool(agenes._key()), "｜ 模型：", agenes.model(), flush=True)
    if not agenes._key():
        print("❌ 没 key, 先配 xiaojiao_control.json 的 models[] 里 agnes 那条 api_key, "
              "或设环境变量 XIAOJIAO_AGNES_KEY")
        return 1
    print("提交中(免费档 1 RPM, 提交前会节流)…", flush=True)
    t = __import__("time").time()
    try:
        path, url = agenes.generate(PROMPT, mode="text", seconds="5", size="720P",
                                    progress_cb=_prog,
                                    create_retry=int(os.environ.get("XIAOJIAO_AGNES_RETRY", "5")))
    except Exception as e:
        print("❌ %s: %s" % (type(e).__name__, e))
        return 2
    print("✅ 用时 %.1f 秒" % (__import__("time").time() - t))
    print("本地文件：", path, os.path.getsize(path) if os.path.exists(path) else "-", "字节")
    print("远程地址：", url)
    print(ffprobe(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
