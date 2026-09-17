# -*- coding: utf-8 -*-
"""
载体效果对比测试
同一批问题，问两次：
  A. 裸 4B（什么都不给）
  B. 4B + 载体（画像 + 血管召回）
"""
import sys, time
sys.path.insert(0, ".")
from xiaojiao_app import _local_brain_model, _LOCAL_PROBE
import urllib.request, json
model, base = "xiaojiao", "http://127.0.0.1:9292/v1"
try:
    m = _local_brain_model()
    if m: model = m
    b = _LOCAL_PROBE.get("base")
    if b: base = b
except Exception:
    pass
def chat(messages, temperature=0.7, max_tokens=300):
    url = base.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()
import xiaojiao_recall as R
profiles = R.load_profiles()
print("载体画像库：" + str(len(profiles)) + " 条")
print()
CASES = [
    "晚上想吃点啥",
    "我最近心情不好",
    "推荐部电影",
    "帮我看看这段代码",
    "我该养什么宠物",
    "有什么歌推荐",
    "周末去哪玩好",
    "早上喝什么",
    "最近想学点东西",
    "推荐本书",
]
print("=" * 74)
print("裸 4B  vs  4B + 载体")
print("=" * 74)
for q in CASES:
    print()
    print("👤 " + q)
    print("-" * 74)
    try:
        ans_a = chat([{"role":"user","content":q}], max_tokens=150)
    except Exception as e:
        ans_a = "[" + str(e)[:40] + "]"
    try:
        imps = R.recall(q)
        if imps:
            imp_text = "\n".join("- " + p.get("text","") for p in imps)
            sys_p = ("你是小焦，用户的本地 AI 伙伴。\n\n"
                     "关于这个人，你手上有的信息：\n" + imp_text + "\n\n"
                     "自然地跟他聊。")
        else:
            sys_p = "你是小焦，用户的本地 AI 伙伴。自然地聊。"
        ans_b = chat([
            {"role":"system","content":sys_p},
            {"role":"user","content":q}
        ], max_tokens=150)
        imp_show = " | ".join(p.get("text","")[:16] for p in imps) if imps else "（空）"
    except Exception as e:
        ans_b = "[" + str(e)[:40] + "]"
        imp_show = "（异常）"
    print("【A · 裸 4B】")
    print("  " + ans_a[:200].replace("\n", " "))
    print()
    print("【B · 4B + 载体】")
    print("  召回：" + imp_show)
    print("  " + ans_b[:200].replace("\n", " "))
    print()
print("=" * 74)
print("跑完了。")
print("=" * 74)
