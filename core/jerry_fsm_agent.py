# Jerry-Insight-Pro/core/jerry_fsm_agent.py
class JerryFSMAgent:
    def __init__(self):
        # 定义系统的所有合法状态
        self.STATES = ["INIT", "INTENT_CHECK", "PRICE_SCOUT", "AUDIT_REPORT", "MCP_RECORD", "END"]
        self.current_state = "INIT"
        print(f"🤖 [FSM 状态机启动] 当前初始状态: {self.current_state}")

    def transition_to(self, next_state):
        if next_state in self.STATES:
            print(f"🔄 [FSM 状态流转] {self.current_state} ➡️ {next_state}")
            self.current_state = next_state
        else:
            raise ValueError(f"🚨 非法状态定义: {next_state}")

    def run_workflow(self, raw_input, router_func, search_func, brain_func, mcp_func):
        """核心调度骨架：严格控制 Agent 的每一步执行生命周期"""
        
        # 1. 意图拦截阶段
        self.transition_to("INTENT_CHECK")
        intent = router_func(raw_input)
        if intent == "INVALID":
            self.transition_to("END")
            return "🚨 触发安全红线拦截，熔断后续所有状态流转！"

        # 2. 实时比价阶段
        self.transition_to("PRICE_SCOUT")
        price_info = search_func(raw_input)

        # 3. 大模型深度审计阶段
        self.transition_to("AUDIT_REPORT")
        final_report, should_buy, cost = brain_func(raw_input, price_info)

        # 4. 资产闭环记账阶段
        if should_buy:
            self.transition_to("MCP_RECORD")
            mcp_func(cost, raw_input)
        else:
            print("🛑 [FSM 通知] 审计未通过，跳过记账，直接进入终态。")

        self.transition_to("END")
        return final_report