from __future__ import annotations

"""Pure matching policy helpers used by active and passive matching.

Keep this module free of database and network calls so the matching rules are
easy to test and reuse from the service layer.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

VECTOR_MATCH_THRESHOLD = 0.55
A2A_MATCH_THRESHOLD = 0.70
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
    score_breakdown: list[dict] = field(default_factory=list)
    dialogue_log: str | None = None


@dataclass(frozen=True)
class AgeFilterDecision:
    should_pass: bool
    issues: list[str] = field(default_factory=list)
    score_boost: float = 0.0


@dataclass(frozen=True)
class GenderFilterDecision:
    should_pass: bool
    issues: list[str] = field(default_factory=list)
    score_boost: float = 0.0


@dataclass(frozen=True)
class _GenderRequirement:
    strict: str | None = None
    preferred: str | None = None


AGE_PREFERENCE_SCORE_BOOST = 0.03
GENDER_PREFERENCE_SCORE_BOOST = 0.04


def canonical_pair_id(id_a: UUID, id_b: UUID) -> tuple[UUID, UUID]:
    return (id_a, id_b) if str(id_a) <= str(id_b) else (id_b, id_a)


def collect_blocked_event_ids(
    *,
    source_event_id: UUID,
    blocklist_rows,
) -> set[UUID]:
    blocked: set[UUID] = set()
    for row in blocklist_rows:
        if row.event_a_id == source_event_id and row.event_b_id:
            blocked.add(row.event_b_id)
        if row.event_b_id == source_event_id and row.event_a_id:
            blocked.add(row.event_a_id)
    return blocked


def has_time_overlap(source, candidate) -> bool:
    """Return False only when both events have full non-overlapping ranges."""
    if not (source.start_time and source.end_time and candidate.start_time and candidate.end_time):
        return True
    return not (source.end_time < candidate.start_time or candidate.end_time < source.start_time)


def age_on_date(birth_date: date, today: date) -> int:
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def is_age_filter_compatible(
    *,
    source_event,
    source_birth_date: date | None,
    candidate_event,
    candidate_birth_date: date | None,
    today: date,
) -> AgeFilterDecision:
    """Check both events' age filters without hard rejecting unknown ages."""
    issues: list[str] = []
    score_boost = 0.0

    source_decision = _check_one_age_filter(
        event=source_event,
        target_birth_date=candidate_birth_date,
        today=today,
        target_label="候选",
    )
    if not source_decision.should_pass:
        return source_decision
    issues.extend(source_decision.issues)
    score_boost += source_decision.score_boost

    candidate_decision = _check_one_age_filter(
        event=candidate_event,
        target_birth_date=source_birth_date,
        today=today,
        target_label="发起方",
    )
    if not candidate_decision.should_pass:
        return candidate_decision
    issues.extend(candidate_decision.issues)
    score_boost += candidate_decision.score_boost

    return AgeFilterDecision(should_pass=True, issues=issues, score_boost=score_boost)


def _check_one_age_filter(
    *,
    event,
    target_birth_date: date | None,
    today: date,
    target_label: str,
) -> AgeFilterDecision:
    min_age = getattr(event, "age_filter_min", None)
    max_age = getattr(event, "age_filter_max", None)
    mode = getattr(event, "age_filter_mode", None)
    if min_age is None or max_age is None or mode not in {"hard_filter", "preference"}:
        return AgeFilterDecision(should_pass=True, issues=[])

    if target_birth_date is None:
        if mode == "hard_filter":
            return AgeFilterDecision(
                should_pass=True,
                issues=[f"{target_label}未填写出生日期，无法验证年龄范围 {min_age}-{max_age} 岁"],
            )
        return AgeFilterDecision(should_pass=True, issues=[])

    target_age = age_on_date(target_birth_date, today)
    in_range = min_age <= target_age <= max_age
    if in_range:
        boost = AGE_PREFERENCE_SCORE_BOOST if mode == "preference" else 0.0
        return AgeFilterDecision(should_pass=True, issues=[], score_boost=boost)

    if mode == "hard_filter":
        return AgeFilterDecision(
            should_pass=False,
            issues=[f"{target_label}年龄 {target_age} 不在要求范围 {min_age}-{max_age} 岁"],
        )
    return AgeFilterDecision(
        should_pass=True,
        issues=[f"{target_label}年龄 {target_age} 不符合偏好范围 {min_age}-{max_age} 岁"],
    )


def is_gender_filter_compatible(
    *,
    source_event,
    source_gender: str | None,
    candidate_event,
    candidate_gender: str | None,
) -> GenderFilterDecision:
    """Check strict partner gender requirements and score soft preferences."""
    issues: list[str] = []
    score_boost = 0.0

    source_decision = _check_one_gender_filter(
        event=source_event,
        target_gender=candidate_gender,
        target_label="候选",
    )
    if not source_decision.should_pass:
        return source_decision
    issues.extend(source_decision.issues)
    score_boost += source_decision.score_boost

    candidate_decision = _check_one_gender_filter(
        event=candidate_event,
        target_gender=source_gender,
        target_label="发起方",
    )
    if not candidate_decision.should_pass:
        return candidate_decision
    issues.extend(candidate_decision.issues)
    score_boost += candidate_decision.score_boost

    return GenderFilterDecision(
        should_pass=True,
        issues=issues,
        score_boost=score_boost,
    )


def _check_one_gender_filter(
    *,
    event,
    target_gender: str | None,
    target_label: str,
) -> GenderFilterDecision:
    requirement = _gender_requirement_for_event(event)
    normalized_target = normalize_gender(target_gender)

    if requirement.strict:
        required_label = _gender_label(requirement.strict)
        if normalized_target is None:
            return GenderFilterDecision(
                should_pass=False,
                issues=[f"{target_label}未填写性别，无法满足性别要求：{required_label}"],
            )
        if normalized_target != requirement.strict:
            return GenderFilterDecision(
                should_pass=False,
                issues=[f"{target_label}性别 {_gender_label(normalized_target)} 不符合要求：{required_label}"],
            )
        return GenderFilterDecision(should_pass=True)

    if requirement.preferred:
        preferred_label = _gender_label(requirement.preferred)
        if normalized_target == requirement.preferred:
            return GenderFilterDecision(
                should_pass=True,
                score_boost=GENDER_PREFERENCE_SCORE_BOOST,
            )
        if normalized_target is not None:
            return GenderFilterDecision(
                should_pass=True,
                issues=[f"{target_label}性别 {_gender_label(normalized_target)} 不符合偏好：{preferred_label}"],
            )

    return GenderFilterDecision(should_pass=True)


def _gender_requirement_for_event(event) -> _GenderRequirement:
    strict: str | None = None
    preferred: str | None = None

    for item in _event_text_list(event, "constraints"):
        strict = _gender_from_text(item)
        if strict:
            break

    for item in _event_text_list(event, "preferences"):
        if _is_unlimited_gender_text(item):
            continue
        gender = _gender_from_text(item)
        if gender and _is_preferred_gender_text(item):
            preferred = gender
            break

    return _GenderRequirement(strict=strict, preferred=preferred)


def normalize_gender(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if "不限" in text or "保密" in text or "未知" in text:
        return None
    if text in {"female", "woman", "girl", "f"}:
        return "female"
    if text in {"male", "man", "boy", "m"}:
        return "male"
    has_female = "女" in text
    has_male = "男" in text
    if has_female and not has_male:
        return "female"
    if has_male and not has_female:
        return "male"
    return None


def adjusted_candidate_score(
    vector_score: float,
    *decisions: AgeFilterDecision | GenderFilterDecision,
) -> float:
    boost = sum(decision.score_boost for decision in decisions if decision.should_pass)
    return min(1.0, vector_score + boost)


def _event_text_list(event, field: str) -> list[str]:
    value = getattr(event, field, None)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _gender_from_text(text: str) -> str | None:
    return normalize_gender(text)


def _is_preferred_gender_text(text: str) -> bool:
    return any(token in text for token in ("优先", "偏好", "希望", "prefer"))


def _is_unlimited_gender_text(text: str) -> bool:
    return any(token in text for token in ("不限", "都可以", "无所谓", "any"))


def _gender_label(gender: str) -> str:
    return "女" if gender == "female" else "男"


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
