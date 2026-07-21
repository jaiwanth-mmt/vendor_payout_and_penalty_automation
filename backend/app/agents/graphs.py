"""Compile LangGraph case and portfolio graphs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.app.agents.llm import AgentLlmGenerator
from backend.app.agents.nodes.investigation import (
    evidence_agent_node,
    finalize_node,
    human_review_node,
    intake_node,
    judge_node,
    portfolio_summary_node,
    specialist_node,
    vendor_penalty_analysis_node,
)
from backend.app.agents.state import InvestigationState, PortfolioState

CASE_NODE_NAMES = [
    "intake",
    "evidence_agent",
    "specialist",
    "judge",
    "human_review",
    "finalize",
]
PORTFOLIO_NODE_NAMES = ["portfolio_summary", "vendor_penalty_analysis"]


def build_case_graph(
    *,
    llm_generator: AgentLlmGenerator | None = None,
    semaphore=None,
    checkpointer=None,
    enable_hitl: bool = True,
):
    """
    Per-booking investigation graph.

    intake → evidence_agent → specialist → judge → human_review → finalize
    """
    builder = StateGraph(InvestigationState)

    async def _evidence(state: InvestigationState) -> dict[str, Any]:
        return await evidence_agent_node(state, llm_generator=llm_generator, semaphore=semaphore)

    async def _specialist(state: InvestigationState) -> dict[str, Any]:
        return await specialist_node(state, llm_generator=llm_generator, semaphore=semaphore)

    async def _judge(state: InvestigationState) -> dict[str, Any]:
        return await judge_node(state, llm_generator=llm_generator, semaphore=semaphore)

    builder.add_node("intake", intake_node)
    builder.add_node("evidence_agent", _evidence)
    builder.add_node("specialist", _specialist)
    builder.add_node("judge", _judge)
    if enable_hitl:
        builder.add_node("human_review", human_review_node)
    else:

        def _skip_hitl(state: InvestigationState) -> dict[str, Any]:
            return {"pending_interrupt": False}

        builder.add_node("human_review", _skip_hitl)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "evidence_agent")
    builder.add_edge("evidence_agent", "specialist")
    builder.add_edge("specialist", "judge")
    builder.add_edge("judge", "human_review")
    if enable_hitl:
        # human_review uses Command(goto="finalize")
        pass
    else:
        builder.add_edge("human_review", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def build_portfolio_graph(
    *,
    llm_generator: AgentLlmGenerator | None = None,
    llm_concurrency: int = 1,
    checkpointer=None,
):
    builder = StateGraph(PortfolioState)

    async def _portfolio(state: PortfolioState) -> dict[str, Any]:
        return await portfolio_summary_node(
            state,
            llm_generator=llm_generator,
            llm_concurrency=llm_concurrency,
        )

    builder.add_node("portfolio_summary", _portfolio)
    builder.add_node("vendor_penalty_analysis", vendor_penalty_analysis_node)
    builder.add_edge(START, "portfolio_summary")
    builder.add_edge("portfolio_summary", "vendor_penalty_analysis")
    builder.add_edge("vendor_penalty_analysis", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def sanitize_mermaid(chart: str) -> str:
    """Strip HTML wrappers LangGraph embeds in node labels so browsers can render Mermaid."""
    cleaned = chart.replace("<p>", "").replace("</p>", "")
    cleaned = cleaned.replace("&lt;p&gt;", "").replace("&lt;/p&gt;", "")
    return cleaned.strip()


def case_graph_mermaid(graph=None) -> str:
    compiled = graph or build_case_graph(enable_hitl=True)
    return sanitize_mermaid(compiled.get_graph().draw_mermaid())


def portfolio_graph_mermaid(graph=None) -> str:
    compiled = graph or build_portfolio_graph()
    return sanitize_mermaid(compiled.get_graph().draw_mermaid())


def graph_topology_payload() -> dict[str, Any]:
    case_graph = build_case_graph(enable_hitl=True)
    portfolio_graph = build_portfolio_graph()
    return {
        "case": {
            "nodes": CASE_NODE_NAMES,
            "mermaid": sanitize_mermaid(case_graph.get_graph().draw_mermaid()),
        },
        "portfolio": {
            "nodes": PORTFOLIO_NODE_NAMES,
            "mermaid": sanitize_mermaid(portfolio_graph.get_graph().draw_mermaid()),
        },
    }


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


async def maybe_await_callback(callback: EventCallback | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(event)
    if hasattr(result, "__await__"):
        await result  # type: ignore[misc]
