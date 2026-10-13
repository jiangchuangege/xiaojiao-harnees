# tools/check_lipsync.py —— 查本机有没有"让人物按台词开口"的能力（只读，不装不下）
#
# 为什么要有它：用户问过「为啥是配音而不是让AI视频…有人说话让他说出来有声音那种」。
# 本地 Wan2.1 没有音频通道，所以"人物开口说话"要么靠云端（Veo/Kling 那类），
# 要么靠本地的口型模型（LatentSync / S2V / EchoMimic / Sonic / Wav2Lip 这些）。
# 这个脚本只做一件事：**如实报告本机现在有没有**，缺什么、多大、按 8G 显存够不够。
# 它不下载任何东西 —— 下几个 G 的模型这种事不能自己替用户决定。
import json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY = os.environ.get("XIAOJIAO_COMFY_URL", "http://127.0.0.1:8188")

# 各家的"口型/说话头像"方案，以及它们需要的权重（名字按社区常见叫法，不保证全）
CANDIDATES = [
    ("Wav2Lip", ("wav2lip",), ("wav2lip", "s3fd", "face_detection")),
    ("LatentSync", ("latentsync",), ("latentsync", "whisper")),
    ("EchoMimic", ("echomimic",), ("echomimic",)),
    ("Sonic", ("sonic",), ("sonic", "whisper")),
    ("Hallo / Hallo2", ("hallo",), ("hallo", "wav2vec")),
    ("Wan2.1 S2V（WanVideoWrapper 那条）", ("wanvideo", "s2v"), ("s2v",)),
    ("MuseTalk", ("musetalk",), ("musetalk",)),
    ("Ditto", ("ditto",), ("ditto",)),
]


def _object_info(url=COMFY, timeout=60):
    try:
        return json.load(urllib.request.urlopen(url.rstrip("/") + "/object_info", timeout=timeout))
    except Exception as e:
        return {"__error__": "%s: %s" % (type(e).__name__, str(e)[:120])}


def _model_dirs():
    """ComfyUI 的模型目录 —— **复用载体自己的目录解析**（video_service/config.py），
    不再自己猜那几个常见路径：本机的 ComfyUI 装在哪是配置说了算的。"""
    dirs = []
    try:
        sys.path.insert(0, os.path.join(ROOT, "video_service"))
        import config as _cfg
        base = None
        for fn in ("find_comfy_dir", "find_comfy"):
            f = getattr(_cfg, fn, None)
            if callable(f):
                try:
                    base = f()
                except Exception:
                    base = None
                if base:
                    break
        if not base:
            base = getattr(_cfg, "VIDEO_ROOT", None) or getattr(_cfg, "COMFY_DIR", None)
        if base and os.path.isdir(base):
            for sub in ("", "models", os.path.join("models", "checkpoints"),
                        os.path.join("models", "diffusion_models"), os.path.join("models", "audio_encoders"),
                        os.path.join("models", "latentsync"), os.path.join("custom_nodes")):
                d = os.path.join(base, sub) if sub else base
                if os.path.isdir(d):
                    dirs.append(d)
        print("ComfyUI 目录（载体自己解析出来的）：%s" % (base or "没解析出来"))
    except Exception as e:
        print("解析 ComfyUI 目录失败（退回环境变量/常见路径）：%s" % e)
    for p in (os.environ.get("XIAOJIAO_COMFY_DIR"), r"C:\ComfyUI",
              r"C:\ComfyUI_windows_portable\ComfyUI"):
        if p and os.path.isdir(p):
            for sub in ("models", ""):
                d = os.path.join(p, sub) if sub else p
                if os.path.isdir(d) and d not in dirs:
                    dirs.append(d)
    return dirs


def main():
    print("=" * 78)
    print("本机「让人物开口说话（口型）」能力核查 —— 只读，不下载任何东西")
    print("=" * 78)
    info = _object_info()
    if "__error__" in info:
        print("❌ 连不上 ComfyUI（%s）：%s" % (COMFY, info["__error__"]))
        print("   → 先让小焦起 ComfyUI（本地视频那条链会自己起），再跑这个脚本。")
        return 2
    names = list(info.keys())
    low = [n.lower() for n in names]
    print("ComfyUI 在跑，节点 %d 个" % len(names))

    dirs = _model_dirs()
    files = []
    for d in dirs:
        if os.path.basename(d.rstrip("\\/")).lower() == "custom_nodes":
            continue          # 代码目录不算"权重"（否则 .py 文件名里的 s2v 会被当成下好了模型）
        try:
            for root, _sub, fs in os.walk(d):
                for f in fs:
                    if os.path.splitext(f)[1].lower() in (".safetensors", ".pth", ".pt", ".bin",
                                                          ".ckpt", ".onnx", ".npz", ".gguf"):
                        files.append(os.path.join(root, f))
        except Exception:
            pass
    lowfiles = [os.path.basename(f).lower() for f in files]
    print("模型目录：%s" % ("、".join(dirs) if dirs else "（没找到 ComfyUI 模型目录）"))
    print("模型文件：%d 个" % len(files))

    print("\n%-34s %-10s %-10s %s" % ("方案", "有节点", "有权重", "结论"))
    print("-" * 78)
    ready = []
    for label, node_keys, weight_keys in CANDIDATES:
        has_node = any(all(k in n for k in node_keys) for n in low)
        has_w = any(any(k in f for k in weight_keys) for f in lowfiles)
        if has_node and has_w:
            verdict, mark = "本机现在就能试", "✅"
            ready.append(label)
        elif has_node and not has_w:
            verdict, mark = "有节点、缺权重（要下载）", "⚠️"
        elif has_w and not has_node:
            verdict, mark = "有权重、缺节点（要装自定义节点）", "⚠️"
        else:
            verdict, mark = "都没有", "❌"
        print("%-34s %-10s %-10s %s %s" % (label, "有" if has_node else "无", "有" if has_w else "无", mark, verdict))

    print("\n" + "=" * 78)
    if ready:
        print("结论：%s 在本机具备条件，可以试（仍要看 8G 显存够不够）。" % "、".join(ready))
    else:
        print("结论：**本机现在没有可用的口型方案** —— 所以「让人物开口说话」这件事，")
        print("      要么走云端（Veo/Kling 那类自带口型的视频 API），要么先下模型（每家 1~8 GB 不等）。")
        print("      我不替你下：一是几个 G，二是 8G 显存跑不跑得动要试了才知道，不能拿'应该能'糊过去。")
    print("另外：现在视频里的'声音'是**载体用他自己的声音念台词**（/api/tts → Chatterbox），")
    print("      那叫'载体替他配音'，**不是**画面里的人物在开口 —— 这两件事别混。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
