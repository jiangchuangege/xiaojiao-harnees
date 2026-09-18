# -*- coding: utf-8 -*-
"""外部路径解析自测（离线）：**换台机器不改代码也能跑** 这件事得钉住。

【为什么必须钉】这些路径以前是写死的（`llama-swap.yaml`、`brain_manager.py`、
两个浏览器自测、播客的 SD 模型，以及"一键添加本地模型"写新路由时），
用户的原话是「死路径别人有点不太愿意」。现在统一走 `core/paths.py`，顺序是
**环境变量 > PATH/项目/常见目录 > 深搜**，所以这里逐条钉：
  ① 环境变量必须压过自动探测（用户自己指定优先）；
  ② 环境变量指向不存在的路径时**如实说"不存在"**，不许悄悄回落成"没找到"（那是两回事）；
  ③ 自动探测真能找到放好的文件；GGUF 里名字带 xiaojiao 的优先；
  ④ 什么都没有时返回空串，且提示里**明写该设哪个环境变量**（不写"请自行配置"这种空话）；
  ⑤ `llama-swap.yaml` 改写：dry-run 一个字节不动；apply 只改"指向不存在的文件"的那几条，
     其余行（`-c 20000 --reasoning off`、注释、路由名）**原样保留**；先备份；再跑一次为空（幂等）。

跑法：python tools/test_paths.py（全用临时目录，**不碰真的 llama-swap.yaml**）
"""
import io
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import paths as P  # noqa: E402

PASS, FAIL = [], []
ENVS = ["XIAOJIAO_LLAMA_SERVER", "XIAOJIAO_GGUF", "XIAOJIAO_LLAMA_SWAP",
        "XIAOJIAO_CHROME", "XIAOJIAO_SD_MODEL"]


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:160]) if info else ""))


YAML = """# 头部注释不许被动
healthCheckTimeout: 300
models:
  good:
    cmd: 'C:/llama/llama-server.exe --port ${PORT} --model "%s" -c 20000 --reasoning off'
    ttl: 0
    useModelName: good
  broken:
    # 这条指向的文件不存在 —— 应该被换成探测到的
    cmd: 'D:/nowhere/llama-server.exe --port ${PORT} --model "D:/nowhere/missing.gguf" -c 20000 --reasoning off'
    ttl: 0
    useModelName: broken
"""


def main():
    tmp = tempfile.mkdtemp(prefix="xj_paths_")
    old_env = {k: os.environ.get(k) for k in ENVS}
    old_dirs, old_roots, old_which = P._cand_dirs, P._ROOTS, shutil.which
    try:
        for k in ENVS:
            os.environ.pop(k, None)
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)

        print("一、环境变量优先（用户自己指定压过自动探测）")
        fake_chrome = os.path.join(tmp, "my-chrome.exe")
        io.open(fake_chrome, "w").close()
        os.environ["XIAOJIAO_CHROME"] = fake_chrome
        p1, how1 = P.find_chrome()
        ck("环境变量命中", os.path.normcase(p1) == os.path.normcase(fake_chrome), p1)
        ck("说明里写明是环境变量", "环境变量 XIAOJIAO_CHROME" in how1, how1)

        print("\n二、环境变量指向不存在的路径 → 如实说「不存在」，不静默回落")
        os.environ["XIAOJIAO_CHROME"] = os.path.join(tmp, "nope.exe")
        p2, how2 = P.find_chrome()
        ck("返回空", p2 == "", p2)
        ck("说明里点出「不存在」", "不存在" in how2 and "XIAOJIAO_CHROME" in how2, how2)
        os.environ.pop("XIAOJIAO_CHROME", None)

        print("\n三、自动探测：放好的文件能找到；GGUF 里带 xiaojiao 的优先")
        P._cand_dirs = lambda: [empty]
        P._ROOTS = [tmp]
        open(os.path.join(empty, "llama-server.exe"), "w").close()
        p3, how3 = P.find_llama_server()
        ck("在项目/常见目录里找到 llama-server", p3.endswith("llama-server.exe"), p3)
        ck("说明里给出是哪个目录", "找到" in how3, how3)
        io.open(os.path.join(empty, "other-model.gguf"), "w").close()
        io.open(os.path.join(empty, "xiaojiao1.0-4B.gguf"), "w").close()
        p4, how4 = P.find_gguf()
        ck("官方同名优先", p4.endswith("xiaojiao1.0-4B.gguf"), p4)
        ck("路径是正斜杠（跟 llama-swap.yaml 一致）", "\\" not in p4, p4)

        print("\n四、什么都没有 → 空串 + 明写该设哪个环境变量")
        P._cand_dirs = lambda: [os.path.join(tmp, "void")]
        shutil.which = lambda *a, **k: None
        p5, how5 = P.find_llama_server()
        ck("返回空", p5 == "", p5)
        ck("提示里明写环境变量名", "XIAOJIAO_LLAMA_SERVER" in how5, how5)
        p6, how6 = P.find_llama_swap()
        ck("可选件说清「没有也能跑」", "不影响聊天" in how6 or "直连" in how6, how6)

        print("\n五、llama-swap.yaml 改写：dry-run 不动、apply 只改坏的、能用的不碰、可幂等")
        P._cand_dirs = lambda: [empty]
        shutil.which = old_which
        canary = os.path.join(tmp, "canary.exe")
        io.open(canary, "w").close()
        gg = os.path.join(tmp, "real.gguf")
        io.open(gg, "w").close()
        yp = os.path.join(tmp, "llama-swap.yaml")
        io.open(yp, "w", encoding="utf-8").write(YAML % canary.replace("\\", "/"))
        before = io.open(yp, encoding="utf-8").read()
        out = P.fix_swap_cfg(server=os.path.join(tmp, "found-llama-server.exe"),
                             gguf=gg, path=yp, dry_run=True)
        ck("dry-run 报出要改 2 处（exe + model）", len(out.get("changes") or []) == 2,
           out.get("changes"))
        ck("dry-run 一个字节都没动", io.open(yp, encoding="utf-8").read() == before)
        out2 = P.fix_swap_cfg(server=os.path.join(tmp, "found-llama-server.exe"),
                              gguf=gg, path=yp, dry_run=False)
        after = io.open(yp, encoding="utf-8").read()
        ck("apply 真的改了", after != before and "found-llama-server.exe" in after)
        ck("坏路由的模型换成了探测到的", "real.gguf" in after and "missing.gguf" not in after)
        ck("**能用的那条路由没被动**（它自己的 gguf 还在）",
           ("--model \"%s\"" % canary.replace("\\", "/")) in after)
        ck("`-c 20000 --reasoning off` 原样保留", after.count("-c 20000 --reasoning off") == 2)
        ck("注释与路由名原样保留", "# 头部注释不许被动" in after and "  broken:" in after)
        ck("先备份了", bool(out2.get("backup")) and os.path.exists(out2["backup"]),
           out2.get("backup"))
        out3 = P.fix_swap_cfg(server=os.path.join(tmp, "found-llama-server.exe"),
                              gguf=gg, path=yp, dry_run=False)
        ck("再跑一次不用改（幂等）", not (out3.get("changes") or []), out3.get("changes"))

        print("\n六、report()：五项齐全，每项都带环境变量名")
        rep = P.report()
        ck("五项", len(rep) == 5, [r["what"] for r in rep])
        ck("每项都有 env 名", all(r.get("env", "").startswith("XIAOJIAO_") for r in rep))
        ck("每项都有状态与说明", all(("ok" in r and r.get("how")) for r in rep))
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        P._cand_dirs, P._ROOTS, shutil.which = old_dirs, old_roots, old_which
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    print("外部路径解析自测：通过 %d / 共 %d%s"
          % (len(PASS), len(PASS) + len(FAIL), ("　失败：" + str(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
