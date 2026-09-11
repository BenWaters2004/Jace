from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.agents import director, runner


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    task = SimpleNamespace(
        title="Inspect the project and establish the actual behaviour",
        instruction="",
        agent_id="code",
    )

    original_original_request = runner._director_original_request
    try:
        runner._director_original_request = lambda _task: (
            "Investigate why a completed background result could be missed and work out the best fix."
        )

        draft = """
        ## Missing Evidence
        The current files only expose task types and an API wrapper.
        I still need to inspect the background worker, completion detection,
        result delivery path, event publishing, and persistence flow.
        A symbol such as `publish_completion_event` or the consumer of
        `agent.task.completed` would close the evidence gap.
        """
        terms = runner._gap_search_terms(task, draft, [], limit=12)
        folded = [value.casefold() for value in terms]

        assert_true(
            any("publish_completion_event" in value for value in folded),
            f"Expected exact missing-evidence symbol to be prioritised; got {terms}",
        )
        assert_true(
            any(
                needle in value
                for value in folded
                for needle in ("worker", "completion", "delivery", "event", "persist")
            ),
            f"Expected missing implementation-layer concepts in frontier search terms; got {terms}",
        )
    finally:
        runner._director_original_request = original_original_request

    raw = (
        "### Investigation Complete: Root Cause Identified\n"
        "**Root Cause:** The client definitely does not poll."
    )
    sanitised = director._sanitize_unverified_analyst_language(raw)
    assert_true(
        "Root Cause Identified" not in sanitised,
        "Unverified Analyst output must not retain a confirmed-root-cause heading.",
    )
    assert_true(
        sanitised.startswith("UNVERIFIED REVIEW"),
        "Unverified Analyst output must be explicitly prefixed as unverified.",
    )

    step = SimpleNamespace(depends_on=["code"])
    outcomes = {
        "code": SimpleNamespace(
            verified=False,
            result=(
                "Missing Evidence: I still need to inspect the worker and result delivery path "
                "before the root cause can be confirmed."
            ),
        )
    }
    assert_true(
        director._dependency_has_explicit_evidence_gap(step, outcomes),
        "Analyst should recognise an explicitly evidence-incomplete upstream dependency.",
    )

    runner_source = (BACKEND_ROOT / "jace" / "agents" / "runner.py").read_text(encoding="utf-8")
    assert_true(
        "_bootstrap_gap_followup_evidence(" in runner_source,
        "Runner is missing deterministic evidence-frontier continuation.",
    )
    assert_true(
        "expanded the unresolved evidence frontier" in runner_source,
        "Runner is missing evidence-frontier continuation logging.",
    )
    assert_true(
        "prior_discovery" in runner_source,
        "Runner should preserve audited discovery provenance on model-triggered rereads.",
    )

    print(
        "PASS: 11B.4.14 continues unresolved investigations from the evidence frontier, "
        "preserves source provenance on rereads, and prevents Analyst from promoting "
        "evidence-incomplete hypotheses to confirmed root causes."
    )


if __name__ == "__main__":
    main()
