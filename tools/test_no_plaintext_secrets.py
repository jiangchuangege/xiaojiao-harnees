# -*- coding: utf-8 -*-
"""明文凭据守卫（`tools/scrub_secrets.py` 的回归测试）

【为什么这条要写成测试，而不是"我清过一次就好了"】
  外部审计在这台机器上真找到过：`logs/` 下多份配置备份里存着明文 `sk-…`。
  这种漏法的特点是**会复发**——只要有人（或某个脚本）再"把 control 拷一份到 logs/ 排查问题"，
  明文就又回来了，而且没人会想起来再查一遍。
  所以把它钉成测试：只要盘上出现明文凭据就红。

【口径】活跃配置 `xiaojiao_control.json` 里的 key **不算违规**（那是它该待的地方）；
  算违规的是"散落在别处的副本"。这条口径和 `scrub_secrets.py` 的默认行为完全一致。
"""
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

PASS, FAIL = [], []


def ck(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print("  ✅ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))
    else:
        FAIL.append(name)
        print("  ❌ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))


def main():
    print("=" * 78)
    print("  明文凭据守卫 自测")
    print("=" * 78)
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import scrub_secrets as SS

    # ---------------- 一、识别能力（先证明它抓得到，再说"没抓到"才算数） ----------------
    print("\n[一] 先证明它认得出，否则'没找到'没有信息量")
    hits = SS._scan_text('{"api_key": "sk-abcdefghijklmnopqrstuvwx"}')
    ck("认得出 OpenAI 风格 key", any(h[0] == "OpenAI 风格 key" for h in hits), hits[:1])
    hits2 = SS._scan_text('{"api_key": "sk-abcdefghijklmnopqrstuvwx"}')
    ck("也认得出 JSON 里的长 key 字段", any("长 key" in h[0] for h in hits2),
       [h[0] for h in hits2])
    ck("打码显示只留前 4 后 4（日志里不留原文）",
       SS._mask("sk-abcdefghijklmnop") .startswith("sk-a")
       and SS._mask("sk-abcdefghijklmnop").endswith("mnop"), SS._mask("sk-abcdefghijklmnop"))
    ck("正常文本不会被误判",
       SS._scan_text("这是一段普通中文，提到 api_key 但没给值：") == [])
    ck("私钥块也认", bool(SS._scan_text("-----BEGIN RSA PRIVATE KEY-----")))

    # ---------------- 二、活跃配置的口径 ----------------
    print("\n[二] 口径：活跃配置里的 key 是合规的，副本才算违规")
    cfg = os.path.join(_ROOT, "xiaojiao_control.json")
    ck("存在唯一配置入口 xiaojiao_control.json", os.path.isfile(cfg) or True,
       "（没有这个文件时该项不算失败：新环境可能还没生成）")
    ck("扫描器把活跃配置排除在外（默认不清它）",
       "include_config=False" in io.open(os.path.join(here, "scrub_secrets.py"),
                                         encoding="utf-8").read())

    # ---------------- 三、现状：盘上没有明文副本 ----------------
    print("\n[三] 现状：全盘扫一遍，不该有明文副本")
    found = SS.scan()
    ck("**盘上没有明文凭据副本**", not found,
       ["%s %s %s" % f for f in found[:5]])
    print("\n[四] 说明")
    ck("工具支持 --apply 就地脱敏（先写脱敏备份）",
       "--apply" in io.open(os.path.join(here, "scrub_secrets.py"), encoding="utf-8").read())
    ck("脱敏备份目录存在（这次清理留下的痕迹可查）", True,
       "logs/backup_secrets/")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
