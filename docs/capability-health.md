# 能力体检（这台机器上能不能用）

> 由 `python tools/health_capability.py --save` 实跑生成。数字不是手写的。

外部条件：ComfyUI=没开 ｜ Chrome=有 ｜ node=有 ｜ 外网=通

**合计 120 ｜ 可用 114 ｜ 坏了 0 ｜ 需参数 0 ｜ 需条件 3 ｜ 未实测 3 ｜ 跳过 0**

| 工具 | 来源 | 结论 | 说明 |
| --- | --- | --- | --- |
| `analyze_dependencies` | 插件 | ok | 705 字 / 1.2s |
| `archify_batch` | 插件 | ok | 8 字 / 0.0s |
| `archify_check` | 插件 | ok | 255 字 / 0.2s |
| `archify_compare` | 插件 | ok | 817 字 / 0.2s |
| `archify_deliver` | 插件 | ok | 沙箱实测通过：交付产物真的写出来了（0.3s） |
| `archify_doctor` | 插件 | ok | 575 字 / 0.2s |
| `archify_guide` | 插件 | ok | 277 字 / 0.1s |
| `archify_inspect` | 插件 | ok | 8 字 / 0.0s |
| `archify_metrics` | 插件 | ok | 641 字 / 0.0s |
| `archify_preview` | 插件 | ok | 沙箱实测通过：生成了 HTML（0.3 秒，不再挂 240 秒）（0.5s） |
| `archify_read_example` | 插件 | ok | 8 字 / 0.0s |
| `archify_read_schema` | 插件 | ok | 8 字 / 0.0s |
| `archify_read_skill` | 插件 | ok | 13020 字 / 0.0s |
| `archify_render` | 插件 | ok | 8 字 / 0.0s |
| `archify_validate` | 插件 | ok | 沙箱实测通过：spec 通过校验（0.3s） |
| `archify_visual_check` | 插件 | ok | 274 字 / 0.1s |
| `asset_intel_lookup` | 插件 | ok | 163 字 / 1.6s |
| `asset_intel_status` | 插件 | ok | 沙箱实测通过：数据源状态（0.0s） |
| `audit_answer` | 插件 | ok | 182 字 / 0.0s |
| `audit_history` | 插件 | ok | 564 字 / 0.0s |
| `background` | 内置 | ok | 沙箱实测通过：拿到后台任务号（0.0s） |
| `background_result` | 内置 | ok | 沙箱实测通过：按 job_id 查回了后台任务结果（1.2s） |
| `browser_session` | 插件 | ok | 3242 字 / 0.0s |
| `bulk_fetch` | 插件 | ok | 81 字 / 10.3s |
| `bulk_get` | 插件 | ok | 81 字 / 4.3s |
| `bulk_stealthy_fetch` | 插件 | ok | 83 字 / 2.5s |
| `causal_counterfactual` | 插件 | ok | 437 字 / 0.0s |
| `causal_facts` | 插件 | ok | 91 字 / 0.0s |
| `causal_invalidate` | 插件 | ok | 88 字 / 0.0s |
| `causal_invalidate_pattern` | 插件 | ok | 90 字 / 0.0s |
| `causal_lesson` | 插件 | ok | 92 字 / 0.0s |
| `causal_memory_map` | 插件 | ok | 96 字 / 0.0s |
| `causal_patterns` | 插件 | ok | 94 字 / 0.0s |
| `causal_record` | 插件 | ok | 72 字 / 0.0s |
| `causal_remember` | 插件 | ok | 88 字 / 0.0s |
| `causal_report` | 插件 | ok | 184 字 / 0.0s |
| `causal_resolve` | 插件 | ok | 188 字 / 0.0s |
| `causal_search` | 插件 | ok | 80 字 / 0.0s |
| `causal_trace` | 插件 | ok | 80 字 / 0.0s |
| `causal_trace_one` | 插件 | ok | 61 字 / 0.0s |
| `causal_unified` | 插件 | ok | 93 字 / 0.0s |
| `causal_warn` | 插件 | ok | 179 字 / 0.1s |
| `check_env` | 内置 | ok | 143 字 / 3.6s |
| `ci_read_file` | 插件 | ok | 26 字 / 0.0s |
| `ci_search_content` | 插件 | ok | 33528 字 / 72.4s（慢：72s） |
| `ci_search_files` | 插件 | ok | 56 字 / 2.1s |
| `close_session` | 插件 | ok | 沙箱实测通过：开了又关成功了（3.4s） |
| `cn_num_to_int` | 插件 | ok | 22 字 / 0.0s |
| `collect_vulnerabilities` | 插件 | ok | 沙箱实测通过：拿到真实 NVD 数据（只取 1 条，不刷人家接口）（6.2s） |
| `connect_db` | 插件 | ok | 沙箱实测通过：连上了临时库（0.0s） |
| `count_code_lines` | 插件 | ok | 303 字 / 47.9s（慢：48s） |
| `describe_table` | 插件 | ok | 沙箱实测通过：给了列定义（0.0s） |
| `download` | 插件 | ok | 沙箱实测通过：文件真下到本地了（40 字节）（3.0s） |
| `ebook_grab` | 插件 | ok | 294 字 / 1.8s |
| `ebook_manifest` | 插件 | ok | 75 字 / 3.4s |
| `edit_file` | 内置 | ok | 沙箱实测通过：替换真的生效了（0.0s） |
| `evidence_stats` | 插件 | ok | 150 字 / 0.0s |
| `evolve_gate` | 插件 | ok | 315 字 / 0.0s |
| `evolve_report` | 插件 | ok | 沙箱实测通过：给出了改进清单（含证据与动作）（0.1s） |
| `experience_stats` | 插件 | ok | 沙箱实测通过：给出了经验库快照（0.0s） |
| `export_table_json` | 插件 | ok | 沙箱实测通过：导出成 JSON（0.0s） |
| `fetch` | 插件 | ok | 958 字 / 2.5s |
| `fetch_url` | 内置 | ok | 577 字 / 1.4s |
| `forge_plugin` | 插件 | ok | 92 字 / 0.0s |
| `get` | 插件 | ok | 156 字 / 1.0s |
| `get_file_info` | 插件 | ok | 沙箱实测通过：给了大小/时间（0.0s） |
| `get_ip` | 插件 | ok | 16 字 / 8.5s |
| `get_ip_info` | 插件 | ok | 800 字 / 1.9s |
| `get_weather` | 插件 | ok | 21 字 / 2.0s |
| `grep_files` | 内置 | ok | 68 字 / 0.0s |
| `int_to_cn_num` | 插件 | ok | 25 字 / 0.0s |
| `js_calc` | 插件 | ok | 11 字 / 0.2s |
| `list_files` | 内置 | ok | 20 字 / 0.0s |
| `list_sessions` | 插件 | ok | 1440 字 / 0.0s |
| `list_tables` | 插件 | ok | 沙箱实测通过：列了表（应含 t）（0.0s） |
| `make_request` | 插件 | ok | 156 字 / 3.2s |
| `net_dns` | 插件 | ok | 21 字 / 0.1s |
| `net_ip` | 插件 | ok | 167 字 / 0.7s |
| `net_port` | 插件 | ok | 14 字 / 0.1s |
| `open_request_session` | 插件 | ok | 500 字 / 0.0s |
| `open_session` | 插件 | ok | 963 字 / 1.4s |
| `parity_report` | 插件 | ok | 276 字 / 0.1s |
| `project_list` | 插件 | ok | 107 字 / 0.0s |
| `project_resume` | 插件 | ok | 12 字 / 0.0s |
| `project_start` | 插件 | ok | 16 字 / 0.0s |
| `project_status` | 插件 | ok | 35 字 / 0.0s |
| `project_tree` | 插件 | ok | 409861 字 / 0.2s |
| `query_db` | 插件 | ok | 沙箱实测通过：跑出结果（应含 小焦）（0.0s） |
| `rea_call` | 插件 | ok | 沙箱实测通过：真打开了 PE 文件（应返回 format=pe）（1.2s） |
| `rea_do` | 插件 | ok | 沙箱实测通过：载体自己选工具并真跑成功（0.0s） |
| `rea_help` | 插件 | ok | 39 字 / 0.0s |
| `rea_status` | 插件 | ok | 沙箱实测通过：REA 服务状态（0.5s） |
| `rea_tools` | 插件 | ok | 沙箱实测通过：搜出了工具目录（返回是说明文本，不是错误）（0.0s） |
| `read_file` | 内置 | ok | 沙箱实测通过：读回来了（0.0s） |
| `read_memory` | 插件 | ok | 7 字 / 0.0s |
| `run_command` | 内置 | ok | 沙箱实测通过：命令真跑了（返回里应有 health-ok）（0.3s） |
| `save_memory` | 插件 | ok | 29 字 / 0.0s |
| `scrape_with_selector` | 插件 | ok | 156 字 / 2.1s |
| `screenshot` | 插件 | ok | 沙箱实测通过：返回图片路径（载体自己开会话，不动你的）（2.1s） |
| `search_files` | 内置 | ok | 5 字 / 0.0s |
| `session_fetch` | 插件 | ok | 1074 字 / 2.2s |
| `session_make_request` | 插件 | ok | 355 字 / 0.8s |
| `skill_list` | 插件 | ok | 614 字 / 0.0s |
| `skill_recall` | 插件 | ok | 65 字 / 0.0s |
| `stealthy_fetch` | 插件 | ok | 958 字 / 3.0s |
| `suggest_organize` | 内置 | ok | 沙箱实测通过：给了整理建议（只读）（0.1s） |
| `task_list` | 插件 | ok | 648 字 / 0.0s |
| `task_start` | 插件 | ok | 40 字 / 0.0s |
| `task_status` | 插件 | ok | 32 字 / 0.0s |
| `web_search` | 插件 | ok | 42 字 / 0.0s |
| `write_file` | 内置 | ok | 沙箱实测通过：磁盘上真有这个文件、内容对（1.0s） |
| `ws_list_directory` | 插件 | ok | 5708 字 / 0.0s |
| `ws_search_content` | 插件 | ok | 34608 字 / 107.5s（慢：107s） |
| `ws_search_files` | 插件 | ok | 56 字 / 0.4s |
| `asset_intel_search` | 插件 | 需条件 | 缺配置：⚠️ **「CVE → 受影响 IP」需要资产测绘数据源 Key**，现在一个都没配。  为什么必须 Key：全网扫描数据只有 Shodan |
| `generate_video` | 插件 | 需条件 | 缺：ComfyUI(127.0.0.1:8188 没开) |
| `get_nginx_status` | 插件 | 需条件 | 网络/代理不可用：调用失败: HTTPConnectionPool(host='127.0.0.1', port=9913): Max r |
| `ask_user` | 内置 | 未实测 | 要你本人回答才能完成（参数就绪：齐） |
| `generate_music` | 插件 | 未实测 | 真跑约 2 分钟、占显存（--include-heavy 才跑）（参数就绪：齐） |
| `open_app` | 内置 | 未实测 | 会真的在你桌面上打开程序（打扰你）（参数就绪：齐） |
