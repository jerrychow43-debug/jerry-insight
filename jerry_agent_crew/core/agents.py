from __future__ import annotations

import time
from typing import Any, Dict, List

from .artifact_store import write_artifacts
from .models import AgentStep, Artifact, CrewTask, PriceCandidate
from .skills import read_local_knowledge, search_price_candidates, summarize_ledger


def _step(agent: str, action: str, summary: str, detail: Dict[str, Any] | None = None, start: float | None = None) -> AgentStep:
    latency = int((time.perf_counter() - start) * 1000) if start else 0
    return AgentStep(agent=agent, action=action, status="success", summary=summary, detail=detail or {}, latency_ms=latency)


class ManagerAgent:
    name = "ManagerAgent"

    def run(self, task: CrewTask) -> Dict[str, Any]:
        start = time.perf_counter()
        plans = {
            "saving_decision": ["分析用户消费意图", "查询旧账本/预算", "搜索公开候选价格", "生成消费建议", "检查是否需要记账确认"],
            "procurement_research": ["拆解采购需求", "搜索候选方案", "结合预算筛选", "生成对比报告", "审查来源可信度"],
            "interview_prep": ["识别面试主题", "读取项目/笔记", "补充 Agent 框架资料", "生成回答稿", "模拟追问和挑刺"],
            "learning_digest": ["识别学习主题", "读取本地学习笔记", "整理知识结构", "生成复习计划", "检查遗漏"],
        }
        plan = plans.get(task.template_id, ["理解任务", "收集资料", "生成产物", "审查结果"])
        task.steps.append(_step(self.name, "plan_task", "已把用户目标拆成 Agent 协作步骤。", {"plan": plan}, start))
        return {"plan": plan}


class ResearchAgent:
    name = "ResearchAgent"

    def run(self, task: CrewTask) -> Dict[str, Any]:
        start = time.perf_counter()
        if task.template_id in {"saving_decision", "procurement_research"}:
            candidates = search_price_candidates(task.goal)
            detail = {"price_candidates": [candidate.__dict__ for candidate in candidates]}
            task.steps.append(_step(self.name, "search_price_candidates", "已用搜索 API 路线收集候选价格，不使用硬爬虫。", detail, start))
            return {"price_candidates": candidates}

        notes = read_local_knowledge(task.goal)
        task.steps.append(_step(self.name, "collect_knowledge", "已读取本地项目/学习资料作为任务上下文。", {"notes": notes}, start))
        return {"notes": notes}


class AnalystAgent:
    name = "AnalystAgent"

    def run(self, task: CrewTask, research: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        if task.template_id in {"saving_decision", "procurement_research"}:
            ledger = summarize_ledger()
            task.steps.append(
                _step(
                    self.name,
                    "analyze_finance_context",
                    "已结合旧账本/余额形成消费上下文。",
                    {"ledger": ledger.__dict__},
                    start,
                )
            )
            return {"ledger": ledger}

        notes = research.get("notes", [])
        key_points = []
        for note in notes[:4]:
            key_points.append(f"{note['path']}: {note['snippet'][:120]}...")
        if not key_points:
            key_points = ["未找到强相关本地资料，建议先补充项目说明或学习笔记。"]
        task.steps.append(_step(self.name, "analyze_local_context", "已从本地资料中提取可用于写作的要点。", {"key_points": key_points}, start))
        return {"key_points": key_points}


class WriterAgent:
    name = "WriterAgent"

    def run(self, task: CrewTask, research: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        artifacts = self._compose_artifacts(task, research, analysis)
        task.artifacts.extend(artifacts)
        task.final_answer = artifacts[0].content if artifacts else ""
        task.steps.append(
            _step(
                self.name,
                "compose_artifacts",
                f"已生成 {len(artifacts)} 个任务产物，不再只是聊天回复。",
                {"artifact_titles": [artifact.title for artifact in artifacts]},
                start,
            )
        )
        return {"artifacts": artifacts}

    def _compose_artifacts(self, task: CrewTask, research: Dict[str, Any], analysis: Dict[str, Any]) -> List[Artifact]:
        if task.template_id == "saving_decision":
            return [
                Artifact(title="省钱决策报告", kind="markdown", content=self._saving_report(task, research, analysis)),
                Artifact(title="候选价格看板", kind="markdown", content=self._price_board(task, research)),
            ]
        if task.template_id == "procurement_research":
            return [
                Artifact(title="采购调研报告", kind="markdown", content=self._procurement_report(task, research, analysis)),
                Artifact(title="候选商品对比表", kind="markdown", content=self._procurement_table(task, research)),
                Artifact(title="观察清单草稿", kind="json", content=self._watchlist_json(task, research)),
            ]
        if task.template_id == "interview_prep":
            return [
                Artifact(title="Agent 岗面试准备包", kind="markdown", content=self._interview_report(task, analysis)),
                Artifact(title="模拟追问清单", kind="markdown", content=self._mock_questions(task)),
                Artifact(title="项目讲法卡片", kind="markdown", content=self._project_pitch_card(task)),
            ]
        if task.template_id == "learning_digest":
            return [
                Artifact(title="学习复习计划", kind="markdown", content=self._learning_report(task, analysis)),
                Artifact(title="复习卡片", kind="csv", content=self._flashcards_csv(task, analysis)),
            ]
        return [Artifact(title=f"{task.title} - Agent 输出", kind="markdown", content=f"# {task.title}\n\n目标：{task.goal}")]

    def _compose(self, task: CrewTask, research: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        if task.template_id == "saving_decision":
            return self._saving_report(task, research, analysis)
        if task.template_id == "procurement_research":
            return self._procurement_report(task, research, analysis)
        if task.template_id == "interview_prep":
            return self._interview_report(task, analysis)
        if task.template_id == "learning_digest":
            return self._learning_report(task, analysis)
        return f"# {task.title}\n\n目标：{task.goal}\n\n当前 MVP 已生成基础结果。"

    def _price_lines(self, candidates: List[PriceCandidate]) -> str:
        lines = []
        for idx, candidate in enumerate(candidates[:5], start=1):
            source = f" 来源：{candidate.source_url}" if candidate.source_url else ""
            lines.append(f"{idx}. {candidate.source_title}：{candidate.price_text}，可信度 {candidate.confidence}。{source}")
        return "\n".join(lines) if lines else "暂无候选价格。"

    def _price_board(self, task: CrewTask, research: Dict[str, Any]) -> str:
        candidates = research.get("price_candidates", [])
        rows = ["| 来源 | 候选价格 | 可信度 | 链接 |", "| --- | --- | --- | --- |"]
        for candidate in candidates[:8]:
            link = candidate.source_url or "无"
            rows.append(f"| {candidate.source_title} | {candidate.price_text} | {candidate.confidence} | {link} |")
        return f"# 候选价格看板\n\n目标：{task.goal}\n\n" + "\n".join(rows)

    def _saving_report(self, task: CrewTask, research: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        candidates = research.get("price_candidates", [])
        ledger = analysis.get("ledger")
        ledger_note = ledger.note if ledger else "暂无账本摘要。"
        surplus = f"{ledger.current_surplus} 元" if ledger and ledger.current_surplus is not None else "未知"
        recent = "、".join(ledger.recent_items) if ledger and ledger.recent_items else "暂无"
        return f"""# 省钱决策结果

**目标**：{task.goal}

## 候选价格
{self._price_lines(candidates)}

## 个人消费上下文
- 当前剩余预算：{surplus}
- 最近消费：{recent}
- 账本状态：{ledger_note}

## 建议
这次不再承诺“全网最低价”。系统只把公开搜索结果作为候选价格，再结合你的历史消费和预算做判断。

如果候选价格可信度低，建议先点击来源人工确认；如果你已经明确买了并给出金额，可以进入记账确认流程。
"""

    def _procurement_report(self, task: CrewTask, research: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        candidates = research.get("price_candidates", [])
        ledger = analysis.get("ledger")
        budget_line = f"当前剩余预算约 {ledger.current_surplus} 元。" if ledger and ledger.current_surplus is not None else "当前预算未知。"
        return f"""# 采购调研报告

**采购目标**：{task.goal}

## 初步需求拆解
- 明确预算上限和刚需功能。
- 优先选择可验证来源，不采用无法确认的低价信息。
- 将候选商品加入观察清单后再决定是否购买。

## 候选来源
{self._price_lines(candidates)}

## 预算上下文
{budget_line}

## 下一步
建议补充具体偏好，例如品牌、尺寸、是否接受二手、是否需要立即购买。随后可生成更细的候选对比表。
"""

    def _procurement_table(self, task: CrewTask, research: Dict[str, Any]) -> str:
        candidates = research.get("price_candidates", [])
        rows = ["| 候选 | 价格信息 | 来源可信度 | 用途判断 |", "| --- | --- | --- | --- |"]
        for idx, candidate in enumerate(candidates[:5], start=1):
            rows.append(f"| 方案 {idx}: {candidate.source_title} | {candidate.price_text} | {candidate.confidence} | 需要人工打开来源核实参数和售后 |")
        if not candidates:
            rows.append("| 暂无 | 暂无 | low | 需要补充搜索 API 或手动候选 |")
        return f"# 候选商品对比表\n\n采购目标：{task.goal}\n\n" + "\n".join(rows)

    def _watchlist_json(self, task: CrewTask, research: Dict[str, Any]) -> str:
        candidates = research.get("price_candidates", [])
        items = []
        for candidate in candidates[:5]:
            items.append(
                {
                    "goal": task.goal,
                    "source_title": candidate.source_title,
                    "source_url": candidate.source_url,
                    "price_text": candidate.price_text,
                    "confidence": candidate.confidence,
                    "next_action": "人工核实参数/价格后决定是否加入正式观察清单",
                }
            )
        return __import__("json").dumps({"watchlist": items}, ensure_ascii=False, indent=2)

    def _interview_report(self, task: CrewTask, analysis: Dict[str, Any]) -> str:
        key_points = "\n".join(f"- {point}" for point in analysis.get("key_points", []))
        return f"""# 面试准备草稿

**目标**：{task.goal}

## 可用项目素材
{key_points}

## 建议讲法
你可以把项目讲成一个轻量级 Agent Runtime，而不是普通聊天机器人：它有任务模板、Skill Registry、MCP 工具服务、Trace 和 Eval。

## 可能追问
1. 为什么这些能力不是普通函数？
2. MCP 和 Skill 的区别是什么？
3. 如何避免 Agent 误操作？
4. 如何评测 Agent 是否真的有效？

## 回答方向
强调你没有硬套概念，而是把工具执行、状态管理、可观测性和测试体系工程化。
"""

    def _mock_questions(self, task: CrewTask) -> str:
        return f"""# 模拟追问清单

目标：{task.goal}

1. 你这个项目和普通聊天机器人有什么区别？
2. 为什么要做 Skill Registry，而不是直接写函数？
3. MCP 在你的项目里解决了什么问题？
4. 如果面试官质疑多 Agent 牵强，你怎么回答？
5. Agent 调错工具怎么办？
6. 如何证明你的 Agent 不是靠感觉能跑？
7. 你的 Trace 记录了哪些字段？
8. 为什么省钱模块不继续硬爬电商平台？
"""

    def _project_pitch_card(self, task: CrewTask) -> str:
        return f"""# 项目讲法卡片

**一句话**：我做的是一个个人任务多智能体工作台，不是简单聊天框。

**核心结构**：

```text
任务模板 -> ManagerAgent 拆任务 -> Research/Analyst/Writer/Reviewer/Executor 协作
          -> Skill Registry / MCP 工具 -> Trace -> Artifact
```

**重点亮点**：
- 多 Agent 是围绕任务产物分工，不是把小函数包装成 Agent。
- Skills 负责具体动作，Agent 负责规划、分析、写作、审查和执行决策。
- 省钱模块保留生活场景，但价格来源改为 Search API 候选结果，避免硬爬虫风险。
"""

    def _learning_report(self, task: CrewTask, analysis: Dict[str, Any]) -> str:
        key_points = "\n".join(f"- {point}" for point in analysis.get("key_points", []))
        return f"""# 学习资料整理

**目标**：{task.goal}

## 已读取资料
{key_points}

## 7 天计划
1. 第 1 天：整理概念地图，标出不会的术语。
2. 第 2 天：复习核心原理，补齐基础。
3. 第 3 天：整理高频问答。
4. 第 4 天：做一轮口述练习。
5. 第 5 天：查漏补缺。
6. 第 6 天：模拟面试。
7. 第 7 天：压缩成一页速记稿。

## 输出建议
把最终内容导出为 Markdown/PDF，并把薄弱点放进下一轮任务。
"""

    def _flashcards_csv(self, task: CrewTask, analysis: Dict[str, Any]) -> str:
        rows = ['question,answer,source']
        for idx, point in enumerate(analysis.get("key_points", [])[:8], start=1):
            clean = point.replace('"', "'").replace("\n", " ")
            rows.append(f'"复习点 {idx}","{clean}","local_notes"')
        if len(rows) == 1:
            rows.append('"如何使用这个学习模板？","补充本地笔记后重新运行，系统会从文件中提取复习点。","system"')
        return "\n".join(rows)


class ReviewerAgent:
    name = "ReviewerAgent"

    def run(self, task: CrewTask, research: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        warnings: List[str] = []
        if task.template_id in {"saving_decision", "procurement_research"}:
            candidates: List[PriceCandidate] = research.get("price_candidates", [])
            if not candidates or all(candidate.confidence == "low" for candidate in candidates):
                warnings.append("候选价格可信度偏低，需要用户点击来源或手动输入价格确认。")
            if any(word in task.goal for word in ["买了", "花了", "扣", "记账"]):
                task.needs_approval = True
                warnings.append("检测到可能涉及账本写入，MVP 只创建确认项，不自动扣款。")
        if task.template_id in {"interview_prep", "learning_digest"} and "资料" not in task.final_answer:
            warnings.append("本地资料不足，建议补充笔记或 README 后再生成正式材料。")
        task.warnings.extend(warnings)
        summary = "已完成审查。" if not warnings else "已完成审查，并发现需要注意的风险。"
        task.steps.append(_step(self.name, "review_output", summary, {"warnings": warnings, "needs_approval": task.needs_approval}, start))
        return {"warnings": warnings}


class ExecutorAgent:
    name = "ExecutorAgent"

    def run(self, task: CrewTask) -> Dict[str, Any]:
        start = time.perf_counter()
        action = "prepare_artifact"
        summary = "已准备最终产物，可在页面中查看。"
        detail: Dict[str, Any] = {"artifact_count": len(task.artifacts)}
        artifact_paths = write_artifacts(task)
        detail["artifact_paths"] = artifact_paths
        if task.needs_approval:
            action = "prepare_approval"
            summary = "已创建待确认动作，当前 MVP 不自动写账本或发送外部通知。"
            detail["approval_required"] = True
        task.status = "needs_approval" if task.needs_approval else "completed"
        task.steps.append(_step(self.name, action, summary, detail, start))
        return detail
