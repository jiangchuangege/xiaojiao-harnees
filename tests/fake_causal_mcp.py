# tests/fake_causal_mcp.py —— 假的 causal-memory MCP server（自测用，不联网、不依赖 Rust 二进制）
#
# 为什么要有它：接外部 MCP 服务这条链路的错，几乎都出在**客户端**（握手、按行 JSON-RPC、
# 超时、进程死了要不要重启、参数拼错）。这些错跟"对面是不是真 causal-memory"无关，
# 所以用一个小假服务就能把客户端钉死；真机那条另有一个冒烟测试（用真二进制 + 临时库）。
#
# 用法：python tests/fake_causal_mcp.py          # 按行读 JSON-RPC，按行回
# 行为：initialize / tools/list / tools/call 三件事，工具名与真品保持一致；
#       把每次 tools/call 记到 $FAKE_MCP_LOG（有设的话），供测试核对参数有没有拼对。
import json
import os
import sys

TOOLS = [
    {"name": "record_decision",
     "description": "record a decision → outcome",
     "inputSchema": {"type": "object", "required": ["decision", "outcome", "relation", "task_tag"],
                     "properties": {"decision": {"type": "string"}, "outcome": {"type": "string"},
                                    "relation": {"type": "string"}, "task_tag": {"type": "string"},
                                    "context": {"type": ["string", "null"]}}}},
    {"name": "search_causal",
     "description": "search past causal episodes",
     "inputSchema": {"type": "object", "properties": {"query": {"type": ["string", "null"]},
                                                      "task_tag": {"type": ["string", "null"]},
                                                      "limit": {"type": ["integer", "null"]}}}},
    {"name": "intervention_query",
     "description": "forward simulation before acting",
     "inputSchema": {"type": "object", "required": ["action"],
                     "properties": {"action": {"type": "string"}, "task_tag": {"type": ["string", "null"]}}}},
    {"name": "counterfactual_query",
     "description": "contrast two options",
     "inputSchema": {"type": "object", "required": ["decision", "alternative"],
                     "properties": {"decision": {"type": "string"}, "alternative": {"type": "string"}}}},
    {"name": "trace_cause_chain",
     "description": "multi-hop backward trace",
     "inputSchema": {"type": "object", "required": ["outcome_description"],
                     "properties": {"outcome_description": {"type": "string"},
                                    "max_depth": {"type": ["integer", "null"]}}}},
    {"name": "prediction_report",
     "description": "prediction ledger accuracy",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _log(obj):
    p = os.environ.get("FAKE_MCP_LOG")
    if p:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _reply(mid, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = (line or "").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _reply(mid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                         "serverInfo": {"name": "fake-causal-memory", "version": "0"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            _log({"tool": name, "args": args})
            if name == "record_decision":
                if not args.get("decision") or not args.get("outcome") or not args.get("relation"):
                    _reply(mid, {"content": [{"type": "text", "text": "missing required field"}], "isError": True})
                else:
                    _reply(mid, {"content": [{"type": "text",
                                              "text": "✅ Recorded: [%s] %s →(%s)→ %s (confidence: 0.60, id: 7)"
                                                      % (args.get("task_tag"), args["decision"],
                                                         args["relation"], args["outcome"])}],
                                 "isError": False})
            elif name == "search_causal":
                if not args.get("query"):
                    _reply(mid, {"content": [{"type": "text", "text": ""}], "isError": False})
                else:
                    _reply(mid, {"content": [{"type": "text",
                                              "text": "[bm25/l2] Found 1 past episode(s):\n\n1. [%s] \"%s\"\n   →(prevented)→ \"以前这么干出过事\"\n   confidence: 70%%"
                                                      % (args.get("task_tag"), args["query"])}],
                                 "isError": False})
            elif name == "intervention_query":
                _reply(mid, {"content": [{"type": "text",
                                          "text": "[bm25] Predicted effect(s) of \"%s\"\n\nChain 1 ⚠️ WARNING: hop 1 →(prevented)→ \"以前出过事\""
                                                  % args.get("action")}], "isError": False})
            elif name == "trace_cause_chain":
                _reply(mid, {"content": [{"type": "text",
                                          "text": "chain: 崩 ← OOM ← 缓存没 TTL（关于 %s）" % args.get("outcome_description")}],
                             "isError": False})
            elif name == "counterfactual_query":
                _reply(mid, {"content": [{"type": "text",
                                          "text": "A(%s) vs B(%s): prefer_a" % (args.get("decision"), args.get("alternative"))}],
                             "isError": False})
            elif name == "prediction_report":
                _reply(mid, {"content": [{"type": "text", "text": "准确率：3/4 = 75%（按领域：显存 1/1）"}],
                             "isError": False})
            else:
                _reply(mid, {"content": [{"type": "text", "text": "unknown tool"}], "isError": True})
        elif mid is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                         "error": {"code": -32601, "message": "method not found"}},
                                        ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
