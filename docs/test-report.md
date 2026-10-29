# 自测报告（`tools/run_all_tests.py` 生成）

- 文件：131 个（跳过 1）｜ 断言：4113 / 4121 ｜ 没通过的文件：8 个
- 每文件单独子进程 + 超时 150 秒（超时算「卡死」）；5 路并行，没通过的已串行复测
- 总耗时 103.1 分钟

| 测试文件 | 结论 | 通过/共 | 耗时(秒) | 备注 |
| --- | --- | --- | --- | --- |
| `test_4_gaps.py` | 通过 | 60/60 | 5.5 |  |
| `test_6_capabilities.py` | 卡死 | 0/1 | 600.2 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_agnes_live.py` | 有失败 | 0/1 | 2.0 | 复测：有失败 |
| `test_answer_gate.py` | 通过 | 14/14 | 0.0 |  |
| `test_autonomy.py` | 通过 | 111/111 | 27.4 |  |
| `test_boost.py` | 通过 | 195/195 | 0.7 |  |
| `test_brain_line_cleanup.py` | 通过 | 12/12 | 7.2 |  |
| `test_bug2_dedup.py` | 通过 | 16/16 | 4.4 |  |
| `test_bug3_repeat.py` | 通过 | 20/20 | 0.8 |  |
| `test_bug45_ui.py` | 通过 | 42/42 | 18.9 |  |
| `test_bug6_open_html.py` | 通过 | 12/12 | 16.9 |  |
| `test_capability_parity.py` | 通过 | 37/37 | 0.1 |  |
| `test_carrier.py` | 通过 | 64/64 | 23.2 |  |
| `test_carrier_block.py` | 通过 | 26/26 | 8.2 |  |
| `test_causal_hooks.py` | 通过 | 37/37 | 6.2 |  |
| `test_causal_memory_ext.py` | 通过 | 37/37 | 0.2 |  |
| `test_causal_memory_plugin.py` | 通过 | 25/25 | 3.3 |  |
| `test_central.py` | 通过 | 44/44 | 0.5 |  |
| `test_chain.py` | 通过 | 16/16 | 5.2 |  |
| `test_channel_policy.py` | 通过 | 24/24 | 3.4 |  |
| `test_closed_loop.py` | 卡死 | 0/1 | 902.5 | 复测：卡死；超过 900 秒没结束（已杀掉） |
| `test_cloud_video_spec.py` | 通过 | 57/57 | 10.8 |  |
| `test_cloud_video_worker.py` | 通过 | 10/10 | 5.8 |  |
| `test_cn_number.py` | 通过 | 34/34 | 0.0 |  |
| `test_code_judge.py` | 通过 | 25/25 | 3.2 |  |
| `test_comments_audit.py` | 通过 | 34/34 | 3.5 |  |
| `test_context_merge.py` | 通过 | 91/91 | 3.7 |  |
| `test_cross_check_wired.py` | 通过 | 17/17 | 3.5 |  |
| `test_degen_strategy.py` | 通过 | 13/13 | 0.1 |  |
| `test_degeneration.py` | 通过 | 31/31 | 0.3 |  |
| `test_diagnose_code.py` | 通过 | 39/39 | 3.8 |  |
| `test_docs_audit.py` | 通过 | 42/42 | 0.0 |  |
| `test_dual_check.py` | 通过 | 15/15 | 14.6 |  |
| `test_ebook_plugin.py` | 通过 | 35/35 | 14.7 |  |
| `test_embedder_long.py` | 通过 | 18/18 | 6.6 |  |
| `test_energy.py` | 通过 | 46/46 | 26.1 |  |
| `test_event_what_retrieval.py` | 通过 | 1/1 | 96.1 |  |
| `test_evidence_ledger.py` | 通过 | 35/35 | 0.1 |  |
| `test_fact_doctor.py` | 通过 | 30/30 | 11.7 |  |
| `test_file_claim_correction.py` | 通过 | 11/11 | 0.1 |  |
| `test_fresh_clone.py` | 通过 | 13/13 | 119.1 |  |
| `test_gate_evolve.py` | 通过 | 31/31 | 4.1 |  |
| `test_health.py` | 通过 | 142/142 | 0.5 |  |
| `test_health_integration.py` | 通过 | 38/38 | 8.3 |  |
| `test_heart_back.py` | 通过 | 16/16 | 26.5 |  |
| `test_heartbeat.py` | 通过 | 40/40 | 68.9 |  |
| `test_impression_usage.py` | 有失败 | 0/1 | 266.5 | 复测：有失败 |
| `test_infinity_456.py` | 通过 | 32/32 | 25.5 |  |
| `test_inline_code.py` | 通过 | 13/13 | 32.2 |  |
| `test_inner.py` | 通过 | 54/54 | 6.3 |  |
| `test_inner_facts.py` | 通过 | 7/7 | 4.0 |  |
| `test_inner_joint.py` | 通过 | 28/28 | 1.7 |  |
| `test_input_infinity.py` | 通过 | 27/27 | 0.8 |  |
| `test_interoceptive.py` | 通过 | 23/23 | 243.1 | 复测：通过 |
| `test_last_jump.py` | 通过 | 1/1 | 25.9 | 复测：通过 |
| `test_log_rotation.py` | 通过 | 9/9 | 0.1 |  |
| `test_longform_quality.py` | 通过 | 29/29 | 0.3 |  |
| `test_math_render.py` | 通过 | 9/9 | 7.5 | 复测：通过 |
| `test_mem_filter.py` | 通过 | 26/26 | 7.5 |  |
| `test_mem_source.py` | 通过 | 15/15 | 3.4 |  |
| `test_memory_depth.py` | 通过 | 73/73 | 4.2 |  |
| `test_memory_gate.py` | 通过 | 64/64 | 0.7 |  |
| `test_memory_gate_wiring.py` | 通过 | 16/16 | 4.8 |  |
| `test_memory_plugin_gate.py` | 通过 | 22/22 | 2.1 |  |
| `test_memory_recall.py` | 有失败 | 0/1 | 87.6 | 复测：有失败 |
| `test_memory_upkeep.py` | 通过 | 36/36 | 3.8 |  |
| `test_memory_upkeep_wiring.py` | 通过 | 14/14 | 38.4 |  |
| `test_memory_vec_index.py` | 通过 | 18/18 | 4.2 |  |
| `test_memory_write_dedupe.py` | 通过 | 10/10 | 3.6 |  |
| `test_metacognition.py` | 通过 | 143/143 | 0.2 |  |
| `test_mind.py` | 通过 | 77/77 | 35.6 |  |
| `test_mind_facts.py` | 通过 | 12/12 | 0.1 |  |
| `test_mind_stream.py` | 通过 | 67/67 | 0.1 |  |
| `test_mind_stream_live.py` | 卡死 | 0/1 | 600.0 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_model_add_keeps_video_api.py` | 通过 | 9/9 | 5.3 |  |
| `test_model_name_reconcile.py` | 通过 | 18/18 | 3.0 |  |
| `test_model_router.py` | 通过 | 22/22 | 0.2 |  |
| `test_module_integration.py` | 卡死 | 0/1 | 600.0 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_no_delete.py` | 通过 | 101/101 | 0.3 |  |
| `test_no_plaintext_secrets.py` | 通过 | 10/10 | 13.0 |  |
| `test_paths.py` | 通过 | 23/23 | 0.1 |  |
| `test_perception.py` | 通过 | 41/41 | 6.4 |  |
| `test_perception_infinity.py` | 通过 | 9/9 | 102.3 | 复测：通过 |
| `test_persona.py` | 通过 | 58/58 | 0.1 |  |
| `test_perspective.py` | 通过 | 16/16 | 0.1 |  |
| `test_platform_integration.py` | 通过 | 39/39 | 90.8 |  |
| `test_plugin_forge.py` | 通过 | 21/21 | 0.3 |  |
| `test_preference_gate.py` | 通过 | 18/18 | 0.1 |  |
| `test_preinstall.py` | 通过 | 31/31 | 0.2 |  |
| `test_profile_recall_integration.py` | 跳过 | 0/0 | 0.2 |  |
| `test_profile_system.py` | 通过 | 84/84 | 0.1 |  |
| `test_project_runner.py` | 通过 | 43/43 | 0.2 |  |
| `test_raw.py` | 通过 | 33/33 | 2.9 |  |
| `test_rea_plugin.py` | 通过 | 40/40 | 2.7 |  |
| `test_rea_router.py` | 通过 | 12/12 | 0.1 |  |
| `test_realtime_fact.py` | 通过 | 23/23 | 2.7 |  |
| `test_redline_integration.py` | 通过 | 40/40 | 4.8 |  |
| `test_repeat_all_paths.py` | 通过 | 30/30 | 9.8 |  |
| `test_rerank_gate.py` | 通过 | 14/14 | 0.1 |  |
| `test_retrieval_rerank.py` | 通过 | 22/22 | 0.1 |  |
| `test_route_table.py` | 通过 | 39/39 | 4.1 |  |
| `test_scrape_retry.py` | 通过 | 24/24 | 104.7 |  |
| `test_scrape_save.py` | 通过 | 23/23 | 5.3 |  |
| `test_search_intent.py` | 通过 | 58/58 | 4.1 |  |
| `test_search_modifier.py` | 通过 | 34/34 | 4.4 |  |
| `test_self_echo.py` | 通过 | 19/19 | 42.7 |  |
| `test_self_evolve.py` | 通过 | 28/28 | 42.5 |  |
| `test_self_model.py` | 通过 | 17/17 | 21.8 |  |
| `test_silent_evolve.py` | 通过 | 23/23 | 21.7 |  |
| `test_single_request_limit.py` | 卡死 | 0/1 | 601.9 | 复测：卡死；超过 600 秒没结束（已杀掉） |
| `test_spirit_memory.py` | 通过 | 41/41 | 4.1 |  |
| `test_state_policy.py` | 通过 | 19/19 | 5.0 |  |
| `test_stream_render.py` | 通过 | 22/22 | 480.5 | 复测：通过 |
| `test_task_runner.py` | 通过 | 35/35 | 1.6 |  |
| `test_thinking_loop_vector.py` | 通过 | 22/22 | 3.0 |  |
| `test_time_context.py` | 通过 | 15/15 | 80.0 | 复测：通过 |
| `test_timeline_search.py` | 通过 | 24/24 | 5.1 | 复测：通过 |
| `test_tool_contract.py` | 通过 | 12/12 | 4.5 |  |
| `test_tool_gate.py` | 通过 | 29/29 | 7.6 |  |
| `test_tool_infinity_live.py` | 通过 | 18/18 | 159.5 |  |
| `test_tool_isolation.py` | 通过 | 52/52 | 3.8 |  |
| `test_two_fixes.py` | 通过 | 11/11 | 6.0 |  |
| `test_user_profile.py` | 通过 | 48/48 | 0.1 |  |
| `test_video_audio.py` | 通过 | 27/27 | 50.0 | 复测：通过 |
| `test_video_ui_wiring.py` | 通过 | 37/37 | 4.3 |  |
| `test_vram_policy.py` | 通过 | 25/25 | 0.1 |  |
| `test_wholeness.py` | 通过 | 63/63 | 41.0 |  |
| `test_world.py` | 通过 | 12/12 | 6.6 |  |
| `test_world_firewall.py` | 通过 | 46/46 | 69.5 |  |
| `test_write_judge.py` | 通过 | 31/31 | 35.9 |  |
| `test_write_overwrite_path.py` | 通过 | 21/21 | 32.6 |  |
