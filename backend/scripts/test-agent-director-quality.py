from __future__ import annotations

from jace.agents.director import (
    DirectorStep,
    StepOutcome,
    _fallback_plan,
    _normalise_route_agents,
    _verification_for_step,
)


def main() -> None:
    objective = (
        "Investigate why the agent handoff system in the Jace project could miss "
        "a completed background result and work out the best fix."
    )
    plan = _fallback_plan(objective, [])
    ids = [step.agent_id for step in plan.steps]
    assert ids[0] == "code", ids
    assert "research" not in ids, ids
    assert "analyst" in ids, ids

    guarded = _normalise_route_agents(objective, ["research", "analyst"])
    assert "code" in guarded, guarded
    assert "research" not in guarded, guarded

    code_step = DirectorStep(
        id="code",
        agent_id="code",
        title="Inspect Jace",
        instruction="Inspect source",
    )
    verified, _ = _verification_for_step(
        code_step,
        used_tools=["list_computer_workspaces", "read_workspace_file"],
        outcomes={},
        result="Verified in backend/jace/agents/runner.py",
    )
    assert verified is True

    unverified, _ = _verification_for_step(
        code_step,
        used_tools=["list_computer_workspaces"],
        outcomes={},
        result="I think the registry is deleted.",
    )
    assert unverified is False

    analyst = DirectorStep(
        id="analysis",
        agent_id="analyst",
        title="Review",
        instruction="Review evidence",
        depends_on=["code"],
    )
    outcomes = {
        "code": StepOutcome(
            step_id="code",
            agent_id="code",
            title="Inspect Jace",
            status="completed",
            result="Source-backed result",
            used_tools=["read_workspace_file"],
            verified=True,
            evidence="Local workspace evidence",
        )
    }
    analyst_verified, _ = _verification_for_step(
        analyst,
        used_tools=[],
        outcomes=outcomes,
        result="Review",
    )
    assert analyst_verified is True

    print("PASS: 11B.4.1 Director evidence/quality guardrails are working.")


if __name__ == "__main__":
    main()
