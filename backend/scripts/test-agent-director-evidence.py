from __future__ import annotations

from jace.agents.director import (
    DirectorStep,
    StepOutcome,
    _fallback_plan,
    _normalise_route_agents,
    _verification_for_step,
)
from jace.agents.runner import _tool_evidence_payload


def _successful_read(path: str, text: str) -> dict:
    return _tool_evidence_payload(
        tool_name="read_workspace_file",
        arguments={"workspace_id": "00000000-0000-0000-0000-000000000000", "path": path},
        success=True,
        content=(
            '{"workspace":"Jace","path":"' + path + '",'
            '"sha256":"abc","start_line":1,"returned_lines":3,'
            '"text":' + __import__("json").dumps(text) + '}'
        ),
        display=f"Read 3 lines from Jace:{path}.",
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

    source_text = (
        "379: async def _persist_completion_handoff(...):\n"
        "387: Persist the specialist result into the originating conversation.\n"
        "408: message = await add_message(... )"
    )
    good_evidence = [_successful_read("backend/jace/agents/runner.py", source_text)]
    verified, reason, context = _verification_for_step(
        code_step,
        used_tools=["read_workspace_file"],
        outcomes={},
        result=(
            "The handoff is persisted in backend/jace/agents/runner.py by "
            "`_persist_completion_handoff`."
        ),
        tool_evidence=good_evidence,
    )
    assert verified is True, reason
    assert "runner.py" in context

    failed_attempt = _tool_evidence_payload(
        tool_name="read_workspace_file",
        arguments={"workspace_id": "x", "path": "backend/jace/agents/runner.py"},
        success=False,
        error="Unknown workspace",
    )
    verified, reason, _ = _verification_for_step(
        code_step,
        used_tools=["read_workspace_file"],
        outcomes={},
        result="Verified in backend/jace/agents/runner.py",
        tool_evidence=[failed_attempt],
    )
    assert verified is False
    assert "No successful source-file read" in reason

    verified, reason, _ = _verification_for_step(
        code_step,
        used_tools=["read_workspace_file"],
        outcomes={},
        result=(
            "The root cause is a `TaskRegistry` race in `BackgroundTaskHandler.py`. "
            "I also inspected backend/jace/agents/runner.py."
        ),
        tool_evidence=good_evidence,
    )
    assert verified is False
    assert "BackgroundTaskHandler.py" in reason or "TaskRegistry" in reason

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
            evidence="Source-backed Code evidence",
            evidence_context=context,
        )
    }
    analyst_verified, _, _ = _verification_for_step(
        analyst,
        used_tools=[],
        outcomes=outcomes,
        result="Review",
        tool_evidence=[],
    )
    assert analyst_verified is True

    print("PASS: 11B.4.2 Director verifies successful source evidence, not tool attempts.")


if __name__ == "__main__":
    main()
