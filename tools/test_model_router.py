# -*- coding: utf-8 -*-
"""难度路由 · 自测（离线、确定性；不需要真调模型）

钉住的是**换档不乱换**，因为换错的代价很大（llama-swap 切模型要冷启动 20~50 秒）：
  ① 判据：闲聊/简单 → fast；写代码 → code；重推理且够长 → strong；
  ② 粘性：同一档在有效期内不换模型（防止来回切导致反复加载）；
  ③ 换档：只有档变了、且已过粘性时间才换；
  ④ 兜底：目标档的模型不在可用列表 → 退到该档备选 → 再退 fast；
  ⑤ 探不到模型列表（服务没起）→ 返回空，调用方按原配置走，绝不发 404。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  难度路由自测（离线）")
    print("=" * 80)
    from core import model_router as MR      # noqa: E402

    REAL_IDS = {"xiaojiao", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder", "deepseek-v4"}

    def reset():
        MR.STATE.update({"tier": "fast", "model": "", "at": 0.0})

    def fake_ids(ids):
        MR.available_models = lambda force=False: set(ids)

    # ---------------- 一、判据 ----------------
    print("\n[一] 这一句该走哪个档（字面 + 长度，不问模型自己）")
    ck("闲聊 → fast", MR.pick_tier("你好呀")[0] == "fast", MR.pick_tier("你好呀"))
    ck("小数比较 → fast（实测 4B 就答对了，没必要等 30 秒）",
       MR.pick_tier("3.11 和 3.9 哪个大")[0] == "fast")
    ck("写快排 → code", MR.pick_tier("帮我写一个 Python 快速排序函数")[0] == "code")
    ck("报错排查 → code", MR.pick_tier("这段代码报错了 Traceback 怎么改")[0] == "code")
    ck("重推理且够长 → strong",
       MR.pick_tier("为什么这个架构要拆成微服务，对比一下两种方案的利弊")[0] == "strong")
    ck("短句里有'为什么'但太短 → 不当重活",
       MR.pick_tier("为什么")[0] == "fast", MR.pick_tier("为什么"))
    ck("很长的普通描述 → strong（长度判据）",
       MR.pick_tier("x" * (MR._HEAVY_LEN + 5))[0] == "strong")
    ck("意图=code 也走 code 档", MR.pick_tier("随便什么", intent="code")[0] == "code")

    # ---------------- 二、粘性 ----------------
    print("\n[二] 粘性：同一档在有效期内不换（切模型要冷启动 20~50 秒）")
    fake_ids(REAL_IDS)
    reset()
    m1, t1, _ = MR.route("帮我写一个 Python 函数", now=1000.0)
    ck("第一次：写代码 → code 档", t1 == "code" and m1.startswith("qwopus"), (m1, t1))
    m2, t2, why2 = MR.route("写个脚本", now=1010.0)
    ck("10 秒内再问代码 → 沿用同一模型（不重新加载）", m2 == m1 and "粘性" in why2, why2)
    m3, t3, why3 = MR.route("你好呀", now=1020.0)
    ck("20 秒内问闲聊 → 降档要等冷却，先沿用 code 档", t3 == "code", why3)
    m4, t4, why4 = MR.route("你好呀", now=1000.0 + MR._SWITCH_S + 5)
    ck("过了降档冷却 → 换回 fast（闲聊就该用最快的）",
       t4 == "fast" and m4 == "xiaojiao", (m4, t4, why4))
    # 升档：活儿变重了就该立刻切（第一版把升档也压住，等于永远让 4B 干重活）
    reset()
    MR.route("你好呀", now=2000.0)
    m5, t5, why5 = MR.route("帮我写一个 Python 函数", now=2005.0)
    ck("5 秒内从闲聊转写代码 → 立即升到 code 档（不等冷却）",
       t5 == "code" and m5.startswith("qwopus"), (m5, t5, why5))

    # ---------------- 三、兜底 ----------------
    print("\n[三] 兜底：目标模型不在列表里就退，绝不把请求发进 404")
    reset()
    fake_ids({"xiaojiao"})                       # 只有 fast
    m5, t5, why5 = MR.route("帮我写一个 Python 函数", now=5000.0)
    ck("要 code 档但机器上只有 xiaojiao → 退回 fast 并用 xiaojiao",
       m5 == "xiaojiao" and t5 == "fast", (m5, t5, why5))
    reset()
    fake_ids(set())                              # 一个都探不到
    m6, t6, why6 = MR.route("帮我写一个 Python 函数", now=6000.0)
    ck("探不到模型列表 → 返回空（调用方按原配置走）", m6 == "", (m6, why6))
    reset()
    fake_ids({"coder", "deepseek-v4"})           # 没有 xiaojiao 也没有 qwopus
    m7, t7, _ = MR.route("你好呀", now=7000.0)
    ck("fast 档首选不在 → 用该档备选（coder）", m7 == "coder", m7)
    reset()
    fake_ids({"deepseek-v4"})
    m8, t8, _ = MR.route("帮我写一个 Python 函数", now=8000.0)
    ck("code 档的模型全不在 → 用 fast 档有的（deepseek-v4）", m8 == "deepseek-v4", m8)

    # ---------------- 四、真机（只读探测，不换档） ----------------
    print("\n[四] 真机：现在这台机器上探到的模型")
    import importlib
    importlib.reload(MR)
    ids = MR.available_models(force=True)
    ck("能探到可用模型列表（llama-swap 在跑）", len(ids) >= 1, sorted(ids))
    if ids:
        ck("路由给出的模型一定在可用列表里", MR.route("帮我写一个 Python 函数", now=9000.0)[0] in ids,
           MR.route("帮我写一个 Python 函数", now=9000.0))
        ck("current() 能自报当前档位与可用模型",
           "tier" in MR.current() and MR.current().get("available"), MR.current())

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
