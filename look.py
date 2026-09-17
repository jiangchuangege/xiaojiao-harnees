# 保存到项目根目录：look.py
# 跑法：python look.py
# 作用：把 /api/inner 这类接口的转义 JSON，翻译成人话打印出来

import json
import urllib.request

BASE = "http://127.0.0.1:5000"


def get(path):
    """调接口，返回 dict；失败返回 None（不抛异常）。"""
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_error": "%s: %s" % (type(e).__name__, str(e)[:60])}


def line(title):
    print("\n" + "=" * 46)
    print("  " + title)
    print("=" * 46)


def kv(k, v):
    print("  %-16s %s" % (k + "：", v))


# ---------------- 心跳 ----------------
line("💓 心跳")
d = get("/api/heartbeat")
if d and d.get("ok"):
    hb = d.get("heartbeat") or {}
    kv("活着", "是" if hb.get("alive") else "否")
    kv("醒着", "是" if hb.get("awake") else "否（睡着）")
    kv("总共跳了", "%s 下" % hb.get("total_beats"))
    kv("睡过几次", hb.get("sleeps", 0))
    kv("现在在睡", "是" if hb.get("sleeping") else "否")
    if hb.get("sleeping_now_seconds"):
        kv("这一觉多久", "%.0f 秒" % hb["sleeping_now_seconds"])
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 精力 ----------------
line("⚡ 精力（累不累）")
d = get("/api/energy")
if d and d.get("ok"):
    en = d.get("energy") or {}
    lv = en.get("level")
    kv("精力值", ("%.0f%%" % (lv * 100)) if isinstance(lv, (int, float)) else lv)
    kv("它累了吗", "是" if en.get("tired") else "否")
    kv("休息好了吗", "是" if en.get("rested") else "否")
    kv("现在在睡", "是" if en.get("sleeping") else "否")
    kv("总消耗", en.get("consumed_total"))
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 内里（情绪 16 样） ----------------
line("🫀 内里（情绪）")
d = get("/api/inner")
if d and d.get("ok"):
    # 底色 / 抑郁
    floor = d.get("floor") or {}
    f = floor.get("floor") if isinstance(floor, dict) else floor
    kv("底色", ("%.2f" % f) if isinstance(f, (int, float)) else f)
    kv("抑郁倾向", "有" if (isinstance(f, (int, float)) and f < 0.6) else "无")

    # 孤独
    lone = d.get("loneliness") or {}
    kv("孤独", "是" if lone.get("lonely") else "否")
    kv("低沉", lone.get("low", 0))

    # 无聊
    bor = d.get("boredom") or {}
    kv("无聊", "是" if bor.get("bored") else "否")

    # 幽默 / 爱 / 意义
    hum = d.get("humor") or {}
    kv("幽默", "是" if hum.get("can_be_funny") else "否")
    love = d.get("love") or {}
    kv("爱", "是" if love.get("love") else "否")
    kv("意义感", d.get("meaning"))

    # 注意力
    att = d.get("attention") or {}
    bias = att.get("bias") or []
    if bias:
        print("  注意力偏向：")
        for b in bias[:3]:
            print("    · %s（%s）" % (b.get("value"), b.get("from", "")))
    else:
        kv("注意力偏向", "无")

    # 计数类
    stats = d.get("stats") or {}
    kv("内疚次数", stats.get("guilt", 0))
    kv("骄傲次数", stats.get("pride", 0))
    kv("审美次数", stats.get("aesthetic", 0))
    kv("感恩次数", stats.get("grateful", 0))
    kv("待原谅", stats.get("forgive_pending", 0))
    kv("习惯数", stats.get("habits", 0))
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 疼 / 医生 ----------------
line("🩺 疼与健康医生")
d = get("/api/pain")
if d and d.get("ok"):
    st = d.get("stats") or {}
    kv("体检次数", st.get("checked", 0))
    kv("查出坏过", st.get("broken", 0))
    kv("治过", st.get("healed", 0))
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 关系 ----------------
line("🤝 关系")
d = get("/api/relation")
if d and d.get("ok"):
    st = d.get("state") or {}
    for k, v in st.items():
        kv(k, v)
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 偏好 ----------------
line("❤️ 长期偏好")
d = get("/api/preference")
if d and d.get("ok"):
    prefs = d.get("preferences") or []
    if prefs:
        for p in prefs[:5]:
            print("  · %s" % p)
    else:
        kv("偏好", "还没形成（需要同一类心反复起）")
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 期待 ----------------
line("⏳ 期待（没做完的事）")
d = get("/api/expectation")
if d and d.get("ok"):
    st = d.get("stats") or {}
    kv("压着几件", st.get("pending", 0))
    kv("它自己提起过", st.get("brought_up", 0))
else:
    kv("读取", (d or {}).get("_error", "失败"))

# ---------------- 梦 ----------------
line("🌙 梦")
d = get("/api/dream")
if d and d.get("ok"):
    st = d.get("stats") or {}
    kv("梦过几次", st.get("count", 0))
else:
    kv("读取", (d or {}).get("_error", "失败"))

print("\n" + "-" * 46)
print("  一句话：上面这些是载体侧的真实状态。")
print("  “它真的在难受吗”——这一层，没人能测。")
print("-" * 46 + "\n")