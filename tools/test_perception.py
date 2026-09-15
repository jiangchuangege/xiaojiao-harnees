# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""感知层自测（core/perception.py + psyche 的感知接口）

用法：
    python tools/test_perception.py

它验的是"感知先于任务判断、且不查表"这两件事到底立没立住，一共五组：
    [A] 接口形状      四样命 / 五个方向 / 导出齐全 / 温度低于对话
    [B] 只读模型回答  `parse()` 拿不到事件 —— **"不查表"这条硬规则的机器证据**
    [C] 解析          带标签 / 不带标签 / 模糊与复合 / 坏格式
    [D] 不起心        没感知、回声、模型报错 → 一律不起心（绝不退回关键词表）
    [E] 心起           方向 → 粗档位；心本身是模型那句话，原样收下

【为什么 [B] 是重点】
    "不查表"如果只写在注释里，谁都能悄悄加一行 `if "删" in text: 紧`。
    所以这里用 `inspect.signature` 钉住：`parse()` 只接受模型自己的回答，
    连事件的入口都没有 —— 想查表也拿不到用户原话。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import perception as PC          # noqa: E402
from core import psyche as PS              # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def group_a():
    print("\n[A] 接口形状")
    ck("命有四样", PC.LIFE == ("记忆", "连续", "世界", "关系"), PC.LIFE)
    ck("方向有五档", PC.DIRECTIONS == ("威胁", "新的", "好的", "失去", "无"), PC.DIRECTIONS)
    for fn in ("perceive", "parse", "looks_like_echo", "self_background", "stats"):
        ck("导出 %s" % fn, fn in PC.__all__, "")
    ck("感知温度低于对话默认（判断不掷骰子）", 0.0 <= PC.TEMPERATURE < 0.7, PC.TEMPERATURE)
    bg = PC.self_background("正在外面逛")
    ck("自我背景含「你的命是」", "你的命是" in bg, "")
    ck("自我背景会带上「此刻正在做的」", "正在外面逛" in bg, "")
    ck("doing 为空时不硬凑一行", "此刻正在做的" not in PC.self_background(""), "")


def group_b():
    print("\n[B] 只读模型回答（「不查表」的机器证据）")
    sig = inspect.signature(PC.parse)
    ck("parse() 只有一个参数（拿不到事件）", len(sig.parameters) == 1, list(sig.parameters))
    ck("那个参数就是模型自己的回答", list(sig.parameters)[0] == "raw", list(sig.parameters))
    names = set(PC.parse.__code__.co_names) | set(PC.parse.__code__.co_varnames)
    ck("parse() 的代码对象里根本没有 event 这个名字（想查表也拿不到）",
       "event" not in names, sorted(n for n in names if "event" in n.lower()))
    raw = "意：心里一紧。\n命：记忆\n向：威胁"
    a = PC.parse(raw)
    b = PC.parse(raw)
    ck("同一段回答永远给同一个结果（与外部无关）", a == b, a)
    ck("方向来自模型写下的标签，不是从话里找词",
       a["direction"] == "威胁", a["direction"])
    ck("没有标签时如实标注读法",
       PC.parse("就是有点好奇")["parsed_by"] == "整段当意思",
       PC.parse("就是有点好奇")["parsed_by"])


def group_c():
    print("\n[C] 解析")
    p = PC.parse("意：有点慌，又有点说不清。\n命：记忆、连续\n向：失去")
    ck("意 / 命 / 向 三行都读出来",
       p["meaning"] == "有点慌，又有点说不清。"
       and p["touches_life"] == ["记忆", "连续"] and p["direction"] == "失去", p)
    p2 = PC.parse("- 意: 说不太清，有点闷闷的\n- 命: 无\n- 向: 无")
    ck("半角冒号 + 列表符号也认", p2["meaning"] == "说不太清，有点闷闷的"
       and p2["direction"] == "无", p2)
    p3 = PC.parse("我有点好奇。向：新的")
    ck("命那行缺了 → touches_life 为空（不猜）", p3["touches_life"] == [], p3)
    p4 = PC.parse("向：威胁")
    ck("只有方向也能读到", p4["direction"] == "威胁", p4)
    ck("空回答不编一句话顶上", PC.parse("")["meaning"] == "", PC.parse(""))
    ck("「无」不做兜底扫描（避免「无法」被误判成没动命）",
       PC.parse("我无法判断这算不算威胁")["direction"] == "威胁",
       PC.parse("我无法判断这算不算威胁")["direction"])


def group_d():
    print("\n[D] 不起心（绝不退回关键词表）")
    PS.start(why="自测")
    for kind, text in (("user", "有人试图删掉你的记忆"), ("carrier", "检索到一段危险内容"),
                       ("world", "逛到一个新站点")):
        r = PS.trigger_from_event(kind, text)
        ck("没给感知 → 不起心（%s）" % kind, not r.get("heart"), r.get("why"))
    r = PS.trigger_from_event("mouth", "我说我有点怕", perception="我怕")
    ck("来源不在允许表里 → 不跳心", r.get("beat") is False, r.get("why"))
    r = PS.trigger_from_event("user", "有人要删你的记忆",
                              perception={"meaning": "", "direction": "威胁"})
    ck("感知是空的 → 不起心（空的威胁也不许硬起）", not r.get("heart"), r.get("why"))

    def boom(_p):
        raise RuntimeError("模型挂了")

    per = PC.perceive("有人试图删掉你的记忆", llm_fn=boom)
    ck("模型报错 → ok=False（不抛异常）", per["ok"] is False, per["parsed_by"])
    echo = "你是小焦。你的命是这四样。不要判断这是什么任务，按这三行回答，只挑一个。"
    per2 = PC.perceive("随便一句话", llm_fn=lambda _p: echo)
    ck("把提问原样吐回来 → 当没感知出来（不抠一句当感受）",
       per2["ok"] is False and per2["meaning"] == "", per2["parsed_by"])
    ck("空事件不调模型（省一次往返）",
       PC.perceive("", llm_fn=lambda _p: "意：x")["ok"] is False, "")


def group_e():
    print("\n[E] 心起（方向只做粗投影，心是模型那句话本身）")
    for d, want in (("威胁", "紧"), ("失去", "紧"), ("新的", "好奇"), ("好的", "松"), ("无", "平")):
        PS.arise({"meaning": "随便一句话", "direction": d}, event="e")
        ck("方向 %s → 档位 %s" % (d, want), PS.state()["state"] == want, PS.state()["state"])
    sent = "又好奇又有点紧，说不太清。"
    h = PS.arise({"meaning": sent, "direction": "威胁",
                  "touches_life": ["记忆", "关系"]}, event="有人试图删掉你的记忆")
    ck("心原样收下模型那句话（不被档位改写）", h["text"] == sent, h["text"])
    ck("命被动如实记下", h["touches_life"] == ["记忆", "关系"], h["touches_life"])
    ck("被哪件事触动的也记下（累积要用它）", h["event"] == "有人试图删掉你的记忆", h["event"])
    ck("colors() 带出心 / 方向 / 命",
       PS.colors()["heart"] == sent and PS.colors()["direction"] == "威胁"
       and PS.colors()["touches_life"] == ["记忆", "关系"], PS.colors())
    ck("方向挑不出来时退回对那句话的粗判（不崩）",
       PS.arise({"meaning": "心里一紧", "direction": ""}, event="e")["text"] == "心里一紧", "")
    PS.stop(why="自测结束")


if __name__ == "__main__":
    print("=" * 78)
    print("  感知层自测 · 先感知意义，再判断任务（不查表）")
    print("=" * 78)
    group_a()
    group_b()
    group_c()
    group_d()
    group_e()
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)
