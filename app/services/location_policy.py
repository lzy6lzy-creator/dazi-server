from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.location_normalizer import (
    PlaceProfile,
    activity_strictness,
    normalize_place,
    region_contains_city,
)


STRICTNESS_LEVEL = {
    "none": 0,
    "loose": 1,
    "medium": 2,
    "strict": 3,
}


@dataclass(frozen=True)
class LocationDecision:
    should_pass: bool
    score: float
    relation: str
    threshold: float
    source: PlaceProfile
    target: PlaceProfile


def combined_strictness(source_activity_type: str | None, target_activity_type: str | None) -> str:
    return max(
        [activity_strictness(source_activity_type), activity_strictness(target_activity_type)],
        key=lambda item: STRICTNESS_LEVEL[item],
    )


def threshold_for(strictness: str) -> float:
    return {
        "none": 0.0,
        "loose": 0.35,
        "medium": 0.35,
        "strict": 0.6,
    }[strictness]


def city_in_region(city: str | None, region_name: str | None) -> bool:
    return region_contains_city(city, region_name)


def profile_compatible(source: PlaceProfile, target: PlaceProfile, strictness: str) -> tuple[float, str]:
    if source.place_kind == "online" or target.place_kind == "online":
        return 1.0, "online"
    if source.place_kind == "flexible" or target.place_kind == "flexible":
        return 0.75, "flexible"
    if source.place_normalized and source.place_normalized == target.place_normalized:
        return 1.0, "same_place"
    if source.admin_city and source.admin_city == target.admin_city:
        return 0.85, "same_city"

    if strictness == "strict" and (
        source.geo_scope in {"travel", "cross_city", "regional"}
        or target.geo_scope in {"travel", "cross_city", "regional"}
    ):
        return 0.4, "strict_cross_city"

    if source.place_kind == "region" and city_in_region(target.admin_city, source.place_normalized):
        return 0.75, "city_in_region"
    if target.place_kind == "region" and city_in_region(source.admin_city, target.place_normalized):
        return 0.75, "city_in_region"
    if source.place_kind == "region" and target.place_normalized in source.aliases:
        return 0.78, "region_contains_place"
    if target.place_kind == "region" and source.place_normalized in target.aliases:
        return 0.78, "region_contains_place"

    if source.admin_region and target.admin_region and source.admin_region == target.admin_region:
        if strictness == "strict" and source.admin_city and target.admin_city and source.admin_city != target.admin_city:
            return 0.4, "strict_cross_city"
        return 0.65, "same_region"

    if not source.place_normalized or not target.place_normalized:
        return 0.3, "unknown_or_empty"
    return 0.0, "conflict"


def _event_value(event: Any, key: str):
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key, None)


def is_location_compatible(source_event: Any, target_event: Any) -> LocationDecision:
    source_profile = normalize_place(
        activity_type=_event_value(source_event, "activity_type"),
        city=_event_value(source_event, "city"),
        location=_event_value(source_event, "location"),
    )
    target_profile = normalize_place(
        activity_type=_event_value(target_event, "activity_type"),
        city=_event_value(target_event, "city"),
        location=_event_value(target_event, "location"),
    )
    strictness = combined_strictness(
        _event_value(source_event, "activity_type"),
        _event_value(target_event, "activity_type"),
    )
    score, relation = profile_compatible(source_profile, target_profile, strictness)
    threshold = threshold_for(strictness)
    return LocationDecision(score >= threshold, score, relation, threshold, source_profile, target_profile)
