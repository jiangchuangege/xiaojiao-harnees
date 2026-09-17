# 保存到项目根目录：readlog.py
# 跑法：python readlog.py 文件名 [行数]
# 例：python readlog.py logs/psyche/impressions.jsonl 5

import json
import sys
import os

def show(path, n=5):
    if not os.path.exists(path):
        print("文件不存在：%s" % path)
        return
    lines = [l for l in open(path, encoding="utf-8", errors="replace") if l.strip()]
    print("=" * 50)
    print("  %s（最后 %d 条）" % (path, n))
    print("=" * 50)
    for ln in lines[-n:]:
        try:
            d = json.loads(ln)
        except Exception:
            print(ln[:200])
            continue
        # 有 event + feeling 的（心起的印象）
        if "feeling" in d:
            print("\n【事】%s" % d.get("event", ""))
            print("【心】%s" % d.get("feeling", ""))
            print("【强】%.2f  【源】%s" % (d.get("intensity", 0), d.get("source", "")))
        # 有 text 的（梦）
        elif "text" in d:
            print("\n🌙 %s" % d.get("text", ""))
        # 其它（energy / heartbeat 之类）
        else:
            kv = {k: v for k, v in d.items() if k not in ("vec",)}
            print("  " + " | ".join("%s=%s" % (k, v) for k, v in kv.items()))
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python readlog.py 文件路径 [行数]")
        print("例：  python readlog.py logs/psyche/impressions.jsonl 5")
        sys.exit(0)
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    show(path, n)