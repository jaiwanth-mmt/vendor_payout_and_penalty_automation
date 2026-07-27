"""Compile the deterministic vendor penalty mailer graph."""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.app.agents.mailer.nodes import assign_node, compose_node, finalize_node, send_node, validate_node
from backend.app.agents.mailer.state import MailerState
from backend.app.integrations.smtp import MailTransport

MAILER_NODE_NAMES = ["assign", "compose", "validate", "send", "finalize"]


def build_mailer_graph(*, transport: MailTransport | None = None, checkpointer=None):
    """
    Job-level mailer graph.

    assign → compose → validate → send → finalize
    """
    builder = StateGraph(MailerState)
    builder.add_node("assign", assign_node)
    builder.add_node("compose", compose_node)
    builder.add_node("validate", validate_node)
    builder.add_node("send", partial(send_node, transport=transport))
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "assign")
    builder.add_edge("assign", "compose")
    builder.add_edge("compose", "validate")
    builder.add_edge("validate", "send")
    builder.add_edge("send", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def mailer_graph_mermaid(graph=None) -> str:
    compiled = graph or build_mailer_graph()
    chart = compiled.get_graph().draw_mermaid()
    return chart.replace("<p>", "").replace("</p>", "").strip()


def mailer_topology_payload() -> dict[str, Any]:
    graph = build_mailer_graph()
    return {
        "nodes": MAILER_NODE_NAMES,
        "mermaid": mailer_graph_mermaid(graph),
    }
