# -*- coding: utf-8 -*-
"""阶段 F · 最终验收（全新 clone 验证）

【验收什么】
    "发布即成品"这句话只有在**别的机器/别的目录**上也成立才算数。
    本测试把工作区**复制**成一个全新的干净目录（排除 .git / __pycache__ / logs 运行产物 /
    用户数据），在那里验证：
      ① 代码能 import（没有"只在原目录能跑"的硬编码路径）；
      ② 六个无限的核心模块能工作；
      ③ 预置数据 `core/preinstall.ensure()` 能在**空环境**里把六类补齐（开箱即用的底线）；
      ④ 核心自测能跑绿。

【为什么不是真的 `git clone`】
    当前改动**尚未提交**（用户说了不提交），`git clone` 拿到的是旧提交，
    验证不了本轮的东西。所以用"复制工作区"来模拟全新安装：
    排除项与"用户新下载一个发布包"的情形一致 —— 没有 logs、没有缓存、没有 git 历史。
    这不是偷懒，而是**在这个约束下唯一能验证当前代码的方式**（报告里要如实写明）。

⚠️ 本测试**绝不删除任何文件**：临时目录用完只打印路径，不清理（避免误删）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# 复制时排除的东西（与"用户新下载发布包"的情形对齐）
_EXCLUDE_DIRS = ("__pycache__", ".git", ".ruff_cache", ".github",
                 "LCCC-base-split", "LCCC-large", "downloads", "media", "videos",
                 "books", "dsh_home", "dsh_sessions", "~")
_EXCLUDE_FILES = ("LCCC-base_train.json", "LCCC-base_test.json", "LCCC-base_valid.json",
                  "LCCC-large.zip", "LCCC-base-split.zip", "LCCD.json",
                  "mini_gpt_model.pth", "vocab.pkl")


def _copy_tree(dst):
    """把工作区复制到 dst（排除 .git / 缓存 / 日志 / 大文件），返回复制的文件数。"""
    n = 0
    for root, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        rel = os.path.relpath(root, _ROOT)
        if rel.split(os.sep)[0] in ("logs", "downloads", "media", "videos"):
            continue
        for f in files:
            if f in _EXCLUDE_FILES or f.endswith(".pyc"):
                continue
            src = os.path.join(root, f)
            try:
                if os.path.getsize(src) > 8 * 1024 * 1024:      # 跳过大文件
                    continue
            except Exception:      # noqa: silent-ok — 取不到大小就跳过，不影响复制主体
                continue
            out = os.path.join(dst, rel, f) if rel != "." else os.path.join(dst, f)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            try:
                shutil.copyfile(src, out)
                n += 1
            except Exception:      # noqa: silent-ok — 个别文件复制失败不算致命
                continue
    return n


def _run(work, code, timeout=300):
    """在新目录里跑一段 python（UTF-8，返回 (ok, stdout+stderr)）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = work
    try:
        p = subprocess.run([sys.executable, "-W", "ignore", "-c", code],
                           cwd=work, env=env, capture_output=True, timeout=timeout)
        out = (p.stdout or b"").decode("utf-8", "replace") + \
              (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode == 0, out
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def main():
    print("=" * 78)
    print("  阶段 F · 最终验收 · 全新 clone 验证")
    print("=" * 78)
    work = tempfile.mkdtemp(prefix="xj_fresh_clone_")
    print("\n[①] 复制成全新目录（排除 .git / 缓存 / logs 运行产物 / 大文件）")
    n = _copy_tree(work)
    ck("复制成功（有文件）", n > 100, "%d 个文件 → %s" % (n, work))
    ck("**新目录里没有 .git**（模拟用户拿到的发布包）",
       not os.path.exists(os.path.join(work, ".git")))
    ck("**新目录里没有 logs**（无运行产物、无用户数据）",
       not os.path.exists(os.path.join(work, "logs")))
    for rel in ("core/continuation.py", "core/memory_deep.py", "core/persona/__init__.py",
                "core/central/__init__.py", "core/boost/__init__.py",
                "core/preinstall/__init__.py", "docs/architecture-diagrams.md"):
        ck("新目录含 %s" % rel, os.path.exists(os.path.join(work, rel)))

    # ---------------- ② import 与核心能力 ----------------
    print("\n[②] 在新目录里 import 与核心能力")
    ok, out = _run(work, (
        "import core, core.continuation, core.memory_deep, core.persona\n"
        "import core.central, core.boost, core.preinstall, core.metacognition\n"
        "from core.boost import reasoning, causal, analogy, vague, creative, deepthink, consistency\n"
        "print('IMPORT_OK', len(reasoning.all_templates()))\n"))
    ck("**所有新模块在新目录里都能 import**（没有硬编码原路径）",
       ok and "IMPORT_OK" in out, out.strip().splitlines()[-1][:120] if out else "")

    ok, out = _run(work, (
        "from core import memory_deep as M\n"
        "print('CLASSIFY', M.classify('我叫张三，住在济南')[0], M.classify('你好')[0])\n"
        "print('CLARITY', M.clarity_of(0.5), M.clarity_of(15), M.clarity_of(60), M.clarity_of(400))\n"
        "print('OVERLAP', M.overlap('我住在济南','用户：我住在济南'))\n"))
    ck("记忆深度（模块 3）在新环境可用", ok and "CLASSIFY fact expression" in out, out.strip()[-100:])
    ck("清晰度四档（模块 3）在新环境可用", "CLARITY hd sd blur impression" in out)

    ok, out = _run(work, (
        "from core import persona as P\n"
        "sp = P.persona_block()\n"
        "print('PERSONA', '有立场' in sp and '有边界感' in sp, P.pick_form('给我列 5 条'))\n"
        "t,_ = P.strip_flavor('当然可以！以下是内容。希望以上对你有帮助。')\n"
        "print('STRIP', '当然可以' not in t and '希望以上' not in t)\n"))
    ck("人格层（模块 9）在新环境可用", ok and "PERSONA True list" in out, out.strip()[-100:])
    ck("去 AI 味在新环境有效", "STRIP True" in out)

    ok, out = _run(work, (
        "from core import central as S\n"
        "S.set_state('t', a=1); S.publish('x', 1)\n"
        "print('CENTRAL', S.get_state('t').get('a'), S.bus_stats()['published'])\n"
        "S.clear_state(); S.reset_bus()\n"))
    ck("协同网络（阶段 B）在新环境可用", ok and "CENTRAL 1 1" in out, out.strip()[-80:])

    # ---------------- ③ 开箱即用：预置数据能在空环境补齐 ----------------
    print("\n[③] 开箱即用：空环境里补齐六类预置数据")
    ok, out = _run(work, (
        "from core import preinstall as P\n"
        "before = P.verify()\n"
        "print('BEFORE_READY', before['ready'], len(before['missing']))\n"
        "w = P.ensure()\n"
        "v = P.verify()\n"
        "print('SEEDED', w.get('rules'), w.get('cases'), w.get('persona'))\n"
        "print('AFTER_READY', v['ready'], v['missing'])\n"
        "for k, c in v['categories'].items():\n"
        "    print('CAT', k, c['ready'], c['count'])\n"
        "print('SUMMARY', P.summary()[:60])\n"))
    ck("**空环境启动时预置数据是缺的**（证明确实是「装配」补上的，不是随包自带）",
       "BEFORE_READY False" in out, [l for l in out.splitlines() if l.startswith("BEFORE_READY")])
    ck("**ensure() 之后六类齐备**（开箱即用的底线）",
       "AFTER_READY True []" in out, [l for l in out.splitlines() if l.startswith("AFTER_READY")])
    # ⚠️ 人格那一项是 **0** 而不是 1：presets/ 随包发布（人设本来就是发行物的一部分），
    #    所以新目录里已经有可用人设，ensure() 正确地**没有重复写**。
    #    第一版我按"三项都该写"断言，把正确的幂等行为判成了失败。
    #    正确口径：规则库/案例库**必须**被补齐（它们的产地是代码里的种子），
    #    人格则允许"已有就不写"（用户改过的人设绝不能被覆盖）。
    ck("规则库/案例库被补齐（人格随包已有 → 0 是正确的幂等）",
       "SEEDED 10 8 0" in out, [l for l in out.splitlines() if l.startswith("SEEDED")])
    cat_lines = [l for l in out.splitlines() if l.startswith("CAT ")]
    ck("六类各自 ready=True", len(cat_lines) == 6 and all(" True " in l for l in cat_lines),
       cat_lines)

    # ---------------- ④ 核心自测能在新目录跑绿 ----------------
    print("\n[④] 核心自测在新目录跑绿")
    # ---------------- ④ 依赖可用（"安装"这一步） ----------------
    print("\n[④] 依赖可用：requirements.txt 里的核心包在新环境都能 import")
    ck("requirements.txt 随包存在", os.path.exists(os.path.join(work, "requirements.txt")))
    # 只核对**核心**依赖：可选的重型包（torch/diffusers 等）缺失只影响视频/播客附加能力，
    # 不影响聊天与检索主线 —— 把它们算作失败会让这条验收永远红。
    _core_mods = (("flask", "flask"), ("requests", "requests"), ("numpy", "numpy"),
                  ("jieba", "jieba"), ("markdownify", "markdownify"))
    _code = ("import importlib\n"
             "missing=[]\n"
             "for mod,label in %r:\n"
             "    try: importlib.import_module(mod)\n"
             "    except Exception: missing.append(label)\n"
             "print('DEPS_OK' if not missing else 'DEPS_MISSING:'+','.join(missing))\n"
             % (_core_mods,))
    ok, out = _run(work, _code, timeout=120)
    ck("**核心依赖都能 import**（等价于「装好了能跑」）",
       ok and "DEPS_OK" in out, [l for l in out.splitlines() if l.startswith("DEPS")])

    # ---------------- ⑤ 启动：全新目录里能起服务 ----------------
    print("\n[⑤] 启动：全新目录里能起服务（换端口跑，不动正在运行的那一份）")
    import time as _t
    port = 5099
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["XIAOJIAO_NEKO_AUTO"] = "0"
    env["PORT"] = str(port)
    proc = None
    try:
        # ⚠️ 端口必须走 `--port` 参数，**不能只设 PORT 环境变量**：
        #    `start_xiaojiao.py` 的优先级是 `--port` > `xiaojiao_control.json 的 web_port`
        #    > 环境变量 PORT。而控制文件是随包复制的，里面写着 web_port=5000 ——
        #    于是"设了 PORT=5099"也会去抢 5000，跟正在运行的那份**撞端口**，
        #    表现为"服务起不来"（第一版就是这么假红的）。
        #    带 `--port` 才是真正意义上的"换一个端口起"。
        proc = subprocess.Popen([sys.executable, "start_xiaojiao.py", "--port", str(port)],
                                cwd=work, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        alive, waited = False, 0.0
        while waited < 150:
            _t.sleep(3)
            waited += 3
            try:
                r = subprocess.run(
                    [sys.executable, "-c",
                     "import urllib.request as u;"
                     "print(u.urlopen('http://127.0.0.1:%d/health',timeout=4).status)" % port],
                    cwd=work, env=env, capture_output=True, timeout=25)
                if b"200" in (r.stdout or b""):
                    alive = True
                    break
            except Exception:      # noqa: silent-ok — 还没起来就继续等
                continue
        ck("**全新目录能启动并响应 /health**（等了 %.0fs）" % waited, alive,
           "port=%d" % port)
        if alive:
            r = subprocess.run(
                [sys.executable, "-c",
                 "import urllib.request as u;"
                 "print(u.urlopen('http://127.0.0.1:%d/api/models',timeout=8).status)" % port],
                cwd=work, env=env, capture_output=True, timeout=30)
            ck("业务接口可访问（/api/models 返回 200）", b"200" in (r.stdout or b""),
               (r.stdout or b"").decode("utf-8", "replace")[:40])
    except Exception as e:
        ck("**全新目录能启动并响应 /health**", False, "%s: %s" % (type(e).__name__, e))
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=20)
            except Exception:      # noqa: silent-ok — 收不掉就交给系统回收，不影响结论
                try:
                    proc.kill()
                except Exception:      # noqa: silent-ok — 同上
                    pass

    # ---------------- ⑥ 核心自测能在新目录跑绿 ----------------
    print("\n[⑥] 核心自测在新目录跑绿")
    for script, pattern, label in (
            ("tools/test_degen_strategy.py", "通过 13 / 共 13", "无限 3 复读策略"),
            ("tools/test_memory_depth.py", "通过 73 / 共 73", "模块 3 记忆深度"),
            ("tools/test_persona.py", "通过 58 / 共 58", "模块 9 人格层"),
            ("tools/test_central.py", "通过 44 / 共 44", "阶段 B 协同网络"),
            ("tools/test_preinstall.py", "通过 31 / 共 31", "阶段 C 预置数据"),
            ("tools/test_boost.py", "通过 195 / 共 195", "模块 10 极限补刀"),
            ("tools/test_mind.py", "通过 77 / 共 77", "模块 1 十项核心智力"),
            ("tools/test_search_intent.py", "通过 58 / 共 58", "Bug1/Bug2 回归"),
            ("tools/test_infinity_456.py", "通过 32 / 共 32", "无限 4/5/6（代码级）"),
            ("tools/test_comments_audit.py", "通过 34 / 共 34", "阶段 D 注释审计"),
            ("tools/test_docs_audit.py", "通过 42 / 共 42", "阶段 E 文档审计")):
        # 【为什么这份清单里**没有** tools/test_embedder_long.py】
        #   它验收的是小脑（MiniGPT 权重）的向量区分度，而全新目录里**没有小脑权重文件** ——
        #   嵌入器会如实退到哈希兜底后端，那 6 条基于小脑的断言必然红。
        #   这是"依赖真实权重"的测试，不是"裸目录必须全绿"的测试；
        #   把它塞进这份清单，等于要求一次 git clone 就自带几百 MB 的模型权重。
        #   教训（实测踩到）：往这份清单里加东西之前，先问一句"它在**裸目录**里也能跑吗"。
        p = os.path.join(work, script)
        if not os.path.exists(p):
            ck("%s 在新目录存在" % label, False, script)
            continue
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        try:
            r = subprocess.run([sys.executable, "-W", "ignore", script], cwd=work, env=env,
                               capture_output=True, timeout=900)
            text = (r.stdout or b"").decode("utf-8", "replace") + \
                   (r.stderr or b"").decode("utf-8", "replace")
            line = next((l.strip() for l in text.splitlines()
                         if "通过" in l and "/ 共" in l), "")
            ck("%s 在全新目录跑绿" % label, pattern in text, line or text.strip()[-80:])
        except Exception as e:
            ck("%s 在全新目录跑绿" % label, False, "%s: %s" % (type(e).__name__, e))

    print("\n  临时目录（**未删除**，避免误删）：%s" % work)
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
