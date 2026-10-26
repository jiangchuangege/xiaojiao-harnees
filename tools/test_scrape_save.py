# -*- coding: utf-8 -*-
"""「抓下来 + 存到本地」自测（离线判据；只有最后一组会真连一次网）

用户实测的那句话钉在这里：
    「帮我爬一下电子书https://www.xyax.cn/book 下载到G:\\dzs」
它当时的结果是 —— `screenshot` 连错两次、**会话不存在**、整体"已停止"。
三个根因，逐条钉住：
  ① 「下载/保存到」曾被当成"别的动作"，抓取意图直接被判成 None（整条链没人管）；
  ② 抓取直通被"通用工具隔离"挡掉（句子里有"下载"→ 命中专用工具 download → get 被逐出）；
  ③ 就算抓到了，也没有任何代码把正文落盘（"下载到 G:" 这句话没人接）。
"""
import io
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  抓取 + 落盘 自测")
    print("=" * 80)
    import xiaojiao_app as app        # noqa: E402

    q = "帮我爬一下电子书https://www.xyax.cn/book 下载到G:\\dzs"

    # ---------------- 一、意图：这句话必须被判成"抓取" ----------------
    print("\n[一] 「爬一下…下载到…」必须判成抓取（原来判成 None，整条链没人管）")
    sc = app._detect_scrape_intent(q)
    ck("判得出抓取意图", bool(sc), sc)
    ck("选的是抓取工具 get（网页地址，不是直链文件）", sc and sc[0] == "get", sc)
    ck("网址取对了", sc and sc[1].get("url") == "https://www.xyax.cn/book", sc and sc[1])
    ck("仍然不乱抢：说「截图」时不走抓取",
       app._detect_scrape_intent("把 https://a.com/x 截图") is None)
    ck("仍然不乱抢：说「监控」时不走抓取",
       app._detect_scrape_intent("监控 https://a.com/x 每 5 分钟") is None)
    ck("普通抓取不受影响",
       bool(app._detect_scrape_intent("抓 https://httpbin.org/json 看看写了啥")))

    # ---------------- 二、保存位置：认得出、不乱猜 ----------------
    print("\n[二] 保存位置认得出，且只在用户说了才存")
    ck("从原话里取出保存目录", app._scrape_save_target(q) == "G:\\dzs",
       app._scrape_save_target(q))
    ck("给了文件名的也认", app._scrape_save_target("抓到 D:\\a\\b.txt 里") == "D:\\a\\b.txt",
       app._scrape_save_target("抓到 D:\\a\\b.txt 里"))
    ck("没说存哪儿 → 空（不擅自落盘）", app._scrape_save_target("抓 https://a.com/x") == "")

    # ---------------- 三、真落盘：目录 / 文件 / 空正文 / 盘不存在 ----------------
    print("\n[三] 真落盘，失败就如实说")
    d = tempfile.mkdtemp()
    try:
        p, note = app._scrape_save_body("https://www.xyax.cn/book", "# 标题\n正文第二行", d)
        ck("存进目录 → 自动起文件名", bool(p) and os.path.isfile(p), p)
        ck("内容写全了（不是空壳）", bool(p) and io.open(p, encoding="utf-8").read().count("\n") >= 1)
        p2, _ = app._scrape_save_body("https://a.cn/x", "内容", os.path.join(d, "sub", "x.txt"))
        ck("指定文件名 → 照写，并自动建目录", bool(p2) and os.path.isfile(p2), p2)
        p3, why3 = app._scrape_save_body("https://a.cn/x", "   ", d)
        ck("正文是空的（比如只抓到导航）→ 不写空文件，如实说",
           p3 == "" and "空" in why3, why3)
        p4, why4 = app._scrape_save_body("https://a.cn/x", "内容", "Q:\\不存在的盘\\dzs")
        ck("目标盘不存在 → 不假装成功，给中文原因", p4 == "" and "存盘失败" in why4, why4[:60])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # ---------------- 四、工具描述：session_id 不再是必填（模型才不会去编） ----------------
    print("\n[四] 截图/会话类工具：session_id 不再必填（模型编 ID 的根就在这）")
    import plugins.scrapling_bridge as BR      # noqa: E402
    descs = {}
    for item in (BR.ScraplingBridge().get_tool_descriptions() if hasattr(BR, "ScraplingBridge") else []):
        descs[item.get("name")] = item
    if not descs:      # 插件类名不固定时，退回工具表里的真实 schema
        app._build_tools()
        for t in app._build_tools():
            fn = t.get("function") or {}
            descs[fn.get("name")] = fn
    for name in ("screenshot", "session_fetch", "session_make_request"):
        fn = descs.get(name) or {}
        req = (fn.get("parameters") or {}).get("required") or []
        ck("%s 的 session_id 不是必填" % name, "session_id" not in req, req)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
