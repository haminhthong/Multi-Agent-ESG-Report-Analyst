"""Small, bounded runtime for explicit multi-agent handoffs.

The runtime deliberately owns routing only. Domain work stays in the existing
agents and services, which keeps the graph observable, testable, and safe to
run without an LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.models import AnalysisState

AgentHandler = Callable[[], None]
NextAgent = Callable[[AnalysisState], str | None]


@dataclass(frozen=True)
class AgentNode:
    """A single stateful handoff in the supervisor graph."""

    name: str
    run: AgentHandler
    next_agent: NextAgent


@dataclass(frozen=True)
class AgentRouteResult:
    """Observable result of one bounded graph execution."""

    route: list[str]
    stop_reason: str


class AgentGraphSupervisor:
    """Execute an explicit agent graph with a hard step limit.

    A node can choose the next node from the shared ``AnalysisState``. This is
    the key difference from a fixed service pipeline: a quality gate can stop,
    skip, or redirect work while every handoff remains visible in the trace.
    """

    def __init__(self, max_steps: int = 16) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.max_steps = max_steps

    def execute(
        self,
        state: AnalysisState,
        nodes: Mapping[str, AgentNode],
        start: str,
    ) -> AgentRouteResult:
        if start not in nodes:
            raise ValueError(f"Unknown start agent: {start}")

        route: list[str] = []
        visited: set[str] = set()
        current = start
        stop_reason = "completed"

        while current is not None:
            if len(route) >= self.max_steps:
                stop_reason = "max_steps_reached"
                state.warnings.append(f"Supervisor stopped after {self.max_steps} agent steps.")
                state.trace.append(f"Supervisor: stop reason={stop_reason}")
                break
            if current in visited:
                stop_reason = "cycle_detected"
                state.warnings.append(f"Supervisor detected an agent cycle at {current}.")
                state.trace.append(f"Supervisor: stop reason={stop_reason} agent={current}")
                break

            node = nodes.get(current)
            if node is None:
                raise ValueError(f"Unknown next agent: {current}")

            route.append(node.name)
            visited.add(current)
            state.trace.append(f"Supervisor: dispatch agent={node.name}")
            node.run()
            next_agent = node.next_agent(state)
            state.trace.append(f"Supervisor: handoff {node.name} -> {next_agent or 'END'}")
            current = next_agent

        state.agent_route = route
        return AgentRouteResult(route=route, stop_reason=stop_reason)
