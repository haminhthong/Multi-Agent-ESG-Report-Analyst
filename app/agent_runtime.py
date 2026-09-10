"""Runtime nhỏ và có giới hạn cho các handoff của workflow.

Runtime chỉ phụ trách định tuyến. Nghiệp vụ vẫn nằm trong capability và
service để graph dễ quan sát, dễ kiểm thử và chạy được khi không có LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.models import AnalysisState

AgentHandler = Callable[[], None]
NextAgent = Callable[[AnalysisState], str | None]


@dataclass(frozen=True)
class AgentNode:
    """Một handoff có state trong graph workflow."""

    name: str
    run: AgentHandler
    next_agent: NextAgent


@dataclass(frozen=True)
class AgentRouteResult:
    """Observable result of one bounded graph execution."""

    route: list[str]
    stop_reason: str


class AgentGraphSupervisor:
    """Chạy graph workflow với giới hạn bước cứng.

    Node có thể chọn node tiếp theo từ ``AnalysisState``. Quality gate vì vậy
    có thể dừng, bỏ qua hoặc chuyển hướng mà mọi handoff vẫn xuất hiện trong trace.
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
