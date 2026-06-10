from __future__ import annotations

from .models import TaskTemplate


TASK_TEMPLATES = [
    TaskTemplate(
        template_id="saving_decision",
        name="省钱计划 / 消费决策",
        description="继承省钱智探 Agent：问价、预算判断、历史价格、记账建议。",
        example_goal="我想买东方树叶，5 元能买吗？",
        output_hint="购买建议、候选价格、历史消费参考、是否需要记账确认。",
    ),
    TaskTemplate(
        template_id="procurement_research",
        name="采购调研",
        description="把一次购买变成调研任务：需求拆解、候选对比、价格来源、推荐排序。",
        example_goal="帮我选一个 1000 元以内适合写代码的显示器。",
        output_hint="采购对比报告、候选清单、推荐理由、观察清单建议。",
    ),
    TaskTemplate(
        template_id="interview_prep",
        name="面试准备",
        description="读取项目和笔记，整理 Agent 岗面试回答、追问和薄弱点。",
        example_goal="帮我准备 Agent 岗面试，重点讲 MCP、多 Agent、Dify、OpenClaw。",
        output_hint="面试话术、项目包装、模拟追问、复习材料。",
    ),
    TaskTemplate(
        template_id="learning_digest",
        name="学习资料整理",
        description="读取本地学习笔记，整理复习大纲、学习计划和关键概念。",
        example_goal="帮我整理 Linux 网络和 C++ 面试知识，生成 7 天复习计划。",
        output_hint="复习大纲、每日计划、薄弱点、输出文档建议。",
    ),
]


def get_template(template_id: str) -> TaskTemplate:
    for template in TASK_TEMPLATES:
        if template.template_id == template_id:
            return template
    raise KeyError(f"Unknown template_id: {template_id}")

