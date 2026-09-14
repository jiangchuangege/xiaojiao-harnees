# -*- coding: utf-8 -*-
"""回归测试：意图识别 + 搜索词提取（Bug 1 / Bug 2，防复发）

【用户实测现象（这两条就是本测试要钉住的）】
    Bug 1：说"整理一下最近的新闻信息" → 小焦回"抱歉，我无法直接访问实时新闻网站…你想查什么方向？"
           用户已经把方向说清了（"最近"+"新闻"），却还被反问一句。
           根因：信息收集类动作词（整理/汇总/看一下）没被当成检索意图 → 判成 chat →
                 闲聊轮不联网 → 模型只能反问。
    Bug 2：小焦真的调了 web_search，但搜的词是"整理" → 返回"整理的读音/组词/近义词"。
           根因：功能字（整理/帮我/搞）没从检索词里剥掉。

【为什么必须做成回归测试】
    这两条都属于"**静默退化**"：改一次清洗规则、加一个 filler，
    就可能让检索词又带上"壳"，而功能测试全绿、只有用户会看到"整理的读音"。
    所以把用户给的原话逐条钉住，任何一次改动跑一下就知道了。

运行：python tools/test_search_intent.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


# (用户原话, 期望意图, 期望检索词)  —— 前三条是**用户给的验收用例**，一字不改
CASES = (
    ("整理一下最近的新闻信息", "query", "最近新闻"),
    ("帮我看看最近 AI 新闻", "query", "最近 AI 新闻"),
    ("汇总今天的科技动态", "query", "今日科技动态"),
    # 同族变体（同一类说法，防止只修了字面那一条）
    ("整理今天的信息", "query", "今日信息"),
    ("看一下本周的动态", "query", "本周动态"),
    ("整理一下最近的热点", "query", "最近热点"),
    ("帮我汇总近期的资讯", "query", "最近资讯"),
    ("梳理一下最新的进展", "query", "最新进展"),
)


def main():
    print("=" * 74)
    print("  回归 · 意图识别 + 搜索词提取（Bug 1 反问 / Bug 2 检索词带壳）")
    print("=" * 74)

    # ---------------- 一、验收用例逐条 ----------------
    print("\n[一] 用户给的验收用例 + 同族变体：意图要对、检索词要干净")
    for text, want_intent, want_q in CASES:
        got_intent = X._detect_intent(text)
        ck("意图「%s」→ %s" % (text, want_intent), got_intent == want_intent, got_intent)
        got_q, hint = X.resolve_search_query(text)
        ck("检索词「%s」→ %r" % (text, want_q), got_q == want_q,
           "%r%s" % (got_q, ("（提示：%s）" % hint[:20]) if hint else ""))

    # ---------------- 二、Bug 1 的根因：不能再落进 chat ----------------
    print("\n[二] Bug 1 根因回归：信息收集类说法**绝不能**判成 chat")
    # 为什么单独断言"不是 chat"：判成 chat 就等于"闲聊轮不联网"，必然反问用户。
    for text, _, _ in CASES:
        ck("「%s」不是 chat（否则会反问用户）" % text,
           X._detect_intent(text) != "chat", X._detect_intent(text))
    # 反向：真闲聊仍然必须是 chat（不能为了修 Bug 1 把闲聊也变成联网）
    print("\n  反向：真闲聊不能被误判成联网检索")
    for text in ("你好", "在吗", "今天好累", "谢谢你", "哈哈哈", "嗯嗯"):
        ck("闲聊「%s」仍是 chat" % text, X._detect_intent(text) == "chat",
           X._detect_intent(text))

    # ---------------- 三、Bug 2 的根因：功能字必须被剥掉 ----------------
    print("\n[三] Bug 2 根因回归：检索词里不能留功能字/动作词的壳")
    # 这些字出现在检索词里 = 会把用户带去"XX的读音/组词"那种词条
    shells = ("整理", "汇总", "归纳", "梳理", "盘点", "帮我", "帮忙", "一下",
              "看看", "看一下", "给我", "请问", "麻烦")
    for text, _, _ in CASES:
        q, _ = X.resolve_search_query(text)
        bad = [w for w in shells if w in q]
        ck("「%s」的检索词不含功能字" % text, not bad, "残留=%s / 词=%r" % (bad, q))
    ck("**绝不能拿「整理」当检索词**（用户实测就是它搜出了「整理的读音」）",
       "整理" not in X.resolve_search_query("整理一下最近的新闻信息")[0],
       X.resolve_search_query("整理一下最近的新闻信息")[0])

    # ---------------- 四、时间限定词必须保留（不是被删掉） ----------------
    print("\n[四] 时间限定词：**保留并规范化**，不能被当噪声删掉")
    ck("「最近」保留在检索词里（时效性是重点）",
       "最近" in X.resolve_search_query("整理一下最近的新闻信息")[0],
       X.resolve_search_query("整理一下最近的新闻信息")[0])
    ck("「今天」规范化成「今日」",
       "今日" in X.resolve_search_query("汇总今天的科技动态")[0],
       X.resolve_search_query("汇总今天的科技动态")[0])
    ck("「本周」保留", "本周" in X.resolve_search_query("看一下本周的动态")[0],
       X.resolve_search_query("看一下本周的动态")[0])
    ck("只留时间词也不许变空（极端输入不丢关键词）",
       bool(X.resolve_search_query("最近的")[0]), X.resolve_search_query("最近的")[0])

    # ---------------- 五、泛化名词裁剪（新闻信息 → 新闻） ----------------
    print("\n[五] 具体名词 + 泛化名词叠加时，裁掉泛化的那个")
    ck("「新闻信息」→「新闻」（同义叠加只留一个）",
       X.resolve_search_query("整理一下最近的新闻信息")[0] == "最近新闻",
       X.resolve_search_query("整理一下最近的新闻信息")[0])
    ck("**只有泛化名词时必须保留**（「今日信息」不能变成「今日」）",
       X.resolve_search_query("整理今天的信息")[0] == "今日信息",
       X.resolve_search_query("整理今天的信息")[0])

    # ---------------- 六、不能把不相关的功能误伤 ----------------
    print("\n[六] 反向保护：别的功能不能被这两条修法带坏")
    ck("漏洞类检索仍自动带 CVE",
       "cve" in X.resolve_search_query("帮我查一下最近的漏洞")[0].lower(),
       X.resolve_search_query("帮我查一下最近的漏洞")[0])
    _greet_q, _greet_hint = X.resolve_search_query("你好")
    ck("纯寒暄不产生检索词（返回空+提示）", _greet_q == "", repr(_greet_q))
    ck("纯寒暄给出可读的中文提示（不是硬搜）", bool(_greet_hint), _greet_hint[:24])
    ck("**闲聊不被改写**（今天好累 → 不能被改成「今日好累」）",
       X.resolve_search_query("今天好累")[0] == "今天好累",
       X.resolve_search_query("今天好累")[0])
    ck("命令类仍是 shell（不能被 query 抢走）",
       X._detect_intent("跑一下 ipconfig") == "shell",
       X._detect_intent("跑一下 ipconfig"))
    ck("删除类仍是 shell（红线要靠它出场）",
       X._detect_intent("删除 C:/a.txt") == "shell",
       X._detect_intent("删除 C:/a.txt"))
    ck("画图意图不被抢走", X._detect_intent("用 Archify 画个架构图") == "diagram",
       X._detect_intent("用 Archify 画个架构图"))
    ck("带网址仍是 scrape", X._detect_intent("抓一下 http://example.com") == "scrape",
       X._detect_intent("抓一下 http://example.com"))
    # 动作词 + 信息名词才是 query；只有动作词不该联网
    ck("只有动作词（「帮我整理一下桌面」）**不该**判 query（那是文件操作）",
       X._detect_intent("帮我整理一下桌面") != "query",
       X._detect_intent("帮我整理一下桌面"))

    # ---------------- 七、幂等与稳定性 ----------------
    print("\n[七] 稳定性：同一输入两次结果一致（可复现，不依赖随机）")
    for text, _, _ in CASES[:3]:
        a = X.resolve_search_query(text)[0]
        b = X.resolve_search_query(text)[0]
        ck("「%s」两次结果一致" % text, a == b, (a, b))
    ck("重复清洗不会把词越洗越短（幂等保护）",
       X.resolve_search_query(X.resolve_search_query("整理一下最近的新闻信息")[0])[0]
       == "最近新闻",
       X.resolve_search_query(X.resolve_search_query("整理一下最近的新闻信息")[0])[0])

    print("\n" + "=" * 74)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
