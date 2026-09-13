# 小焦 · 项目全景（Project Overview）

> 状态：**待补全** —— 按用户要求，本轮先只放「待办清单」；全景正文稍后再写。
> 分支：`release/stabilize-20260913` ｜ 安全第一批进行中（任务 1~4）

---

## 📌 待办清单（Backlog）

| # | 事项 | 位置 | 发现于 | 状态 |
| --- | --- | --- | --- | --- |
| 3.5 | 界面切模型会把 `models[i].api_key` 写回 `brain.api.api_key`，等于把明文密钥又写回控制文件 | 主程序 `/api/model/select`（切模型那段） | 安全第一批·任务 3 | ✅ **已解决**（安全第一批·任务C） |

### 3.5 详情：明文密钥会被写回控制文件 —— ✅ 已解决

**现象**：控制文件 `xiaojiao_control.json` 的 `models` 数组里，每个模型各自带一份 `api_key`。
在设置页切换模型时，程序把选中模型的那份 `api_key` 直接搬进 `brain.api.api_key`，
于是任务 3 刚清空的明文密钥又被写回文件了。

**影响**：任务 3 的「环境变量优先」只覆盖 `brain.api.api_key` 这一处**读取**；
只要用户在界面上切一次云模型，明文就会重新落进文件 —— `models[1].api_key`
与 `brain.api.api_key` 本来就是同一个 key。

**实际修法（任务C 落地）**：
1. `/api/model/select` 里不再搬 `m.get("api_key")` 进 `brain.api.api_key`，只切 `model` 名，
   `brain["api"]["api_key"]` 一律写 `""`；密钥统一由 `_resolve_llm_key()` 从环境变量
   `XIAOJIAO_API_KEY` 读。
2. 云端探测改用**解析后的** key（`_cloud_key_problem(base, _resolve_llm_key(brain), model)`），
   否则会用空 Key 去撞 401、再把结论带偏。
3. `_cloud_key_problem()` 增加"压根没 Key"分支：直接提示去设环境变量，不再报成"Key 被服务商拒了"。
4. 清空控制文件里 `models[*].api_key` 的历史明文（`brain/api/api_key` 早在任务 2 已清空）。

**验收（已实测通过）**：
- 真实走 `/api/model/select` 来回切（agnes ↔ 本地）3 次：每次切完 `brain/api/api_key` 长度都是 0，
  `LLM_KEY` 始终等于环境变量，磁盘上所有 `api_key` 也都是空。
- 对照证明：**内存里**给 `models[1].api_key` 塞一把假明文再切一次，捕获到的 `brain["api"]`
  仍是 `{"api_key": ""}` —— 说明"搬明文"的路径确实断了（旧代码这里会带上那把假 Key）。

---

## 📎 相关记录

- 安全第一批任务 1~3 的改动与测试数据见 `CHANGELOG.md` 与各次 commit message。
- 密钥迁移方法见 `README.md` 的「🔑 密钥用环境变量（推荐）」一节。
