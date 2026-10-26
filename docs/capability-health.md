# 能力体检（这台机器上能不能用）

> 由 `python tools/health_capability.py --save` 实跑生成。数字不是手写的。

外部条件：ComfyUI=在 ｜ Chrome=有 ｜ node=有 ｜ 外网=通

**合计 101 ｜ 可用 70 ｜ 坏了 0 ｜ 报错 0 ｜ 需条件 5 ｜ 未实测 23 ｜ 跳过 0**

| 工具 | 来源 | 结论 | 说明 |
| --- | --- | --- | --- |
| `analyze_dependencies` | 插件 | ok | 705 字 / 0.7s |
| `archify_batch` | 插件 | ok | 8 字 / 0.0s |
| `archify_check` | 插件 | ok | 255 字 / 0.2s |
| `archify_compare` | 插件 | ok | 817 字 / 0.2s |
| `archify_doctor` | 插件 | ok | 575 字 / 0.1s |
| `archify_guide` | 插件 | ok | 277 字 / 0.1s |
| `archify_inspect` | 插件 | ok | 8 字 / 0.0s |
| `archify_metrics` | 插件 | ok | 547 字 / 0.0s |
| `archify_read_example` | 插件 | ok | 8 字 / 0.0s |
| `archify_read_schema` | 插件 | ok | 8 字 / 0.0s |
| `archify_read_skill` | 插件 | ok | 13020 字 / 0.0s |
| `archify_render` | 插件 | ok | 8 字 / 0.0s |
| `archify_validate` | 插件 | ok | 8 字 / 0.0s |
| `archify_visual_check` | 插件 | ok | 274 字 / 0.1s |
| `asset_intel_lookup` | 插件 | ok | 163 字 / 1.3s |
| `browser_session` | 插件 | ok | 3242 字 / 0.0s |
| `bulk_fetch` | 插件 | ok | 81 字 / 1.3s |
| `bulk_get` | 插件 | ok | 81 字 / 0.7s |
| `bulk_stealthy_fetch` | 插件 | ok | 83 字 / 1.7s |
| `causal_counterfactual` | 插件 | ok | 437 字 / 0.0s |
| `causal_facts` | 插件 | ok | 91 字 / 0.0s |
| `causal_invalidate` | 插件 | ok | 88 字 / 0.1s |
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
| `check_env` | 内置 | ok | 143 字 / 0.6s |
| `ci_read_file` | 插件 | ok | 26 字 / 0.0s |
| `ci_search_files` | 插件 | ok | 56 字 / 0.3s |
| `ebook_grab` | 插件 | ok | 294 字 / 1.5s |
| `ebook_manifest` | 插件 | ok | 75 字 / 2.9s |
| `fetch` | 插件 | ok | 958 字 / 1.8s |
| `fetch_url` | 内置 | ok | 577 字 / 1.4s |
| `get` | 插件 | ok | 156 字 / 1.5s |
| `get_file_info` | 插件 | ok | 173 字 / 0.0s |
| `get_ip` | 插件 | ok | 16 字 / 4.7s |
| `get_nginx_status` | 插件 | ok | 86 字 / 2.1s |
| `get_weather` | 插件 | ok | 21 字 / 2.1s |
| `grep_files` | 内置 | ok | 68 字 / 0.0s |
| `js_calc` | 插件 | ok | 11 字 / 0.2s |
| `list_files` | 内置 | ok | 10 字 / 0.0s |
| `list_sessions` | 插件 | ok | 1440 字 / 0.0s |
| `make_request` | 插件 | ok | 156 字 / 2.5s |
| `net_dns` | 插件 | ok | 21 字 / 0.1s |
| `net_ip` | 插件 | ok | 167 字 / 0.7s |
| `net_port` | 插件 | ok | 14 字 / 0.1s |
| `open_request_session` | 插件 | ok | 500 字 / 0.0s |
| `open_session` | 插件 | ok | 963 字 / 1.5s |
| `project_tree` | 插件 | ok | 362857 字 / 0.1s |
| `rea_help` | 插件 | ok | 39 字 / 0.0s |
| `rea_status` | 插件 | ok | 220 字 / 0.5s |
| `read_file` | 内置 | ok | 99 字 / 0.0s |
| `read_memory` | 插件 | ok | 7 字 / 0.0s |
| `save_memory` | 插件 | ok | 29 字 / 0.0s |
| `search_files` | 内置 | ok | 5 字 / 0.0s |
| `session_fetch` | 插件 | ok | 1074 字 / 1.4s |
| `session_make_request` | 插件 | ok | 355 字 / 0.7s |
| `stealthy_fetch` | 插件 | ok | 958 字 / 2.0s |
| `web_search` | 插件 | ok | 42 字 / 0.0s |
| `ws_list_directory` | 插件 | ok | 5786 字 / 0.0s |
| `ws_search_files` | 插件 | ok | 56 字 / 0.3s |
| `asset_intel_search` | 插件 | 需条件 | 缺配置：⚠️ **「CVE → 受影响 IP」需要资产测绘数据源 Key**，现在一个都没配。  为什么必须 Key：全网扫描数据只有 Shodan |
| `ci_search_content` | 插件 | 需条件 | 慢：49s（可能在做重活，超 30s 记这里） |
| `count_code_lines` | 插件 | 需条件 | 慢：30s（可能在做重活，超 30s 记这里） |
| `get_ip_info` | 插件 | 需条件 | 免费额度/限流：RateLimited |
| `ws_search_content` | 插件 | 需条件 | 慢：59s（可能在做重活，超 30s 记这里） |
| `archify_deliver` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `archify_preview` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `ask_user` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `asset_intel_status` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `background` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `background_result` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `collect_vulnerabilities` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `connect_db` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `describe_table` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `download` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `edit_file` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `export_table_json` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `generate_music` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `generate_video` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `list_tables` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `open_app` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `query_db` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `rea_call` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `rea_do` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `run_command` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `screenshot` | 插件 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `suggest_organize` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `write_file` | 内置 | 未实测 | 有副作用，不真跑（参数就绪：齐） |
| `close_session` | 插件 | 需参数 | 参数不合适：close_session 需要提供 session_id |
| `rea_tools` | 插件 | 需参数 | 参数不合适：REA 工具（共 229 个）前 20 个 —— 调法：rea_call，tool 填名字，args 传 JSON · inspect_an |
| `scrape_with_selector` | 插件 | 需参数 | 参数不合适：选择器 h1 没有匹配到内容（页面里没有这个元素，或元素是空的）—— 可换个选择器，或改用 fetch/get 抓整页 |
