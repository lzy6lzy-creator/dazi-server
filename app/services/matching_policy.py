from __future__ import annotations

"""Pure matching policy helpers used by active and passive matching.

Keep this module free of database and network calls so the matching rules are
easy to test and reuse from the service layer.
"""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

VECTOR_MATCH_THRESHOLD = 0.55
A2A_MATCH_THRESHOLD = 0.65
A2A_WINDOW_SIZE = 3
MAX_A2A_ROUNDS = 1


@dataclass(frozen=True)
class Candidate:
    event_id: UUID
    vector_score: float


@dataclass(frozen=True)
class A2AEvaluation:
    source_event_id: UUID
    candidate_event_id: UUID
    compatibility: float
    should_match: bool
    summary: str
    reasons: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    dialogue_log: str | None = None


def canonical_pair_id(id_a: UUID, id_b: UUID) -> tuple[UUID, UUID]:
    return (id_a, id_b) if str(id_a) <= str(id_b) else (id_b, id_a)


def collect_blocked_event_ids(
    *,
    source_event_id: UUID,
    source_user_id: UUID,
    candidate_events_by_user: dict[UUID, list[UUID]],
    blocklist_rows,
) -> set[UUID]:
    blocked: set[UUID] = set()
    for row in blocklist_rows:
        if row.event_a_id == source_event_id and row.event_b_id:
            blocked.add(row.event_b_id)
        if row.event_b_id == source_event_id and row.event_a_id:
            blocked.add(row.event_a_id)
        if row.user_a_id == source_user_id:
            blocked.update(candidate_events_by_user.get(row.user_b_id, []))
        if row.user_b_id == source_user_id:
            blocked.update(candidate_events_by_user.get(row.user_a_id, []))
    return blocked


def has_time_overlap(source, candidate) -> bool:
    """Return False only when both events have full non-overlapping ranges."""
    if not (source.start_time and source.end_time and candidate.start_time and candidate.end_time):
        return True
    return not (source.end_time < candidate.start_time or candidate.end_time < source.start_time)


def build_candidate_windows(
    candidates: list[Candidate],
    blocked_event_ids: set[UUID],
    vector_threshold: float = VECTOR_MATCH_THRESHOLD,
    window_size: int = A2A_WINDOW_SIZE,
    max_rounds: int = MAX_A2A_ROUNDS,
) -> list[list[Candidate]]:
    eligible = [
        candidate for candidate in candidates
        if candidate.event_id not in blocked_event_ids and candidate.vector_score >= vector_threshold
    ]
    return [
        eligible[i:i + window_size]
        for i in range(0, min(len(eligible), window_size * max_rounds), window_size)
        if eligible[i:i + window_size]
    ]


def choose_a2a_winner(
    evaluations: list[A2AEvaluation],
    min_score: float = A2A_MATCH_THRESHOLD,
) -> A2AEvaluation | None:
    accepted = [
        result for result in evaluations
        if result.should_match and result.compatibility >= min_score
    ]
    if not accepted:
        return None
    return max(accepted, key=lambda result: result.compatibility)


def is_passive_candidate_allowed(
    *,
    is_active: bool,
    has_embedding: bool,
    welcome_disturb: bool,
) -> bool:
    return is_active and has_embedding and welcome_disturb


def is_event_open_for_matching(
    *,
    start_time: datetime | None,
    expires_at: datetime | None,
    now: datetime,
) -> bool:
    if expires_at is not None and expires_at <= now:
        return False
    if start_time is not None and start_time <= now:
        return False
    return True
