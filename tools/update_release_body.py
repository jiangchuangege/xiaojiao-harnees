# -*- coding: utf-8 -*-
"""把这个仓库的 GitHub Release 正文更新到当前状态（2026-09-19 这一版；**不写死 commit SHA** ——
写死就会过期，线上到底指着哪个 commit 由 `git ls-remote origin refs/tags/v1.0` 说了算）。
**本文件里的 `BODY` 就是那份正文的唯一真源** —— 改完跑一次，线上与仓库就不会各说各话
（实测核对过：线上正文与本文件逐字相同）。

Token 从两处找，找到就用，找不到就如实说"没有凭据"（不猜、不乱试）：
  ① 环境变量 GITHUB_TOKEN / GH_TOKEN；
  ② Windows 凭据管理器里的 github.com 凭据（`git credential fill` 读出来）。
"""
import json
import os
import subprocess
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = "jiangchuangege/xiaojiao-harness"
TAG = "v1.0"


def token():
    for k in ("GITHUB_TOKEN", "GH_TOKEN", "XIAOJIAO_GITHUB_TOKEN"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v, "环境变量 %s" % k
    try:
        r = subprocess.run(["git", "credential", "fill"], cwd=".",
                           input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20)
        pw = ""
        for line in (r.stdout or "").splitlines():
            if line.startswith("password="):
                pw = line.split("=", 1)[1].strip()
        if pw:
            return pw, "git 凭据管理器"
    except Exception as e:      # noqa: silent-ok — 读不到就退化成"没有"
        print("（凭据管理器读不到：%s）" % e)
    return "", ""


BODY = """## 这一版是什么

**载体优先架构的本地 AI 助手**：能力不在模型权重里，在模型之外的载体里。
模型是可替换的火种（4B / 70B / 任意 OpenAI 兼容接口），记忆、工具、人格、安全边界一条不丢。

**最强的一点**：状态不是"写进提示词劝它"，而是**代码层真的改它这一轮手里的世界** ——
同一句话，精力 0.95 与 0.10 得到的工具表不同（实测 6 → 0），而且这些改动会被记成因果回流到下一轮策略。

**方向是能力无上限**：上限由载体决定，不由参数决定。

## 本版要点（相对上一版）

- **感知层拆成「事」与「我」**：事（这句话在说什么）给检索，我（心里起了什么）给心；
  实测用「事」检索 top1 命中 10/10、用「我」2/10（用户侧先验是 9/10 与 5/10，两套都记在代码注释里）
- **心接回**：心那句话按原文作为 assistant 消息插在用户消息紧前面（只有新起的心才接，不重复灌）
- **检索精排两处收口**：`RERANK_GAP` 0.10 → 0.50；判官不可用时不再全量放行，改按阈值卡一道
- **三处注入只给事实**：存在自述 / 内里 / 思维流事实块（后者以前一次都没进过上下文，本版接上）
- **堵住自我回灌**：它自己上一轮的错答不再被当成"用户说过的事实"直接使用（0.94 → 复核档）
- **存量重复清理**：记忆向量库 2962 → 2331 条；**偏好库 18 → 1 条**（全部先备份、留档不删）
- **写入侧去重**（用户实测补的一刀）：同一个问题又问一次 → **刷新原行、不新增** ——
  真机复测：同一句连发两次，库里一条没多（此前是问一遍长一行）
- **用户本人的事实：1/5 → 5/5**：把用户说过的原话作为 assistant 一条摆在**紧挨生成**的位置接回给它自己
  （"心接回"同一招），只有它**又说"我没有记录"**时才由载体拿原话兜底并明写来源；三版做法与实测数据记在 CHANGELOG
- **（2026-09-19）"否认兜底"对记忆库形状的行整条失效 → 已修**：取原话那一环只认
  `…用户：我叫张三…` 这一种行形状，而记忆库的行**整行就是用户那句话**（没有 `用户：` 标记）——
  于是"它否认就带原话重问 / 载体兜底"**根本不触发**。改成两种形状都认，并给无标记的行加两道闸
  （必须第一人称 + 必须含问到的那个词）。`test_memory_recall` **使用率 2~3/5 → 5/5**（同一批样本复测）。
  如实说明：那 5/5 里**至少 1 项是字符串判据的巧合**（有一轮它答的是工具渲染出的代码块，恰好含 `Python`），
  真实质量按 4/5 看更实；同时给该自测加了 `--show-answer`，好分清"模型没答"和"判据被叫法冤枉"。
- **（2026-09-19）偏好库里清掉 3 条"假偏好" + 补上让它长不回来的闸**：感知层那行
  「偏向（来自偏好）」原本一直在摆一句心象（「数字在眼前转，像被甩进一个没有边界的漩涡…」）——
  那是**它自己的心象被当成"偏好"摆回它面前**。存量 4 条里 3 条不合格（2 条把心象原句抄了一遍、
  1 条没有回看素材），清完只剩真的一条「我好像老是注意猫」（**挪进 `logs/quarantine/`，不删**）。
  根因是原来只查"一模一样"，近义照抄一概放行、`form()` 自己什么都收；现在新增确定性判据
  `looks_like_preference()`：**必须有回看倾向的字眼 + 必须有素材 + 跟素材不许字面相同**。
  ⚠️ 这条判据第一版用**向量余弦**判"像不像素材"，结果把**真偏好**挡了（回看结论天然跟素材同话题）
  —— 当天在 `test_inner.py` 上翻车并改成只看字面，过程如实记在 CHANGELOG 里。
- **（2026-09-19）两个体检工具的假红 + 一处文档星号**：`check_brain_paths.py` 遇上带空格的路径
  （`--model "C:/…/xiaojiao harness/X.gguf"`）会把后半截当成新路径 → 误报"路径不存在"（配置本来是对的）；
  `CHANGELOG.md` 有一句加粗按 CommonMark 侧翼规则**不成对**，星号会原样显示。两处都修了。
- **新增一图一文**：《一具身体，等一颗火种：小焦的器官、大脑与心》—— 大脑/心/器官总图 + 器官对照表
- **真 bug 修复**：`/api/video/promptkb` 永远返回 0；`llama-swap.yaml` 的 `coder` 死路由；
  `llama-swap.yaml` 里带空格的模型路径缺引号（这是"模型 500 / upstream command exited prematurely"的真因）
- **文档与原理同步**：**72 份 `docs/*.md`**（全库 markdown 100+ 份）+ CHANGELOG；口径改成"能力无上限"；
  `check_principles` 12/12、`check_docs` 错误 0、**154** 张原理图 0 问题

## 怎么自己验（一条命令）

```
python run_all_tests.py        # 闸门 13 + 自测 92 + 工具自测 + 全量套件，一张表
```

跑完会给「通过 / 失败 / ⚠️ 提醒 / ⏭ 跳过」四列 —— **跳过与提醒都不算通过**。
最近一次实况：**107 项 ｜ 通过 91 ｜ 失败 1 ｜ 提醒 2 ｜ 跳过 13**，唯一那条红是内嵌的全量套件
在那一轮撞上外部网络抖动（247~248/249），同一次运行里单跑 `tests/stress/run_all.py` 是 100%。

## 如实说明（不粉饰）

- 交叉检查默认关（接上了 ≠ 默认在跑，它要成倍调用模型）
- 全库代码审查**没有跑完**，不声称"零 bug"
- **13 项是"跳过"不是"通过"**：它们需要外网/浏览器/大脑在跑；另外**模型相关的那几项会偶发翻红**
  （每次红的不是同一条）—— 这是现状，不当作已修
- 两处「⚠️ 提醒」不是代码问题，理由逐条写在 `run_all_tests.py` 的 `ADVISORY` 里
  （云大脑未配置＝可选功能没开；明文 key 命中的文件被 `.gitignore` 排除、不入库）
- "它是否真正活过来"这一层**原则上不可验证**（不是"暂未验证"）；
  可验证的部分（工具表长度、精力读数、挂起动作、日志与自测）均为真实记录

完整记录见仓库 `CHANGELOG.md` 的 `[v1.0]` 段。
"""


def main():
    tk, where = token()
    if not tk:
        print("❌ 没找到 GitHub 凭据（环境变量 GITHUB_TOKEN/GH_TOKEN、git 凭据管理器都是空）")
        print("   正文已写好，可直接拿去网页上粘贴；或设一个 token 再跑本脚本。")
        return 1
    print("用凭据：%s" % where)

    def api(url, data=None, method="GET"):
        # 【为什么要自己跟跳转】实测踩到：PATCH 时 GitHub 会回 307（Temporary Redirect），
        #   而 urllib 默认**不**对 PATCH 跟跳转 → 直接抛 HTTPError、正文没更新还以为成功了。
        #   所以这里手动跟最多 3 跳，并且**保持同样的 method 和 body**。
        for _hop in range(4):
            req = urllib.request.Request(
                url, data=(json.dumps(data).encode("utf-8") if data is not None else None),
                method=method,
                headers={"Authorization": "Bearer %s" % tk, "User-Agent": "xiaojiao-release",
                         "Accept": "application/vnd.github+json",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 307, 308):
                    loc = e.headers.get("Location") or ""
                    if loc:
                        if loc.startswith("/"):
                            loc = "https://api.github.com" + loc
                        print("（跟一跳：%s）" % loc[:90])
                        url = loc
                        continue
                raise

    rel = api("https://api.github.com/repos/%s/releases/tags/%s" % (REPO, TAG))
    print("现有 Release：%s（id=%s，发布 %s）" % (rel.get("name"), rel.get("id"), rel.get("published_at")))
    out = api("https://api.github.com/repos/%s/releases/%s" % (REPO, rel.get("id")),
              data={"body": BODY, "name": "v1.0 · 小焦（载体优先架构的本地 AI 助手）",
                    "draft": False, "prerelease": False}, method="PATCH")
    print("✅ 已更新：%s ｜ tag=%s ｜ %s" % (out.get("html_url"), out.get("tag_name"),
                                            out.get("updated_at") or out.get("published_at")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
