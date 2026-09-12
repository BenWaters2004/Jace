from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "jace" / "agents" / "runner.py"
SOURCE = RUNNER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

NAMES = {
    "_ARTIFACT_PATH_RE",
    "_BOOTSTRAP_STOPWORDS",
    "_BOOTSTRAP_LOW_SIGNAL_TERMS",
    "_artifact_references_in_draft",
    "_unread_artifacts_named_in_draft",
    "_structural_expansion_terms",
    "_source_evidence_dossier",
}

selected: list[ast.stmt] = []
for node in TREE.body:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets: list[str] = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    targets.append(target.id)
        elif isinstance(node.target, ast.Name):
            targets.append(node.target.id)
        if any(name in NAMES for name in targets):
            selected.append(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES:
        selected.append(node)

namespace: dict[str, Any] = {
    "re": re,
    "Path": Path,
    "Any": Any,
}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(RUNNER), "exec"), namespace)

artifact_refs = namespace["_artifact_references_in_draft"]
structural_terms = namespace["_structural_expansion_terms"]
dossier = namespace["_source_evidence_dossier"]

# A concrete path requested for inspection remains concrete.
concrete, speculative = artifact_refs(
    "Required Additional Inspection:\n- `backend/jace/agents/runner.py`\n- `backend/jace/agents/director.py`",
    set(),
)
assert "backend/jace/agents/runner.py" in concrete, (concrete, speculative)
assert "backend/jace/agents/director.py" in concrete, (concrete, speculative)
assert not speculative, (concrete, speculative)

# Plausible model guesses must not be promoted to trusted named artifacts.
concrete, speculative = artifact_refs(
    "The files likely needed are background worker modules such as `backend/jace/agents/workers.py`, "
    "`apps/desktop/src/agents/worker.ts`, or similar.",
    set(),
)
assert not concrete, (concrete, speculative)
assert "backend/jace/agents/workers.py" in speculative, speculative
assert "apps/desktop/src/agents/worker.ts" in speculative, speculative

# Real route strings and source symbols should become cross-reference anchors.
records = [
    {
        "evidence": {
            "text": """
export type AgentTaskStatus = \"queued\" | \"completed\";
export const getAgentTasks = (limit = 100) =>
  agentRequest(`/agents/tasks?limit=${encodeURIComponent(String(limit))}`);
export const getAgentTaskEvents = (taskId: string) =>
  agentRequest(`/agents/tasks/${taskId}/events?limit=200`);
"""
        }
    }
]
terms = structural_terms(records, limit=20)
assert "/agents/tasks" in terms, terms
assert "AgentTaskStatus" in terms, terms
assert "getAgentTasks" in terms, terms

# The final dossier must retain seed context but favour newest frontier evidence.
records = [
    {"evidence": {"path": f"src/file{i}.py", "text": f"def symbol_{i}():\n    return {i}\n" * 20}}
    for i in range(8)
]
text = dossier(records)
assert "SOURCE FILE: src/file0.py" in text
assert "SOURCE FILE: src/file1.py" in text
assert "SOURCE FILE: src/file7.py" in text
assert "SOURCE FILE: src/file2.py" not in text, "middle-only evidence should yield space to newer frontier files"

# Verify the closure order in source: named concrete path -> verified cross-ref -> semantic gap.
close_start = SOURCE.index("async def _close_source_evidence_frontier")
close_end = SOURCE.index("\ndef _parse_tool_json", close_start)
close_src = SOURCE[close_start:close_end]
idx_named = close_src.index("_bootstrap_named_followup_evidence")
idx_cross = close_src.index("_bootstrap_cross_reference_followup_evidence")
idx_gap = close_src.index("_bootstrap_gap_followup_evidence")
assert idx_named < idx_cross < idx_gap, (idx_named, idx_cross, idx_gap)

# Inner source-backed continuation should use the same ordering.
inner_marker = "if (\n                requires_local_source\n                and coverage_ok\n                and _draft_has_unresolved_frontier(candidate_text)"
inner_start = SOURCE.index(inner_marker)
inner_end = SOURCE.index("            final_text = candidate_text", inner_start)
inner_src = SOURCE[inner_start:inner_end]
assert inner_src.index("_bootstrap_named_followup_evidence") < inner_src.index("_bootstrap_cross_reference_followup_evidence") < inner_src.index("_bootstrap_gap_followup_evidence")

# Gap search must scrub file paths instead of searching model-invented basenames.
gap_start = SOURCE.index("def _gap_search_terms")
gap_end = SOURCE.index("\n\nasync def _bootstrap_cross_reference_followup_evidence", gap_start)
gap_src = SOURCE[gap_start:gap_end]
assert '_ARTIFACT_PATH_RE.sub(" ", excerpt)' in gap_src

# Finalizer must explicitly prohibit guessed paths.
assert "NEVER fabricate a plausible path for missing evidence" in SOURCE

print(
    "PASS: 11B.4.17 distinguishes speculative filenames from concrete artifacts, "
    "follows verified source cross-references before semantic gap search, and keeps "
    "new frontier evidence visible to finalisation."
)
