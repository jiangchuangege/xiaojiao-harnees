# -*- coding: utf-8 -*-
"""🐳 小焦 · 一键安装/启动
用法：双击 `一键安装.bat`，或：python install_auto.py
它会：装依赖 → 检查/提示大模型位置 → 自动识别路径 → 启动小焦。
"""
import os, sys, subprocess, json

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd, show=True):
    print("  >", cmd)
    subprocess.run(cmd, shell=True)


def check_model():
    """检查大模型服务/文件，给出新手指引。**路径全部走统一解析 `core/paths.py`**（2026-09-19）。"""
    try:
        c = json.load(open(os.path.join(ROOT, "xiaojiao_control.json"), encoding="utf-8"))
    except Exception:
        c = {}
    ll = c.get("brain", {}).get("llama", {})
    server, gguf = ll.get("server", ""), ll.get("gguf", "")
    if not (server and os.path.exists(server)) or not (gguf and os.path.exists(gguf)):
        try:
            sys.path.insert(0, ROOT)
            from core import paths as P
            print("   （正在自动找 llama-server / gguf，允许整盘深搜 —— 第一次装可能要几十秒）")
            if not (server and os.path.exists(server)):
                server = P.find_llama_server(deep=True)[0] or server
            if not (gguf and os.path.exists(gguf)):
                gguf = P.find_gguf(deep=True)[0] or gguf
        except Exception as e:
            print("   ⓘ 自动探测不可用：%s" % e)
    ok_s = os.path.exists(server)
    ok_g = os.path.exists(gguf)
    print("\n🔍 检查大模型：")
    print("   llama-server:", server or "（没找到）", "→", "✅ 存在" if ok_s else "❌ 未找到")
    print("   模型文件:    ", gguf or "（没找到）", "→", "✅ 存在" if ok_g else "❌ 未找到")
    if not ok_s:
        print("   💡 请安装 llama.cpp（llama-server.exe），或用环境变量 XIAOJIAO_LLAMA_SERVER 指定路径。")
    if not ok_g:
        print("   💡 请把模型 .gguf 放到 C:/llama、本项目目录或 Downloads，或用环境变量 XIAOJIAO_GGUF 指定。")
    # **自动把 llama-swap.yaml 里写死的路径对齐到这台机器**（只改指向不存在文件的那些，先备份）
    try:
        sys.path.insert(0, ROOT)
        from core import paths as P
        fx = P.fix_swap_cfg(server=server or None, gguf=gguf or None,
                            only_missing=True, dry_run=False)
        if fx.get("ok") and (fx.get("changes") or []):
            for ch in fx["changes"]:
                print("   🔧 llama-swap.yaml 的 %s：%s → %s" % (ch["route"], ch["old"], ch["new"]))
    except Exception as e:
        print("   ⓘ 没自动改 llama-swap.yaml（可手工跑 python tools/setup_paths.py --apply）：%s" % e)
    return ok_s and ok_g


def main():
    print("=" * 52)
    print("🐳 小焦 XiaoJiao · 一键安装 / 启动")
    print("=" * 52)
    # 1) 依赖
    print("\n[1/3] 安装 Python 依赖 ...")
    run('"%s" -m pip install -r "%s"' % (sys.executable, os.path.join(ROOT, "requirements.txt")))
    # 2) 模型
    print("\n[2/3] 检查大模型 ...")
    check_model()
    # 3) 启动
    print("\n[3/3] 启动小焦（大模型 + Web + N.E.K.O. 猫娘）...")
    run('"%s" "%s"' % (sys.executable, os.path.join(ROOT, "start_xiaojiao.py")))
    print("\n✅ 完成。浏览器打开 http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
