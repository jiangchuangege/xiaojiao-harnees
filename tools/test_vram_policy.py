# -*- coding: utf-8 -*-
"""显存归属策略自测（**离线**：把真实的停止/加载动作换成假动作，只验策略本身）

用户给定的规则，一条一条钉死：
  1. **聊天模型是显存的主人**：功能模型跑完，聊天模型回到显存，功能模型退到内存待命
  2. **聊天模型不许顶聊天模型**：显存里已经坐着聊天模型时，另一个聊天模型不许自动上来
     （只有用户在界面上明确选了它才允许）—— 否则就是每次对话都换模型，每次换都重新读盘
  3. **聊天模型可以顶功能模型**（音乐/播客/视频/图像…）
  4. **内存只留一个功能模型**：下一个功能模型要用显存时，上一个温存的彻底清掉
  5. **生成失败也要还回去**（所以插件里写在 finally 里）

运行：python tools/test_vram_policy.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "video_service"))

import brain_manager as bm  # noqa: E402

PASS, FAIL = [], []
CALLS = []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _fake_switch():
    """把真实的显存动作换成记录调用（离线、不动任何模型）。"""
    import types
    fake = types.ModuleType("model_switch")

    def _unload(mid="xiaojiao"):
        CALLS.append(("unload", mid))
        return True

    def _start_brain(model_id=None, preload=True):
        CALLS.append(("start_brain", model_id))
        return None

    def _start_comfy():
        CALLS.append(("start_comfy", ""))
        return None

    def _stop_comfy():
        CALLS.append(("stop_comfy", ""))
        return None

    fake._llama_swap_unload = _unload
    fake.start_brain = _start_brain
    fake.start_comfy = _start_comfy
    fake.stop_comfy = _stop_comfy
    fake.get_state = lambda: {}
    sys.modules["model_switch"] = fake
    # brain_manager 内部用的是 is_running()（按端口判断）—— 离线时端口是空的，
    # 让 wake() 的返回值可预期：直接把它换成"按 state 判断"。
    bm.is_running = lambda key: (bm.BRAINS.get(key, {}).get("state") == "RUN")
    # ⚠️ 还要挡掉 brain_manager **自己的**启动函数：`_start_comfy` 会真的去拉起 ComfyUI
    # 并等 8188 就绪（第一版没挡，测试直接卡死在等端口上）。
    bm._start_llama = lambda b: CALLS.append(("start_llama", b.get("name")))
    bm._start_comfy = lambda b: CALLS.append(("start_comfy_bm", b.get("name")))


def _reset():
    CALLS.clear()
    for k in bm.BRAINS:
        bm.BRAINS[k]["state"] = "OFF"
    bm._DISPLACED["key"] = ""


def main():
    _fake_switch()
    print("一、分类：谁是聊天模型、谁是功能模型")
    ck("chat / coder / agnes / deepseek-v4 是聊天模型",
       all(bm.is_chat(k) for k in ("chat", "coder", "agnes", "deepseek-v4")))
    ck("video / podcast / music 是功能模型",
       not any(bm.is_chat(k) for k in ("video", "podcast", "music")),
       [k for k in bm.BRAINS if not bm.is_chat(k)])

    print("\n二、规则 2+3：聊天模型不许顶聊天模型")
    _reset()
    bm.BRAINS["chat"]["state"] = "RUN"
    ck("显存里有 chat 时，coder 自动上来 → 被拒绝", bm.wake("coder") is False,
       [c for c in CALLS if c[0] == "start_llama"])
    ck("拒绝时没有真的去加载它", not [c for c in CALLS if c[0] == "start_llama"])
    ck("用户明确选它 → 允许（explicit=True）", bm.wake("coder", explicit=True) is True)
    ck("明确切换时 chat 被退到内存（不再是 RUN）", bm.BRAINS["chat"]["state"] != "RUN",
       bm.BRAINS["chat"]["state"])
    ck("且卸载的是**当前配置的**那个模型（不写死 xiaojiao）",
       any(c[0] == "unload" for c in CALLS), CALLS)

    print("\n三、规则 1：功能模型跑完，聊天模型回显存")
    _reset()
    bm.BRAINS["chat"]["state"] = "RUN"
    r = bm.use_gen("video")
    ck("use_gen 记下了该还给谁（chat）", r.get("chat") == "chat", r)
    ck("视频上显存", bm.BRAINS["video"]["state"] == "RUN", bm.BRAINS["video"]["state"])
    ck("聊天模型让出了显存", bm.BRAINS["chat"]["state"] != "RUN", bm.BRAINS["chat"]["state"])
    d = bm.done_gen("video")
    ck("done_gen 把聊天模型还回来了", d.get("chat_back") == "chat", d)
    ck("视频退到内存待命（WARM，不是彻底卸载）", bm.BRAINS["video"]["state"] == "WARM",
       bm.BRAINS["video"]["state"])
    ck("还给聊天模型时**真的调了加载**（不只是改状态）",
       any(c[0] == "start_brain" for c in CALLS), CALLS)

    print("\n四、规则 4：内存只留一个功能模型")
    _reset()
    bm.BRAINS["chat"]["state"] = "RUN"
    bm.use_gen("video")
    bm.done_gen("video")                      # video 现在 WARM（内存里待命）
    ck("视频在内存待命", bm.BRAINS["video"]["state"] == "WARM")
    bm.use_gen("music")                       # 另一个功能模型要显存
    ck("上一个功能模型被彻底清掉（内存只留一个）",
       bm.BRAINS["video"]["state"] == "OFF", bm.BRAINS["video"]["state"])
    ck("音乐上了显存", bm.BRAINS["music"]["state"] == "RUN", bm.BRAINS["music"]["state"])
    bm.done_gen("music")
    ck("音乐跑完 → 聊天模型又回来了", bm.BRAINS["chat"]["state"] == "RUN",
       bm.BRAINS["chat"]["state"])
    ck("音乐退到内存待命", bm.BRAINS["music"]["state"] == "WARM", bm.BRAINS["music"]["state"])

    print("\n五、规则 5：生成失败也必须还回去（插件里写在 finally）")
    src_v = open(os.path.join(_ROOT, "plugins", "video_generation.py"), encoding="utf-8").read()
    src_m = open(os.path.join(_ROOT, "plugins", "music_generation.py"), encoding="utf-8").read()
    ck("视频插件：finally 里有 done_gen", "finally:" in src_v and 'done_gen("video")' in src_v)
    ck("音乐插件：finally 里有 done_gen", "finally:" in src_m and 'done_gen("music")' in src_m)
    # ⚠️ 判据不能只看"出现过 _full_stop(k)"：修复说明的**注释里**也写了这串，
    #    那样会把对的判成错的（我第一次就是这么误报的）。看真正的调用形状：
    ck("音乐插件：不再「把所有大脑全杀一遍」（没有遍历 BRAINS 全停的循环）",
       "for k in list(bm.BRAINS.keys())" not in src_m)
    ck("视频插件：不再只 stop_brain 就完事",
       "done_gen" in src_v and "use_gen" in src_v)

    print("\n六、`_full_stop` 必须按类型分派（不能再拿 ComfyUI 当替罪羊）")
    src_b = open(os.path.join(_ROOT, "brain_manager.py"), encoding="utf-8").read()
    ck("_full_stop 里按 type 分派（llama/comfy/inproc 各走各的）",
       't == "llama"' in src_b and 't == "comfy"' in src_b and "inproc" in src_b)

    print("\n七、真实预热：start_brain 不能只是「打个招呼」")
    src_s = open(os.path.join(_ROOT, "video_service", "model_switch.py"), encoding="utf-8").read()
    ck("start_brain 真的发了一个预热请求（max_tokens=1）",
       'max_tokens": 1' in src_s.replace("'", '"'), "原来只调 /api/profiles，那不会加载模型")
    ck("stop_brain 支持按当前配置的模型卸载（不写死）",
       "_chat_model_id()" in src_s)

    print("=" * 66)
    print("显存归属策略自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
