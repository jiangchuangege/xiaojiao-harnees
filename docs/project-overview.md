# 小焦 · 项目全景（Project Overview）

> 状态：**待补全** —— 按用户要求，本轮先只放「待办清单」；全景正文稍后再写。
> 分支：`release/stabilize-20260913` ｜ 安全第一批进行中（任务 1~4）

---

## 📌 待办清单（Backlog）

| # | 事项 | 位置 | 发现于 | 状态 |
| --- | --- | --- | --- | --- |
| 3.5 | 界面切模型会把 `models[i].api_key` 写回 `brain.api.api_key`，等于把明文密钥又写回控制文件 | 主程序里「切模型」那段（约第 4104 行） | 安全第一批·任务 3 | ⏳ 待修（任务 4 之后另开一轮） |

### 3.5 详情：明文密钥会被写回控制文件

**现象**：控制文件 `xiaojiao_control.json` 的 `models` 数组里，每个模型各自带一份 `api_key`。
在设置页切换模型时，程序把选中模型的那份 `api_key` 直接搬进 `brain.api.api_key`，
于是任务 3 刚清空的明文密钥又被写回文件了。

**影响**：任务 3 的「环境变量优先」只覆盖 `brain.api.api_key` 这一处**读取**；
只要用户在界面上切一次云模型，明文就会重新落进文件 —— 目前剩下那把
`models[1].api_key` 与 `brain.api.api_key` 本来就是同一个 key。

**修法（候选，未定）**：
- 切模型时也走环境变量优先（复用 `_resolve_llm_key`），别把明文直接搬进 `brain.api.api_key`；
- 或者让 `models[*].api_key` 只存 `env:XIAOJIAO_API_KEY` 这类**引用**，不存明文。

**验收**：在界面上切一次云模型后跑 `python tools/check_secrets.py`，明文命中数不应增加
（当前基线：1 处，即 `models[1].api_key`）。

---

## 📎 相关记录

- 安全第一批任务 1~3 的改动与测试数据见 `CHANGELOG.md` 与各次 commit message。
- 密钥迁移方法见 `README.md` 的「🔑 密钥用环境变量（推荐）」一节。
