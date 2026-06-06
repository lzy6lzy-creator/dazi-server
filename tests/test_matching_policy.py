from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.matching_policy import (
    A2AEvaluation,
    AgeFilterDecision,
    Candidate,
    GenderFilterDecision,
    VECTOR_MATCH_THRESHOLD,
    adjusted_candidate_score,
    build_candidate_windows,
    choose_a2a_winner,
    collect_blocked_event_ids,
    has_time_overlap,
    is_age_filter_compatible,
    is_event_open_for_matching,
    is_gender_filter_compatible,
    is_passive_candidate_allowed,
)


@dataclass(frozen=True)
class TimeBox:
    start_time: datetime | None
    end_time: datetime | None


@dataclass(frozen=True)
class AgeFilterBox:
    age_filter_min: int | None
    age_filter_max: int | None
    age_filter_mode: str | None


@dataclass(frozen=True)
class MatchPreferenceBox:
    preferences: list[str] | None
    constraints: list[str] | None
    age_filter_min: int | None = None
    age_filter_max: int | None = None
    age_filter_mode: str | None = None


@dataclass(frozen=True)
class BlocklistRow:
    event_a_id: object
    event_b_id: object
    user_a_id: object
    user_b_id: object


class MatchingPolicyTests(unittest.TestCase):
    def test_default_vector_threshold_is_fifty_five(self):
        self.assertEqual(VECTOR_MATCH_THRESHOLD, 0.55)

    def test_candidate_windows_return_only_top_three_above_threshold(self):
        ids = [uuid4() for _ in range(5)]
        candidates = [
            Candidate(event_id=ids[0], vector_score=0.91),
            Candidate(event_id=ids[1], vector_score=0.80),
            Candidate(event_id=ids[2], vector_score=0.60),
            Candidate(event_id=ids[3], vector_score=0.54),
            Candidate(event_id=ids[4], vector_score=0.53),
        ]

        windows = build_candidate_windows(candidates, blocked_event_ids=set())

        self.assertEqual([[c.event_id for c in w] for w in windows], [
            [ids[0], ids[1], ids[2]],
        ])

    def test_candidate_windows_skip_blocked_and_keep_only_top_three_by_default(self):
        ids = [uuid4() for _ in range(8)]
        candidates = [
            Candidate(event_id=ids[0], vector_score=0.91),
            Candidate(event_id=ids[1], vector_score=0.89),
            Candidate(event_id=ids[2], vector_score=0.81),
            Candidate(event_id=ids[3], vector_score=0.77),
            Candidate(event_id=ids[4], vector_score=0.72),
            Candidate(event_id=ids[5], vector_score=0.68),
            Candidate(event_id=ids[6], vector_score=0.49),
            Candidate(event_id=ids[7], vector_score=0.40),
        ]

        windows = build_candidate_windows(
            candidates,
            blocked_event_ids={ids[1]},
        )

        self.assertEqual([[c.event_id for c in w] for w in windows], [
            [ids[0], ids[2], ids[3]],
        ])

    def test_candidate_windows_can_split_multiple_rounds_when_explicitly_requested(self):
        ids = [uuid4() for _ in range(7)]
        candidates = [Candidate(event_id=event_id, vector_score=0.8) for event_id in ids]

        windows = build_candidate_windows(
            candidates,
            blocked_event_ids=set(),
            vector_threshold=0.5,
            window_size=3,
            max_rounds=2,
        )

        self.assertEqual([[c.event_id for c in w] for w in windows], [
            ids[:3],
            ids[3:6],
        ])

    def test_choose_a2a_winner_requires_acceptance_and_minimum_score(self):
        source_id = uuid4()
        low = uuid4()
        rejected = uuid4()
        best = uuid4()
        evaluations = [
            A2AEvaluation(source_event_id=source_id, candidate_event_id=low, compatibility=0.55, should_match=True, summary="too low"),
            A2AEvaluation(source_event_id=source_id, candidate_event_id=rejected, compatibility=0.95, should_match=False, summary="conflict"),
            A2AEvaluation(source_event_id=source_id, candidate_event_id=best, compatibility=0.82, should_match=True, summary="best"),
        ]

        winner = choose_a2a_winner(evaluations, min_score=0.6)

        self.assertIsNotNone(winner)
        self.assertEqual(winner.candidate_event_id, best)

    def test_collect_blocked_event_ids_uses_only_event_pair_not_user_pair(self):
        source_event_id = uuid4()
        source_user_id = uuid4()
        blocked_event_by_pair = uuid4()
        candidate_user_id = uuid4()
        event_pair_user_id = uuid4()
        old_source_event_id = uuid4()
        old_candidate_event_id = uuid4()

        blocked = collect_blocked_event_ids(
            source_event_id=source_event_id,
            blocklist_rows=[
                BlocklistRow(
                    event_a_id=source_event_id,
                    event_b_id=blocked_event_by_pair,
                    user_a_id=source_user_id,
                    user_b_id=event_pair_user_id,
                ),
                BlocklistRow(
                    event_a_id=None,
                    event_b_id=None,
                    user_a_id=candidate_user_id,
                    user_b_id=source_user_id,
                ),
                BlocklistRow(
                    event_a_id=old_source_event_id,
                    event_b_id=old_candidate_event_id,
                    user_a_id=source_user_id,
                    user_b_id=candidate_user_id,
                ),
            ],
        )

        self.assertEqual(blocked, {blocked_event_by_pair})

    def test_collect_blocked_event_ids_skips_a2a_rejected_event_pair(self):
        source_event_id = uuid4()
        source_user_id = uuid4()
        candidate_event_id = uuid4()
        candidate_user_id = uuid4()

        blocked = collect_blocked_event_ids(
            source_event_id=source_event_id,
            blocklist_rows=[
                BlocklistRow(
                    event_a_id=source_event_id,
                    event_b_id=candidate_event_id,
                    user_a_id=source_user_id,
                    user_b_id=candidate_user_id,
                )
            ],
        )

        self.assertEqual(blocked, {candidate_event_id})

    def test_time_overlap_is_hard_filter_when_both_ranges_exist(self):
        now = datetime.now(timezone.utc)
        source = TimeBox(now, now + timedelta(hours=2))
        overlap = TimeBox(now + timedelta(hours=1), now + timedelta(hours=3))
        no_overlap = TimeBox(now + timedelta(hours=3), now + timedelta(hours=5))
        open_time = TimeBox(None, None)

        self.assertTrue(has_time_overlap(source, overlap))
        self.assertFalse(has_time_overlap(source, no_overlap))
        self.assertTrue(has_time_overlap(source, open_time))

    def test_passive_candidate_requires_explicit_welcome_disturb(self):
        self.assertTrue(is_passive_candidate_allowed(is_active=True, has_embedding=True, welcome_disturb=True))
        self.assertFalse(is_passive_candidate_allowed(is_active=True, has_embedding=True, welcome_disturb=False))
        self.assertFalse(is_passive_candidate_allowed(is_active=False, has_embedding=True, welcome_disturb=True))
        self.assertFalse(is_passive_candidate_allowed(is_active=True, has_embedding=False, welcome_disturb=True))

    def test_event_open_for_matching_rejects_expired_or_already_started_events(self):
        now = datetime.now(timezone.utc)

        self.assertTrue(is_event_open_for_matching(
            start_time=now + timedelta(hours=2),
            expires_at=None,
            now=now,
        ))
        self.assertFalse(is_event_open_for_matching(
            start_time=now - timedelta(minutes=1),
            expires_at=None,
            now=now,
        ))
        self.assertFalse(is_event_open_for_matching(
            start_time=now + timedelta(hours=2),
            expires_at=now - timedelta(minutes=1),
            now=now,
        ))

    def test_age_filter_passes_when_candidate_age_is_in_range(self):
        decision = is_age_filter_compatible(
            source_event=AgeFilterBox(23, 32, "hard_filter"),
            source_birth_date=datetime(1998, 6, 4).date(),
            candidate_event=AgeFilterBox(None, None, None),
            candidate_birth_date=datetime(2000, 1, 1).date(),
            today=datetime(2026, 6, 4).date(),
        )

        self.assertEqual(decision, AgeFilterDecision(should_pass=True, issues=[]))

    def test_age_filter_preference_mode_adds_boost_when_candidate_is_in_range(self):
        decision = is_age_filter_compatible(
            source_event=AgeFilterBox(23, 32, "preference"),
            source_birth_date=datetime(1998, 6, 4).date(),
            candidate_event=AgeFilterBox(None, None, None),
            candidate_birth_date=datetime(2000, 1, 1).date(),
            today=datetime(2026, 6, 4).date(),
        )

        self.assertTrue(decision.should_pass)
        self.assertGreater(decision.score_boost, 0)
        self.assertEqual(decision.issues, [])

    def test_age_filter_rejects_known_out_of_range_candidate(self):
        decision = is_age_filter_compatible(
            source_event=AgeFilterBox(23, 32, "hard_filter"),
            source_birth_date=datetime(1998, 6, 4).date(),
            candidate_event=AgeFilterBox(None, None, None),
            candidate_birth_date=datetime(1980, 1, 1).date(),
            today=datetime(2026, 6, 4).date(),
        )

        self.assertFalse(decision.should_pass)
        self.assertEqual(decision.issues, ["候选年龄 46 不在要求范围 23-32 岁"])

    def test_age_filter_does_not_reject_unknown_birth_date(self):
        decision = is_age_filter_compatible(
            source_event=AgeFilterBox(23, 32, "hard_filter"),
            source_birth_date=datetime(1998, 6, 4).date(),
            candidate_event=AgeFilterBox(None, None, None),
            candidate_birth_date=None,
            today=datetime(2026, 6, 4).date(),
        )

        self.assertTrue(decision.should_pass)
        self.assertEqual(decision.issues, ["候选未填写出生日期，无法验证年龄范围 23-32 岁"])

    def test_age_filter_preference_mode_never_hard_rejects(self):
        decision = is_age_filter_compatible(
            source_event=AgeFilterBox(23, 32, "preference"),
            source_birth_date=datetime(1998, 6, 4).date(),
            candidate_event=AgeFilterBox(None, None, None),
            candidate_birth_date=datetime(1980, 1, 1).date(),
            today=datetime(2026, 6, 4).date(),
        )

        self.assertTrue(decision.should_pass)
        self.assertEqual(decision.issues, ["候选年龄 46 不符合偏好范围 23-32 岁"])
        self.assertEqual(decision.score_boost, 0)

    def test_gender_filter_rejects_known_mismatch_for_strict_requirement(self):
        decision = is_gender_filter_compatible(
            source_event=MatchPreferenceBox(
                preferences=[],
                constraints=["搭子性别：女"],
            ),
            source_gender="男",
            candidate_event=MatchPreferenceBox(preferences=[], constraints=[]),
            candidate_gender="男",
        )

        self.assertEqual(
            decision,
            GenderFilterDecision(
                should_pass=False,
                issues=["候选性别 男 不符合要求：女"],
            ),
        )

    def test_gender_filter_rejects_unknown_gender_for_strict_requirement(self):
        decision = is_gender_filter_compatible(
            source_event=MatchPreferenceBox(
                preferences=[],
                constraints=["搭子性别：男"],
            ),
            source_gender="女",
            candidate_event=MatchPreferenceBox(preferences=[], constraints=[]),
            candidate_gender=None,
        )

        self.assertFalse(decision.should_pass)
        self.assertEqual(decision.issues, ["候选未填写性别，无法满足性别要求：男"])

    def test_gender_filter_soft_preference_adds_boost_without_rejecting_others(self):
        matched = is_gender_filter_compatible(
            source_event=MatchPreferenceBox(
                preferences=["搭子性别偏好：女生优先"],
                constraints=[],
            ),
            source_gender="男",
            candidate_event=MatchPreferenceBox(preferences=[], constraints=[]),
            candidate_gender="女",
        )
        unmatched = is_gender_filter_compatible(
            source_event=MatchPreferenceBox(
                preferences=["搭子性别偏好：女生优先"],
                constraints=[],
            ),
            source_gender="男",
            candidate_event=MatchPreferenceBox(preferences=[], constraints=[]),
            candidate_gender="男",
        )

        self.assertTrue(matched.should_pass)
        self.assertGreater(matched.score_boost, 0)
        self.assertTrue(unmatched.should_pass)
        self.assertEqual(unmatched.score_boost, 0)
        self.assertEqual(unmatched.issues, ["候选性别 男 不符合偏好：女"])

    def test_gender_filter_checks_candidate_requirement_against_source_gender(self):
        decision = is_gender_filter_compatible(
            source_event=MatchPreferenceBox(preferences=[], constraints=[]),
            source_gender="男",
            candidate_event=MatchPreferenceBox(
                preferences=[],
                constraints=["搭子性别：女"],
            ),
            candidate_gender="女",
        )

        self.assertFalse(decision.should_pass)
        self.assertEqual(decision.issues, ["发起方性别 男 不符合要求：女"])

    def test_adjusted_candidate_score_combines_age_and_gender_boosts(self):
        score = adjusted_candidate_score(
            0.96,
            AgeFilterDecision(should_pass=True, score_boost=0.03),
            GenderFilterDecision(should_pass=True, score_boost=0.04),
        )

        self.assertEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()
