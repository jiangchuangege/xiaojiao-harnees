# -*- coding: utf-8 -*-
"""「模型名对账」自测（离线，不调模型、不联网）：**显示名 ≠ 服务认的 id** 这件事必须被挡住。

【为什么必须钉（用户实测，2026-09-21）】设了预设「闲聊陪伴」之后发消息就报：
    HTTP 404 · 接口地址或模型名不对（服务端说：no router for requested model）
    ｜ 接口 http://127.0.0.1:9292/v1 ｜ 模型 **xiaojiao1.0-4B**
llama-swap 真正认的**路由键是 `xiaojiao`**（`useModelName: xiaojiao1.0-4B` 只是它自报的名字）；
而 `models[]` 里本来就分两列：`name` = 显示名、`model` = **要发给接口的 id**。
`brain.api.model` 被写成了显示名 → 每次请求 404，界面上还看不出为什么。

这里钉四件事：
  ① 名字 → id 的映射（同名条目取它的 `model` 字段）；
  ② 已经是 id 就原样返回；空值/空 ids 返回空串（不猜）；
  ③ 兜底时**优先 `xiaojiao`**、并且**绝不随手拿 `ids[0]`**（实测顺序里 coder 在前，
     而那个 coder 的 gguf 早就不在了，请求它 = HTTP 500）；
  ④ `_local_model_reconcile()` 只在"引擎本地 + 地址本地 + 名字不在服务列表里"时才改，
     改完写回**临时**控制文件（自测绝不碰用户真配置），而且**只试一次**。
"""
import io
import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as A  # noqa: E402

PASS, FAIL = [], []

# 用户那台机器上真实的样子（llama-swap 的 /v1/models 顺序与内容都照抄）
IDS = ["coder", "deepseek-v4", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "xiaojiao"]
ENTRIES = [
    {"name": "xiaojiao1.0-4B", "engine": "llama", "base_url": "http://127.0.0.1:9292/v1",
     "api_key": "", "model": "xiaojiao"},
    {"name": "agnes-2.5-flash", "engine": "api", "base_url": "https://apihub.agnes-ai.com/v1",
     "api_key": "sk-x", "model": "agnes-2.5-flash"},
    {"name": "coder", "engine": "llama", "base_url": "http://127.0.0.1:9292/v1",
     "api_key": "", "model": "coder"},
]


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:160]) if info else ""))


def main():
    tmpd = tempfile.mkdtemp(prefix="xj_modelrec_")
    ctl = os.path.join(tmpd, "xiaojiao_control.json")
    old = {k: getattr(A, k, None) for k in ("_CONTROL_FILE", "_LOCAL_MODEL_RECONCILED",
                                            "BRAIN_ENGINE", "LLM_BASE", "LLM_MODEL")}
    old_get, old_ids, old_ctl = A._get_models, A._local_served_ids, A.CONTROL
    old_dead = getattr(A, "_dead_local_models", None)
    try:
        A._CONTROL_FILE = ctl
        A._get_models = lambda: list(ENTRIES)

        print("一、名字 → 服务认的 id")
        ck("显示名 xiaojiao1.0-4B → xiaojiao（同名条目取 model 字段）",
           A._model_id_for("xiaojiao1.0-4B", IDS) == "xiaojiao",
           A._model_id_for("xiaojiao1.0-4B", IDS))
        ck("已经是 id → 原样返回", A._model_id_for("xiaojiao", IDS) == "xiaojiao")
        ck("别的真实 id 也原样返回", A._model_id_for("deepseek-v4", IDS) == "deepseek-v4")
        ck("空值 / 空 ids → 空串（不猜）",
           A._model_id_for("", IDS) == "" and A._model_id_for("xiaojiao", []) == "")

        print("\n二、兜底不许踩坑")
        ck("认不出来的名字 → 兜底 xiaojiao（本项目默认大脑）",
           A._model_id_for("某个不存在的名字", IDS) == "xiaojiao")
        # 【判据是"文件还在不在"这个事实，不是"名字里带不带 coder"这个猜】
        #   实测：这台机器上 `qwopus3.5-4b-coder-mtp-q5_k_m.gguf` 名字里也带 coder，却被正常用着；
        #   而 `coder` 路由的 gguf 一度真的不在（请求它 = HTTP 500 upstream exited prematurely）。
        A._dead_local_models = lambda: {"coder"}
        ck("兜底时跳过「模型文件已经不在」的那个（按事实，不按名字）",
           A._model_id_for("x", ["coder", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf"]) ==
           "qwopus3.5-4b-coder-mtp-q5_k_m.gguf",
           A._model_id_for("x", ["coder", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf"]))
        A._dead_local_models = lambda: set()
        ck("没有死模型时按服务给的顺序取第一个",
           A._model_id_for("x", ["coder", "deepseek-v4"]) == "coder")
        A._dead_local_models = lambda: {"coder", "deepseek-v4"}
        ck("全都不在时也返回一个（不返回空）",
           A._model_id_for("x", ["coder", "deepseek-v4"]) == "coder")

        print("\n三、`_local_served_model` 用同一套映射（切模型那条路）")
        A._local_served_ids = lambda base, timeout=3: list(IDS)
        m, ids = A._local_served_model("http://127.0.0.1:9292/v1", "xiaojiao1.0-4B")
        ck("按显示名来 → 换成 xiaojiao", m == "xiaojiao", (m, ids))
        m2, _ = A._local_served_model("http://127.0.0.1:9292/v1", "coder")
        ck("本来就对的名字不动", m2 == "coder", m2)

        print("\n四、`_local_model_reconcile()`：只在真需要时改，改完写回临时文件，只试一次")
        A.CONTROL = {"preset": "闲聊陪伴", "brain": {"engine": "llama", "llama_swap_port": 9292,
                                                     "api": {"base_url": "http://127.0.0.1:9292/v1",
                                                             "api_key": "", "model": "xiaojiao1.0-4B"}},
                     "_engine": {"keep": True}}
        io.open(ctl, "w", encoding="utf-8").write(json.dumps(A.CONTROL, ensure_ascii=False))
        A.BRAIN_ENGINE, A.LLM_BASE, A.LLM_MODEL = "llama", "http://127.0.0.1:9292/v1", "xiaojiao1.0-4B"
        A._LOCAL_MODEL_RECONCILED = False
        note = A._local_model_reconcile()
        ck("改了：显示名 → xiaojiao", A.LLM_MODEL == "xiaojiao", A.LLM_MODEL)
        ck("说明了改了什么、为什么", ("xiaojiao1.0-4B" in note and "xiaojiao" in note), note)
        saved = json.load(io.open(ctl, encoding="utf-8"))
        ck("写回了控制文件", (saved.get("brain", {}).get("api", {}).get("model") == "xiaojiao"),
           saved.get("brain"))
        ck("**没弄丢别的键**（preset / _engine 还在）",
           saved.get("preset") == "闲聊陪伴" and saved.get("_engine") == {"keep": True}, sorted(saved))
        ck("只试一次：再调返回空", A._local_model_reconcile() == "")

        print("\n五、不需要改的时候一个字都不动")
        A._LOCAL_MODEL_RECONCILED = False
        A.LLM_MODEL = "xiaojiao"
        ck("名字本来就对 → 不改", A._local_model_reconcile() == "" and A.LLM_MODEL == "xiaojiao")
        A._LOCAL_MODEL_RECONCILED = False
        A.BRAIN_ENGINE = "api"
        A.LLM_MODEL = "xiaojiao1.0-4B"
        ck("引擎是云端 → 不管它（本地这套判据不该插手云端）",
           A._local_model_reconcile() == "" and A.LLM_MODEL == "xiaojiao1.0-4B")
        A._LOCAL_MODEL_RECONCILED = False
        A.BRAIN_ENGINE = "llama"
        A._local_served_ids = lambda base, timeout=3: []
        ck("服务问不到（没起）→ 不算对过账，也不改",
           A._local_model_reconcile() == "" and A._LOCAL_MODEL_RECONCILED is False)
    finally:
        A._get_models, A._local_served_ids, A.CONTROL = old_get, old_ids, old_ctl
        if old_dead is not None:
            A._dead_local_models = old_dead
        for k, v in old.items():
            if v is None:
                try:
                    delattr(A, k)
                except AttributeError:
                    pass
            else:
                setattr(A, k, v)
        import shutil
        shutil.rmtree(tmpd, ignore_errors=True)

    print("\n" + "=" * 66)
    print("模型名对账自测：通过 %d / 共 %d%s"
          % (len(PASS), len(PASS) + len(FAIL), ("　失败：" + str(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
