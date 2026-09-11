from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
RUNNER = BACKEND_ROOT / "jace" / "agents" / "runner.py"
DIRECTOR = BACKEND_ROOT / "jace" / "agents" / "director.py"


def fail(message: str) -> None:
    raise AssertionError(message)


def calls_in(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        fn = child.func
        if isinstance(fn, ast.Name):
            found.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            found.add(fn.attr)
    return found


def main() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RUNNER))

    async_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
    }

    closer = async_functions.get("_close_source_evidence_frontier")
    if closer is None:
        fail("runner.py is missing _close_source_evidence_frontier().")

    closer_calls = calls_in(closer)
    for required in {
        "_bootstrap_named_followup_evidence",
        "_bootstrap_gap_followup_evidence",
        "_finalize_source_backed_handoff",
    }:
        if required not in closer_calls:
            fail(f"Post-budget frontier closure does not call {required}().")

    execute = async_functions.get("execute_agent_task")
    if execute is None:
        fail("runner.py is missing execute_agent_task().")

    helper_calls = [
        node for node in ast.walk(execute)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_close_source_evidence_frontier"
    ]
    if not helper_calls:
        fail("execute_agent_task() never invokes post-budget frontier closure.")

    tool_loops = [
        node for node in ast.walk(execute)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "step"
    ]
    if not tool_loops:
        fail("Could not find the bounded model/tool loop in execute_agent_task().")

    tool_loop_end = max(int(getattr(node, "end_lineno", node.lineno)) for node in tool_loops)
    if not any(call.lineno > tool_loop_end for call in helper_calls):
        fail(
            "_close_source_evidence_frontier() must be invoked after the bounded model/tool loop, "
            "otherwise missing evidence discovered at tool-limit finalisation is still lost."
        )

    # Guard against regressing to file-count-only completion: the closure call
    # must itself be conditional on the final handoff declaring missing evidence.
    execute_segment = ast.get_source_segment(source, execute) or ""
    if "_draft_declares_missing_evidence(final_text)" not in execute_segment:
        fail("Post-budget closure is not gated by the final source-backed missing-evidence state.")

    if "max_rounds=4" not in execute_segment:
        fail("Post-budget deterministic frontier closure must remain bounded.")

    # Keep the existing Director verification safeguard that prevents a worker's
    # own unresolved-evidence statement from being upgraded to VERIFIED.
    director_source = DIRECTOR.read_text(encoding="utf-8")
    if "Worker explicitly reported that material source evidence remained unresolved." not in director_source:
        fail("Director unresolved-evidence verification safeguard is missing.")

    compile(source, str(RUNNER), "exec")
    compile(director_source, str(DIRECTOR), "exec")

    print(
        "PASS: 11B.4.15 closes unresolved source evidence after the model/tool budget, "
        "follows named or conceptual gaps deterministically, and keeps the closure bounded."
    )


if __name__ == "__main__":
    main()
