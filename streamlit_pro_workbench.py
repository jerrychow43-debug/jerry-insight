from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


def _load_fullstack_deal_tools():
    """Reuse the Vue/FastAPI backend deal-research pipeline in Streamlit."""
    backend_dir = Path(__file__).resolve().parent / "fullstack_agent" / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from db import init_db, list_blocked_items, list_history, list_ledger
    from deal_research_service import run_deal_research

    init_db()
    return run_deal_research, list_ledger, list_blocked_items, list_history


def _money(value: Any) -> str:
    try:
        if value is None:
            return "未识别"
        return f"{float(value):.2f} 元"
    except Exception:
        return "未识别"


def _safe_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _build_source_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = run.get("legacy_audit", {}) or {}
    rows: list[dict[str, Any]] = []
    for item in legacy.get("price_table", []) or []:
        rows.append({
            "类型": "平台价格来源",
            "价格": item.get("price_text") or "摘要未暴露",
            "说明": item.get("info") or item.get("title") or "",
            "域名/平台": item.get("domain") or item.get("platform") or "",
            "链接": item.get("url") or "",
        })
    for item in legacy.get("crawler_sources", []) or []:
        rows.append({
            "类型": "搜索补充来源",
            "价格": item.get("price_text") or "摘要未暴露",
            "说明": item.get("info") or "",
            "域名/平台": item.get("platform") or "",
            "链接": item.get("url") or "",
        })
    for item in legacy.get("search_sources", []) or []:
        rows.append({
            "类型": "Tavily 搜索来源",
            "价格": "",
            "说明": item.get("summary") or "",
            "域名/平台": "",
            "链接": item.get("url") or "",
        })
    return rows


def _prepare_legacy_audit(run: dict[str, Any]) -> dict[str, Any]:
    decision = run.get("decision", {}) or {}
    legacy = run.get("legacy_audit", {}) or {}
    context = run.get("personal_context", {}) or {}
    audit_data = {
        "price": float(decision.get("estimated_price") or legacy.get("estimated_price") or 0),
        "item": run.get("product") or "未识别商品",
        "display_answer": legacy.get("display_answer") or run.get("report") or "",
        "info_blocks": [],
        "price_table_data": legacy.get("price_table") or [],
        "crawler_results": legacy.get("crawler_sources") or [],
        "long_term_context": "\n".join(str(row.get("text", "")) for row in (context.get("memory_hits") or [])),
        "trace": {"status": run.get("status", "completed"), "stages": run.get("steps", [])},
    }
    st.session_state["LAST_AUDIT"] = audit_data
    st.session_state["active_query"] = run.get("query") or audit_data["item"]
    return audit_data


def _inject_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.1rem; max-width: 1380px;}
        h1 {font-size: 2.25rem !important; margin-bottom: .35rem !important;}
        h2, h3 {letter-spacing: 0 !important;}
        div[data-testid="stTabs"] [data-baseweb="tab-list"] {gap: 20px; margin-bottom: 14px;}
        div[data-testid="stTabs"] [data-baseweb="tab"] {height: 42px; padding: 0 4px;}
        .pro-hero {
            border: 1px solid #dbe5f1; border-radius: 8px; padding: 18px 20px;
            background: #fff; min-height: 178px;
        }
        .pro-eyebrow {font-size: 13px; font-weight: 700; color: #51627a; margin-bottom: 8px;}
        .pro-title {font-size: 25px; font-weight: 800; color: #0b1f3a; margin-bottom: 8px; line-height: 1.25;}
        .pro-muted {color: #52657f; line-height: 1.65; font-size: 15px;}
        .decision-box {border-radius: 8px; padding: 20px; background: #0f7f72; color: white; min-height: 226px;}
        .decision-box small {font-weight: 700; color: #d9fff8;}
        .decision-box strong {display: block; font-size: 38px; line-height: 1.1; margin: 8px 0 12px;}
        .metric-card {border: 1px solid #dbe5f1; border-radius: 8px; padding: 16px; background: #f8fbff; min-height: 86px;}
        .metric-card small {color: #52657f; font-weight: 700;}
        .metric-card strong {display: block; margin-top: 8px; font-size: 23px;}
        .pro-card {border: 1px solid #dbe5f1; border-radius: 8px; padding: 18px; background: #fff; margin-bottom: 16px;}
        .agent-chip {display: inline-block; padding: 5px 9px; margin: 4px 4px 0 0; border-radius: 999px; background: #e8f3f1; color: #0f7f72; font-size: 12px;}
        .section-note {color: #6b7280; font-size: 14px; margin-top: -6px; margin-bottom: 12px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header(profile: dict[str, Any]) -> None:
    title_col, status_col = st.columns([1, 1])
    with title_col:
        st.caption("Jerry Insight Pro")
        st.title("工程化 Agent 工作台")
    with status_col:
        st.markdown(
            f"<div style='text-align:right; padding-top:18px; color:#52657f;'>当前余额 <b>{_money(profile.get('current_surplus'))}</b></div>",
            unsafe_allow_html=True,
        )


def _render_top_query(run_deal_research) -> None:
    left, right = st.columns([1.42, 1], gap="large")
    with left:
        st.markdown(
            """
            <div class="pro-hero">
              <div class="pro-eyebrow">Data Agent + Search Agent + MCP-style 工具编排</div>
              <div class="pro-title">把旧省钱智探升级成消费决策工程应用</div>
              <div class="pro-muted">
                复用原 Streamlit 版的搜索、价格来源、账本、记忆和确认购买闭环，
                把一次聊天式回答整理成证据、决策、链路和可执行动作。
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        with st.form("pro_deal_form", clear_on_submit=False):
            query = st.text_area(
                "购买意图",
                value=st.session_state.get(
                    "PRO_QUERY",
                    "我想买一个 1000 元以内适合写代码的显示器，帮我研究值不值得买",
                ),
                height=104,
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("生成购买研究报告", type="primary", use_container_width=True)

    if submitted and query.strip():
        st.session_state["PRO_QUERY"] = query.strip()
        with st.spinner("正在复用旧版省钱智探链路，并整理成工程化报告..."):
            try:
                st.session_state["PRO_DEAL_RUN"] = run_deal_research(query.strip())
                st.session_state["ACTION_COMPLETED"] = False
                st.toast("研究报告已生成", icon="OK")
            except Exception as err:
                st.error(f"运行失败：{err}")


def _render_decision_summary(run: dict[str, Any], profile: dict[str, Any], callback_confirm, callback_cancel) -> None:
    decision = run.get("decision", {}) or {}
    legacy = run.get("legacy_audit", {}) or {}
    context = run.get("personal_context", {}) or {}

    col_decision, col_metrics = st.columns([1, 1.42], gap="large")
    with col_decision:
        st.markdown(
            f"""
            <div class="decision-box">
              <small>最终建议</small>
              <strong>{decision.get("verdict", "待判断")}</strong>
              <p>{decision.get("reason", "")}</p>
              <p>
                <span class="agent-chip">可信度：{decision.get("confidence", "-")}</span>
                <span class="agent-chip">预算：{_money(decision.get("budget"))}</span>
                <span class="agent-chip">估算价：{_money(decision.get("estimated_price"))}</span>
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        act1, act2 = st.columns(2)
        disabled = st.session_state.get("ACTION_COMPLETED", False)
        if act1.button("确认购买并记账", type="primary", use_container_width=True, disabled=disabled):
            _prepare_legacy_audit(run)
            callback_confirm()
        if act2.button("放弃购买", use_container_width=True, disabled=disabled):
            _prepare_legacy_audit(run)
            callback_cancel()

    with col_metrics:
        m1, m2 = st.columns(2)
        m1.markdown(f'<div class="metric-card"><small>Tavily 来源</small><strong>{_safe_len(legacy.get("search_sources"))} 条</strong></div>', unsafe_allow_html=True)
        m2.markdown(f'<div class="metric-card"><small>平台价格来源</small><strong>{_safe_len(legacy.get("price_table"))} 条</strong></div>', unsafe_allow_html=True)
        m3, m4 = st.columns(2)
        m3.markdown(f'<div class="metric-card"><small>搜索补充来源</small><strong>{_safe_len(legacy.get("crawler_sources"))} 条</strong></div>', unsafe_allow_html=True)
        m4.markdown(f'<div class="metric-card"><small>当前余额</small><strong>{_money(context.get("current_surplus", profile.get("current_surplus")))}</strong></div>', unsafe_allow_html=True)


def _render_planner_and_agents(run: dict[str, Any]) -> None:
    plan_col, agent_col = st.columns([1, 1], gap="large")
    with plan_col:
        st.markdown('<div class="pro-card">', unsafe_allow_html=True)
        st.subheader("Planner 拆解")
        st.markdown('<div class="section-note">把购买问题拆成价格、风险、替代品、个人预算四类。</div>', unsafe_allow_html=True)
        plan_rows = [
            {"角色": q.get("owner", ""), "问题": q.get("question", ""), "目的": q.get("purpose", "")}
            for q in (run.get("questions", []) or [])
        ]
        if plan_rows:
            st.dataframe(pd.DataFrame(plan_rows), hide_index=True, use_container_width=True, height=220)
        st.markdown("</div>", unsafe_allow_html=True)

    with agent_col:
        st.markdown('<div class="pro-card">', unsafe_allow_html=True)
        st.subheader("多 Agent 编排")
        st.markdown('<div class="section-note">展示每个 Agent 的职责、状态和最终产出。</div>', unsafe_allow_html=True)
        agent_rows = []
        for agent in run.get("agent_runs", []) or []:
            tools = ", ".join(call.get("tool", "") for call in (agent.get("tool_calls") or []))
            agent_rows.append({
                "Agent": agent.get("agent", ""),
                "状态": agent.get("status", ""),
                "产出": agent.get("summary", ""),
                "工具": tools or "-",
            })
        if agent_rows:
            st.dataframe(pd.DataFrame(agent_rows), hide_index=True, use_container_width=True, height=220)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_evidence(run: dict[str, Any]) -> None:
    st.markdown('<div class="pro-card">', unsafe_allow_html=True)
    st.subheader("证据卡片")
    evidence = run.get("evidence", []) or []
    if evidence:
        e_cols = st.columns(3)
        for idx, item in enumerate(evidence[:6]):
            with e_cols[idx % 3]:
                st.caption(f"{item.get('category', '')} | {item.get('confidence', '')}")
                st.markdown(f"**{item.get('title', '')}**")
                if item.get("price_text"):
                    st.success(item.get("price_text"))
                summary = item.get("summary", "")
                st.write(summary[:170] + ("..." if len(summary) > 170 else ""))
                if item.get("url"):
                    st.link_button("打开来源", item.get("url"), use_container_width=True)
                else:
                    st.caption(item.get("source", ""))
        if len(evidence) > 6:
            st.caption(f"其余 {len(evidence) - 6} 条已收进下面的来源表，避免页面过长。")
    else:
        st.caption("暂无证据卡片。")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_sources_and_history(run: dict[str, Any], list_ledger, list_blocked_items, list_history) -> None:
    source_col, history_col = st.columns([1.35, 1], gap="large")
    with source_col:
        st.markdown('<div class="pro-card">', unsafe_allow_html=True)
        st.subheader("价格与来源")
        source_rows = _build_source_rows(run)
        if source_rows:
            st.dataframe(pd.DataFrame(source_rows), hide_index=True, use_container_width=True, height=300)
        else:
            st.caption("暂无价格来源。")
        st.markdown("</div>", unsafe_allow_html=True)

    with history_col:
        context = run.get("personal_context", {}) or {}
        st.markdown('<div class="pro-card">', unsafe_allow_html=True)
        st.subheader("账本与历史")
        inner_tabs = st.tabs(["账本", "放弃", "会话"])
        with inner_tabs[0]:
            for row in (context.get("recent_ledger") or list_ledger(6))[:6]:
                st.caption(f"{row.get('item')} | {_money(row.get('amount'))} | {row.get('status')} | {row.get('created_at', '')}")
        with inner_tabs[1]:
            for row in (context.get("blocked_items") or list_blocked_items(6))[:6]:
                st.caption(f"{row.get('item')} | {row.get('reason')} | {row.get('created_at', '')}")
        with inner_tabs[2]:
            for row in (context.get("history") or list_history(6))[:6]:
                st.caption(f"{row.get('intent', '')} | {row.get('user_message', '')}")
        st.markdown("</div>", unsafe_allow_html=True)


def render_streamlit_pro_workbench(callback_confirm, callback_cancel, get_dynamic_profile):
    run_deal_research, list_ledger, list_blocked_items, list_history = _load_fullstack_deal_tools()
    _inject_style()

    profile = get_dynamic_profile()
    _render_header(profile)

    tabs = st.tabs(["省钱智探 Pro", "ProjectOps 排障 Agent"])

    with tabs[0]:
        _render_top_query(run_deal_research)

        run = st.session_state.get("PRO_DEAL_RUN")
        if not run:
            st.info("先输入一个真实购买意图。这里会展示联网搜索、价格来源、个人账本上下文和购买动作。")
            return

        _render_decision_summary(run, profile, callback_confirm, callback_cancel)
        _render_planner_and_agents(run)
        _render_evidence(run)
        _render_sources_and_history(run, list_ledger, list_blocked_items, list_history)

        legacy = run.get("legacy_audit", {}) or {}
        with st.expander("省钱智探原始判断", expanded=False):
            st.markdown(legacy.get("display_answer") or "暂无原始判断。")
        with st.expander("完整 Markdown 报告", expanded=False):
            st.markdown(run.get("report") or "")

    with tabs[1]:
        st.info("ProjectOps 排障 Agent 已在 Vue + FastAPI 版本中实现。Streamlit 版当前先聚焦迁移省钱智探 Pro 展示闭环；如果要继续，可以继续把项目导入、ProjectMap、故障事件和排障报告也搬进来。")
