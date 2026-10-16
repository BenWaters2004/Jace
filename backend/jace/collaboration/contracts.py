"""C4A request/response contracts. Model agreement is not evidence verification."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceNote(BaseModel):
    """User-supplied notes. Neither an external citation nor a verified source receipt."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    content: str = Field(min_length=1, max_length=2500)


class CollaborationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=5, max_length=10000)
    notes: list[SourceNote] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def distinct_ids(self):
        ids = [note.id for note in self.notes]
        if len(ids) != len(set(ids)):
            raise ValueError("Source note IDs must be unique.")
        return self


class ReviewerAssessment(BaseModel):
    """An independent model opinion, NOT a machine-verified fact check."""
    model_config = ConfigDict(extra="forbid")
    assessment: Literal["no_major_concerns", "concerns", "insufficient_evidence"]
    summary: str = Field(min_length=1, max_length=2400)
    material_issues: list[str] = Field(default_factory=list, max_length=8)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=8)
    contradictions: list[str] = Field(default_factory=list, max_length=8)
    improvements: list[str] = Field(default_factory=list, max_length=8)


class CollaborationResponse(BaseModel):
    status: Literal["completed"] = "completed"
    drafter_route: str
    reviewer_route: str
    draft: str
    review: ReviewerAssessment
    final_answer: str
    verification_status: Literal["not_verified"] = "not_verified"
    evidence_source: Literal["user_supplied_unverified", "none"]
    verified_citations: list[str] = Field(default_factory=list)
    tools_executed: int = 0
    model_calls: int = 3
    notice: str = (
        "This is cross-provider editorial review only. The models did not independently "
        "retrieve sources, run tools or verify factual claims."
    )
