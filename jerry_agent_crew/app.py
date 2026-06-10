from __future__ import annotations

import json
from dataclasses import asdict

import streamlit as st

from core.runtime import AgentCrewRuntime
from core.skills import list_skills
from core.templates import TASK_TEMPLATES


st.set_page_config(page_title="Jerry Agent Crew", page_icon="JAC", layout="wide")


def init_state() -> None:
    st.session_state.setdefault("runs", [])
    st.session_state.setdefault("selected_template", TASK_TEMPLATES[0].template_id)


def render_sidebar() -> None:
    st.sidebar.title("Jerry Agent Crew")
    st.sidebar.caption("个人任务多智能体工作台 MVP")
    st.sidebar.divider()
    st.sidebar.subheader("Agent Team")
    for name in ["ManagerAgent", "ResearchAgent", "AnalystAgent", "WriterAgent", "ReviewerAgent", "ExecutorAgent"]:
        st.sidebar.markdown(f"- `{name}`")
    st.sidebar.divider()
    st.sidebar.subheader("Skill Registry")
    for skill in list_skills():
        badge = "confirm" if skill.requires_confirmation else "auto"
        st.sidebar.markdown(f"- `{skill.name}` · {skill.risk_level} · {badge}")


def render_template_cards() -> str:
    st.subheader("任务模板")
    cols = st.columns(4)
    selected = st.session_state.selected_template
    for col, template in zip(cols, TASK_TEMPLATES):
        with col:
            st.markdown(f"**{template.name}**")
            st.caption(template.description)
            if st.button("选择", key=f"tpl_{template.template_id}", use_container_width=True):
                selected = template.template_id
                st.session_state.selected_template = template.template_id
    return selected


def selected_template():
    for template in TASK_TEMPLATES:
        if template.template_id == st.session_state.selected_template:
            return template
    return TASK_TEMPLATES[0]


def render_task_form(template) -> str:
    if template.template_id == "saving_decision":
        product = st.text_input("商品/消费问题", value="东方树叶")
        current_price = st.text_input("当前看到的价格", value="5 元")
        context = st.text_input("场景", value="线下便利店，想判断现在买值不值")
        return f"商品：{product}\n当前价格：{current_price}\n场景：{context}\n任务：判断是否值得购买，并说明是否需要记账确认。"

    if template.template_id == "procurement_research":
        item = st.text_input("要采购的东西", value="适合写代码的显示器")
        budget = st.text_input("预算", value="1000 元以内")
        requirements = st.text_area("硬性需求", value="护眼、27 寸左右、适合长时间写代码、售后稳定", height=90)
        avoid = st.text_input("避雷点", value="不要只看最低价，要关注售后和真实评价")
        return f"采购目标：{item}\n预算：{budget}\n硬性需求：{requirements}\n避雷点：{avoid}\n任务：生成候选对比、观察清单和购买建议。"

    if template.template_id == "interview_prep":
        role = st.text_input("目标岗位", value="Agent / AI Native 应用开发岗位")
        focus = st.multiselect(
            "重点话题",
            ["MCP", "多 Agent", "Dify / Coze / OpenClaw", "Skill Registry", "Trace / Eval", "省钱智探项目包装"],
            default=["MCP", "多 Agent", "Dify / Coze / OpenClaw", "Trace / Eval"],
        )
        weak = st.text_area("你担心被问倒的地方", value="多 Agent 是否牵强，MCP 和普通工具有什么区别，项目为什么不只是聊天框。", height=90)
        return f"目标岗位：{role}\n重点话题：{', '.join(focus)}\n担心点：{weak}\n任务：生成面试准备包、模拟追问清单和项目讲法卡片。"

    if template.template_id == "learning_digest":
        topics = st.text_input("学习主题", value="Linux 网络 + C++ 面试基础")
        days = st.number_input("计划天数", min_value=1, max_value=30, value=7)
        daily_minutes = st.number_input("每天可学习分钟数", min_value=15, max_value=480, value=90, step=15)
        output = st.text_input("希望输出", value="复习大纲、每日计划、复习卡片")
        return f"学习主题：{topics}\n计划天数：{days}\n每天时间：{daily_minutes} 分钟\n希望输出：{output}\n任务：读取本地笔记并生成复习计划和卡片。"

    return st.text_area("任务目标", value=template.example_goal, height=110)


def render_run(task_dict: dict) -> None:
    st.markdown(f"### {task_dict['title']}")
    st.caption(f"Run ID: `{task_dict['run_id']}` · Status: `{task_dict['status']}` · Created: {task_dict['created_at']}")
    if task_dict.get("warnings"):
        for warning in task_dict["warnings"]:
            st.warning(warning)

    final_tab, trace_tab, artifact_tab, raw_tab = st.tabs(["最终结果", "Agent Trace", "产物", "Raw JSON"])
    with final_tab:
        st.markdown(task_dict.get("final_answer") or "暂无结果")
    with trace_tab:
        for idx, step in enumerate(task_dict.get("steps", []), start=1):
            with st.expander(f"{idx}. {step['agent']} · {step['action']} · {step['status']} · {step.get('latency_ms', 0)}ms", expanded=True):
                st.write(step["summary"])
                if step.get("detail"):
                    st.json(step["detail"])
    with artifact_tab:
        for artifact in task_dict.get("artifacts", []):
            st.markdown(f"#### {artifact['title']}")
            st.caption(artifact["kind"])
            if artifact.get("metadata", {}).get("path"):
                st.code(artifact["metadata"]["path"], language="text")
            st.markdown(artifact["content"])
    with raw_tab:
        st.json(task_dict)


def main() -> None:
    init_state()
    render_sidebar()

    st.title("Jerry Agent Crew")
    st.caption("不是聊天框套工具，而是任务模板 + 多 Agent 分工 + Skill Registry + Trace 的个人任务工作台。")

    selected = render_template_cards()
    template = selected_template()

    st.divider()
    left, right = st.columns([1.15, 0.85])
    with left:
        st.subheader("创建任务")
        st.markdown(f"当前模板：**{template.name}**")
        goal = render_task_form(template)
        if st.button("运行 Agent Crew", type="primary", use_container_width=True):
            runtime = AgentCrewRuntime()
            task = runtime.run(selected, goal)
            st.session_state.runs.insert(0, asdict(task))
            st.success("Agent Crew 已完成本次任务。")
    with right:
        st.subheader("这个模板会产出")
        st.info(template.output_hint)
        st.markdown("**执行模式**")
        st.code(
            "ManagerAgent -> ResearchAgent -> AnalystAgent -> WriterAgent -> ReviewerAgent -> ExecutorAgent",
            language="text",
        )
        st.markdown("**省钱模块说明**")
        st.caption("价格情报使用 Search API 候选来源，不再把硬爬虫作为主路径。未配置 TAVILY_API_KEY 时会走安全降级。")

    st.divider()
    st.subheader("最近运行")
    if not st.session_state.runs:
        st.empty().info("还没有任务运行。选择模板后点击运行。")
    for run in st.session_state.runs[:8]:
        render_run(run)
        st.divider()


if __name__ == "__main__":
    main()
