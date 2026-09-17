# -*- coding: utf-8 -*-
"""把这个仓库的 GitHub Release 正文更新到当前状态（v1.0 = 4d9bd2d）。

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
- **存量重复清理**：记忆向量库 2962 → 2331 条；偏好库 18 → 4 条（全部先备份、留档不删）
- **真 bug 修复**：`/api/video/promptkb` 永远返回 0；`llama-swap.yaml` 的 `coder` 死路由
- **文档与原理同步**：18 份文档 + CHANGELOG；口径改成"能力无上限"；
  `check_principles` 12/12、`check_docs` 错误 0、153 张原理图 0 问题

## 如实说明（不粉饰）

- 交叉检查默认关（接上了 ≠ 默认在跑，它要成倍调用模型）
- 全库代码审查**没有跑完**，不声称"零 bug"
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
        req = urllib.request.Request(
            url, data=(json.dumps(data).encode("utf-8") if data is not None else None),
            method=method,
            headers={"Authorization": "Bearer %s" % tk, "User-Agent": "xiaojiao-release",
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

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
