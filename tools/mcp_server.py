import json
import threading

class JerryMcpServer:
    def __init__(self, original_update_balance_func, file_lock: threading.Lock):
        self.tools = {}
        # 🔒 接管主文件传入的全局互斥锁与原始记账函数
        self.update_balance_func = original_update_balance_func
        self.lock = file_lock
        self._register_core_tools()

    def _register_core_tools(self):
        # 包装记账资产闭环工具
        self.tools["record_expense"] = {
            "description": "安全高效地将确认买入的商品开销记入 Jerry 的个人本地资产账本中，并同步修正卡内资金",
            "input_schema": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "扣减金额浮点数"},
                    "item_name": {"type": "string", "description": "买入商品名称"}
                },
                "required": ["amount", "item_name"]
            }
        }

    def handle_json_rpc(self, json_str: str) -> str:
        """标准网络/进程级 JSON-RPC 协议解析，完全符合 MCP 标准规范"""
        try:
            request = json.loads(json_str)
            method = request.get("method")
            req_id = request.get("id")

            if method == "tools/list":
                return json.dumps({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {"tools": [{"name": k, "description": v["description"], "input_schema": v["input_schema"]} for k, v in self.tools.items()]}
                })
                
            elif method == "tools/call":
                tool_name = request["params"]["name"]
                arguments = request["params"].get("arguments", {})
                
                if tool_name == "record_expense":
                    # 🔒 进入临界区，上锁！防止任何并发记账冲突
                    self.update_balance_func(arguments["amount"], arguments["item_name"])
                    return json.dumps({
                        "jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": f"[MCP Gateway 安全记账完毕] 商品: {arguments['item_name']}, 成功扣减: {arguments['amount']} 元"}]}
                    })
                else:
                    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "未找到指定工具"}})
        except Exception as e:
            return json.dumps({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}})
