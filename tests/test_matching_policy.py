from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.matching_policy import (
    A2AEvaluation,
    Candidate,
    build_candidate_windows,
    choose_a2a_winner,
    collect_blocked_event_ids,
    has_time_overlap,
    is_event_open_for_matching,
    is_passive_candidate_allowed,
)


@dataclass(frozen=True)
class TimeBox:
    start_time: datetime | None
    end_time: datetime | None


@dataclass(frozen=True)
class BlocklistRow:
    event_a_id: object
    event_b_id: object
    user_a_id: object
    user_b_id: object


class MatchingPolicyTests(unittest.TestCase):
    def test_candidate_windows_skip_blocked_and_split_top_three_then_next_three(self):
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
            vector_threshold=0.5,
            window_size=3,
            max_rounds=2,
        )

        self.assertEqual([[c.event_id for c in w] for w in windows], [
            [ids[0], ids[2], ids[3]],
            [ids[4], ids[5]],
        ])

    def test_candidate_windows_limit_a2a_to_two_rounds(self):
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

    def test_collect_blocked_event_ids_uses_event_pair_and_user_pair(self):
        source_event_id = uuid4()
        source_user_id = uuid4()
        blocked_event_by_pair = uuid4()
        allowed_event = uuid4()
        blocked_user_event = uuid4()
        blocked_user_id = uuid4()
        allowed_user_id = uuid4()
        event_pair_user_id = uuid4()

        blocked = collect_blocked_event_ids(
            source_event_id=source_event_id,
            source_user_id=source_user_id,
            candidate_events_by_user={
                blocked_user_id: [blocked_user_event],
                allowed_user_id: [allowed_event],
            },
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
                    user_a_id=blocked_user_id,
                    user_b_id=source_user_id,
                ),
            ],
        )

        self.assertEqual(blocked, {blocked_event_by_pair, blocked_user_event})

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


if __name__ == "__main__":
    unittest.main()
