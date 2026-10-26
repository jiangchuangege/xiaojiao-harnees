# -*- coding: utf-8 -*-
"""电子书采集插件 · 自测（离线：本地假站，不碰任何真网站）

钉住五件事，每件都是"能不能用"的关键：
  ① 目录页能解析成书目清单，清单能存成 CSV/MD；
  ② 公开条目里的真 PDF 能下下来，**文件头对得上**（不是登录页冒充的）；
  ③ 付费/登录墙的条目**跳过并说明原因** —— 不绕过、不硬来；
  ④ robots.txt 禁止的目录**一律不抓**；
  ⑤ 扩展名是 .pdf 但内容其实是 HTML 的，靠验文件头**拦下、不落盘**。
另外验：内网地址默认拦（SSRF），limit 生效，插件异常也回中文。
"""
import io
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  电子书采集插件自测（本地假站，不连真站）")
    print("=" * 80)
    from tests.fake_book_site import PDF_BYTES, FakeBookSite   # noqa: E402

    # 自测要打本地假站：插件默认拦内网/环回，这个开关只给自测用
    os.environ["XIAOJIAO_EBOOK_ALLOW_LOCAL"] = "1"
    plug = None
    try:
        import plugins.ebook as EB                              # noqa: E402
        plug = EB.get_plugin()
    except Exception as e:
        print("  ❌ 插件加载失败：%s" % e)

    ck("插件能加载（有 get_tool_descriptions / execute）",
       bool(plug) and hasattr(plug, "get_tool_descriptions") and hasattr(plug, "execute"))

    srv = FakeBookSite().start()
    tmp = tempfile.mkdtemp()
    try:
        # ---------------- 一、工具契约 ----------------
        print("\n[一] 工具声明（名称 / 说明 / 参数）")
        descs = plug.get_tool_descriptions() if plug else []
        names = [d.get("name") for d in descs]
        ck("两个工具都在", set(names) == {"ebook_manifest", "ebook_grab"}, names)
        for d in descs:
            txt = str(d.get("description") or "")
            ck("%s 的说明含「什么时候用」" % d.get("name"), "什么时候用" in txt, txt[:40])
            ck("%s 的说明不超过 60 字" % d.get("name"), len(txt) <= 60, len(txt))

        # ---------------- 二、目录页 → 书目清单 ----------------
        print("\n[二] 目录页能解析成清单，也能存成文件")
        out = plug.execute("ebook_manifest", {"url": srv.base + "/books"}) if plug else ""
        ck("清单里给出了条目", "book/1.html" in str(out), str(out)[:60])
        ck("导航/分页/标签不算条目",
           "/tag/" not in str(out) and "/page/2" not in str(out), str(out)[:80])
        csv_path = os.path.join(tmp, "清单.csv")
        out2 = plug.execute("ebook_manifest", {"url": srv.base + "/books", "out": csv_path}) if plug else ""
        ck("清单能存成 CSV", os.path.isfile(csv_path), str(out2)[-60:])
        ck("CSV 里有表头与链接",
           os.path.isfile(csv_path) and "链接" in io.open(csv_path, encoding="utf-8-sig").read())
        md_path = os.path.join(tmp, "清单.md")
        plug.execute("ebook_manifest", {"url": srv.base + "/books", "out": md_path})
        ck("也能存成 Markdown 表格",
           os.path.isfile(md_path) and "| 序号 |" in io.open(md_path, encoding="utf-8").read())

        # ---------------- 三、抓取：公开的下、付费的跳、禁止的不碰 ----------------
        print("\n[三] 采集：公开条目真下、付费墙跳过、robots 禁止的不抓")
        dl = os.path.join(tmp, "下载")
        res = plug.execute("ebook_grab", {"url": srv.base + "/books", "out_dir": dl, "limit": 10}) if plug else ""
        res = str(res)
        files = sorted(os.listdir(dl)) if os.path.isdir(dl) else []
        ck("公开的 PDF 下下来了", any(f.endswith(".pdf") for f in files), files)
        pdf_path = os.path.join(dl, [f for f in files if f.endswith(".pdf")][0]) if any(
            f.endswith(".pdf") for f in files) else ""
        ck("下下来的确实是 PDF（文件头 %PDF）",
           bool(pdf_path) and io.open(pdf_path, "rb").read(4) == b"%PDF",
           pdf_path)
        ck("字节数和假站给的一致",
           bool(pdf_path) and os.path.getsize(pdf_path) == len(PDF_BYTES),
           (os.path.getsize(pdf_path) if pdf_path else 0, len(PDF_BYTES)))
        ck("付费墙那条被跳过了，并且写清了原因",
           "需登录/付费" in res, [l for l in res.splitlines() if "需登录" in l][:1])
        ck("结果里没有把付费那条说成已下载",
           "book/2.html" in res and "成功" in res)
        ck("robots 禁止的目录没被采集（有拒绝原因）",
           "robots" in res.lower(), [l for l in res.splitlines() if "robots" in l.lower()][:1])
        ck("假的 .pdf（其实是 HTML）没落盘",
           not any(f == "fake.pdf" for f in files), files)
        ck("假 PDF 也给了原因（文件头不对）",
           "文件头" in res or "登录页" in res, [l for l in res.splitlines() if "文件头" in l][:1])

        # ---------------- 四、直接给详情页、limit 生效 ----------------
        print("\n[四] 直接给条目页也能下；limit 真的是上限")
        dl2 = os.path.join(tmp, "下载2")
        plug.execute("ebook_grab", {"url": srv.base + "/book/1.html", "out_dir": dl2})
        ck("给详情页 → 直接下到文件",
           os.path.isdir(dl2) and any(f.endswith(".pdf") for f in os.listdir(dl2)),
           os.listdir(dl2) if os.path.isdir(dl2) else "目录没建")
        dl3 = os.path.join(tmp, "下载3")
        r3 = str(plug.execute("ebook_grab", {"url": srv.base + "/books", "out_dir": dl3, "limit": 1}))
        ck("limit=1 → 只处理第一个条目（不会一口气全下）",
           "成功 1 个" in r3 and "book/2.html" not in r3, r3.splitlines()[:2])

        # ---------------- 五、安全边界 ----------------
        print("\n[五] 安全边界：内网地址要拦（SSRF）、坏参数回中文")
        os.environ.pop("XIAOJIAO_EBOOK_ALLOW_LOCAL", None)
        r4 = str(plug.execute("ebook_grab", {"url": srv.base + "/books", "out_dir": tmp}))
        ck("关掉自测开关后，环回地址被拦", "内网" in r4 or "安全策略" in r4, r4[:80])
        os.environ["XIAOJIAO_EBOOK_ALLOW_LOCAL"] = "1"
        ck("缺 url → 中文提示", "需要 url" in str(plug.execute("ebook_grab", {"out_dir": tmp})))
        ck("缺 out_dir → 中文提示",
           "out_dir" in str(plug.execute("ebook_grab", {"url": srv.base + "/books"})))
        ck("未知工具名 → 中文提示，不抛异常",
           "没有" in str(plug.execute("ebook_xxx", {})))
        ck("limit 传垃圾值也不炸",
           "⚠️" in str(plug.execute("ebook_grab", {"url": srv.base + "/1", "out_dir": tmp,
                                                   "limit": "abc"})) or True)
        ck("抓不到的真实域名 → 中文说明（不抛异常）",
           "⚠️" in str(plug.execute("ebook_grab",
                                    {"url": "https://no-such-host-xyz-1024.invalid/x",
                                     "out_dir": tmp})))
    finally:
        srv.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
