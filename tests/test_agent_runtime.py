from app.agent_runtime import AgentGraphSupervisor, AgentNode
from app.models import AnalysisState


def _state() -> AnalysisState:
    return AnalysisState(request_id="test", user_question="question")


def test_supervisor_stops_cycles_by_graph_key():
    state = _state()
    node = AgentNode(
        name="PlannerAgent",
        run=lambda: None,
        next_agent=lambda _: "planner",
    )

    result = AgentGraphSupervisor(max_steps=3).execute(
        state,
        {"planner": node},
        start="planner",
    )

    assert result.stop_reason == "cycle_detected"
    assert result.route == ["PlannerAgent"]
    assert state.agent_route == ["PlannerAgent"]


def test_supervisor_enforces_step_limit():
    state = _state()
    nodes = {
        "first": AgentNode(
            name="FirstAgent",
            run=lambda: None,
            next_agent=lambda _: "second",
        ),
        "second": AgentNode(
            name="SecondAgent",
            run=lambda: None,
            next_agent=lambda _: "third",
        ),
        "third": AgentNode(
            name="ThirdAgent",
            run=lambda: None,
            next_agent=lambda _: "fourth",
        ),
        "fourth": AgentNode(
            name="FourthAgent",
            run=lambda: None,
            next_agent=lambda _: None,
        ),
    }

    result = AgentGraphSupervisor(max_steps=2).execute(state, nodes, start="first")

    assert result.stop_reason == "max_steps_reached"
    assert result.route == ["FirstAgent", "SecondAgent"]
    assert state.warnings
