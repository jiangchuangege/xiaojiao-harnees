# -*- coding: utf-8 -*-
"""一个假的 REA MCP 服务（只给自测用）：按 MCP stdio 协议回 initialize / tools/list / tools/call。

为什么要它：真 REA 是 229 个工具、要 node、要装包、冷启动十几秒 ——
自测不能依赖那些。这个假服务把**协议形状**钉住（JSON-RPC 按行、握手、列表、调用、报错），
插件对接得对不对就能在 1 秒内验完；真机连通性另有一条单独的活儿（在跑的那份里验）。
"""
import json
import sys

TOOLS = [
    {"name": "inspect_artifact", "description": "检查一个本地文件（PE/ELF/APK/JS 等）的结构",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "binary_overview", "description": "给一个二进制做总览：段、函数数、字符串数",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "search_strings", "description": "在目标里搜字符串",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"},
                                                     "pattern": {"type": "string"}}}},
]


def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
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
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            _out({"jsonrpc": "2.0", "id": mid,
                  "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                             "serverInfo": {"name": "fake-rea", "version": "0.0.1"}}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "inspect_artifact":
                path = str(args.get("path") or "")
                if not path:
                    _out({"jsonrpc": "2.0", "id": mid,
                          "result": {"isError": True, "content": [
                              {"type": "text", "text": "缺少参数 path"}]}})
                    continue
                _out({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                    {"type": "text",
                     "text": "格式：PE32+ ｜ 段：.text .data .rsrc ｜ 函数：128 个 ｜ 路径：%s" % path}]}})
            elif name == "binary_overview":
                _out({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                    {"type": "text", "text": "总览：段 3 个，函数 128 个，字符串 456 条"}]}})
            elif name == "search_strings":
                pat = str(args.get("pattern") or "")
                _out({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                    {"type": "text", "text": "命中 2 条：%s-api.example.com ／ %s-token" % (pat, pat)}]}})
            elif name == "slow_tool":
                pass          # 故意不回，用来测超时
            elif name == "boom":
                _out({"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": []}})
            else:
                _out({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32602, "message": "unknown tool: %s" % name}})
        elif mid is not None:
            _out({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": "method not found: %s" % method}})


if __name__ == "__main__":
    main()
