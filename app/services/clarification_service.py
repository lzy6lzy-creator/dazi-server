from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any


MAX_OPTIONS = 6
_CONVERSATION_ACTIONS = {"chat", "clarify", "draft", "cancel"}
_DRAFT_STRING_FIELDS = ("title", "activity_type", "location", "start_time", "end_time")
_DRAFT_LIST_FIELDS = ("preferences", "constraints")
_AGE_FILTER_MODE_VALUES = {"preference", "hard_filter"}
_LOCATION_QUESTION_IDS = {"city", "location", "area", "place", "district", "region"}
_EVENT_QUESTION_IDS = {"event", "activity", "activity_type"}


def normalize_clarification_payload(payload: Any) -> dict:
    """Normalize an LLM clarification JSON payload into a client-safe shape."""
    if not isinstance(payload, dict):
        return {"reply": "", "questions": [], "draft": {}}

    reply = str(payload.get("reply") or "").strip()
    raw_questions = payload.get("questions") if payload.get("needs_clarification", True) else []
    if not isinstance(raw_questions, list):
        raw_questions = []

    questions = []
    for index, raw_question in enumerate(raw_questions):
        question = _normalize_question(raw_question, index)
        if question:
            questions.append(question)

    draft = _sanitize_draft(payload.get("draft"))

    return {
        "reply": reply,
        "questions": questions,
        "draft": draft,
    }


def normalize_conversation_payload(payload: Any) -> dict:
    """Normalize the main conversation orchestrator JSON into a safe shape."""
    if not isinstance(payload, dict):
        return {"action": "chat", "reply": "", "questions": [], "draft": {}}

    action = str(payload.get("action") or "chat").strip().lower()
    if action not in _CONVERSATION_ACTIONS:
        action = "chat"

    reply = str(payload.get("reply") or "").strip()
    draft = _sanitize_draft(payload.get("draft"))

    raw_questions = payload.get("questions") if action == "clarify" else []
    if not isinstance(raw_questions, list):
        raw_questions = []

    questions = []
    for index, raw_question in enumerate(raw_questions):
        question = _normalize_question(raw_question, index)
        if question:
            questions.append(question)

    return {
        "action": action,
        "reply": reply,
        "questions": questions,
        "draft": draft,
    }


def normalize_draft_payload(payload: Any) -> dict:
    """Normalize LLM draft-generation output into a safe reply plus draft."""
    if not isinstance(payload, dict):
        return {"reply": "", "draft": {}}
    return {
        "reply": str(payload.get("reply") or "").strip(),
        "draft": _sanitize_draft(payload.get("draft")),
    }


def merge_clarification_answers(
    *,
    draft: dict,
    questions: list[dict],
    answers: list[dict],
    user_birth_date: date | None,
    today: date | None = None,
    free_text: str | None = None,
) -> dict:
    """Merge structured card answers into an event draft."""
    merged = deepcopy(draft) if isinstance(draft, dict) else {}
    merged.setdefault("preferences", [])
    merged.setdefault("constraints", [])
    merged.setdefault("clarification_answers", [])

    if not isinstance(answers, list):
        answers = []

    question_by_id = {
        str(question.get("id")): question
        for question in questions
        if isinstance(question, dict) and question.get("id")
    }

    for answer in answers:
        if not isinstance(answer, dict):
            continue
        question_id = str(answer.get("question_id") or "")
        question = question_by_id.get(question_id)
        if not question:
            continue
        merged["clarification_answers"].append(answer)

        if question.get("type") == "age_range":
            _merge_age_answer(
                merged=merged,
                question=question,
                answer=answer,
                user_birth_date=user_birth_date,
                today=today or date.today(),
            )
        else:
            _merge_generic_answer(merged, question, answer)

    free_text = (free_text or "").strip()
    if free_text:
        merged["preferences"].append(free_text)

    return merged


def _normalize_question(raw_question: Any, index: int) -> dict | None:
    if not isinstance(raw_question, dict):
        return None

    title = str(raw_question.get("title") or "").strip()
    raw_options = raw_question.get("options")
    if not title or not isinstance(raw_options, list) or not raw_options:
        return None

    options = []
    for opt_index, raw_option in enumerate(raw_options[:MAX_OPTIONS]):
        option = _normalize_option(raw_option, opt_index)
        if option:
            options.append(option)
    if not options:
        return None

    question_id = str(raw_question.get("id") or f"question_{index + 1}").strip()
    question_type = str(raw_question.get("type") or "single_choice").strip()
    category = str(raw_question.get("category") or "偏好").strip()
    match_filter = raw_question.get("match_filter")
    if match_filter not in {"preference", "hard_filter", None}:
        match_filter = None

    return {
        "id": question_id,
        "type": question_type,
        "title": title,
        "helper_text": str(raw_question.get("helper_text") or "").strip(),
        "category": category,
        "required": bool(raw_question.get("required", False)),
        "allow_custom": bool(raw_question.get("allow_custom", True)),
        "match_filter": match_filter,
        "options": options,
        "default_option_ids": _normalize_default_option_ids(
            raw_question.get("default_option_ids"),
            options,
        ),
    }


def _sanitize_draft(raw_draft: Any) -> dict:
    if not isinstance(raw_draft, dict):
        return {}

    draft: dict[str, Any] = {}
    for field in _DRAFT_STRING_FIELDS:
        value = _clean_string(raw_draft.get(field))
        if value:
            draft[field] = value

    legacy_city = _clean_string(raw_draft.get("city"))
    if "location" not in draft and legacy_city:
        draft["location"] = legacy_city

    for field in _DRAFT_LIST_FIELDS:
        if field in raw_draft:
            draft[field] = _clean_string_list(raw_draft.get(field))

    age_min = _safe_int(raw_draft.get("age_filter_min"))
    age_max = _safe_int(raw_draft.get("age_filter_max"))
    if age_min is not None and age_max is not None:
        if age_min > age_max:
            age_min, age_max = age_max, age_min
        draft["age_filter_min"] = age_min
        draft["age_filter_max"] = age_max
        mode = _clean_string(raw_draft.get("age_filter_mode")) or "preference"
        draft["age_filter_mode"] = mode if mode in _AGE_FILTER_MODE_VALUES else "preference"

    _remove_place_labels_from_lists(
        draft,
        _place_labels_for_cleanup(draft.get("location"), legacy_city),
    )

    return draft


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_string(item)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _normalize_option(raw_option: Any, index: int) -> dict | None:
    if not isinstance(raw_option, dict):
        return None
    label = str(raw_option.get("label") or "").strip()
    if not label:
        return None
    option_id = str(raw_option.get("id") or f"option_{index + 1}").strip()
    return {
        "id": option_id,
        "label": label,
        "value": raw_option.get("value"),
    }


def _normalize_default_option_ids(value: Any, options: list[dict]) -> list[str]:
    if not isinstance(value, list):
        return []
    valid_ids = {str(option.get("id")) for option in options if option.get("id")}
    result: list[str] = []
    for item in value:
        option_id = str(item).strip()
        if option_id in valid_ids and option_id not in result:
            result.append(option_id)
    return result


def _merge_generic_answer(merged: dict, question: dict, answer: dict) -> None:
    option_ids = answer.get("option_ids")
    if not isinstance(option_ids, list):
        option_ids = []

    options = {
        str(option.get("id")): option
        for option in question.get("options", [])
        if isinstance(option, dict)
    }
    labels = []
    for option_id in option_ids:
        option = options.get(str(option_id))
        if not option:
            continue
        value = option.get("value")
        if isinstance(value, dict):
            _apply_draft_value(merged, value)
            continue
        if isinstance(value, str) and value.strip():
            labels.append(value.strip())
            continue
        label = str(option.get("label") or "").strip()
        if label:
            labels.append(label)

    custom_value = answer.get("custom_value")
    if isinstance(custom_value, dict):
        _apply_draft_value(merged, custom_value)
    elif isinstance(custom_value, str) and custom_value.strip():
        labels.append(custom_value.strip())

    if _is_event_question(question):
        activity_type = "、".join(dict.fromkeys(labels)).strip()
        if activity_type:
            merged["activity_type"] = activity_type
        return

    if _is_location_question(question):
        location = "、".join(dict.fromkeys(labels)).strip()
        if location:
            merged["location"] = location
            _remove_place_labels_from_lists(merged, labels)
        return

    target = "constraints" if question.get("match_filter") == "hard_filter" else "preferences"
    for label in labels:
        if label not in merged[target]:
            merged[target].append(label)


def _apply_draft_value(merged: dict, value: dict) -> None:
    for field in _DRAFT_STRING_FIELDS:
        text = _clean_string(value.get(field))
        if text:
            merged[field] = text
    for field in _DRAFT_LIST_FIELDS:
        additions = _clean_string_list(value.get(field))
        if additions:
            merged.setdefault(field, [])
            for item in additions:
                if item not in merged[field]:
                    merged[field].append(item)
    _remove_place_labels_from_lists(
        merged,
        _place_labels_for_cleanup(value.get("location")),
    )


def _is_event_question(question: dict) -> bool:
    question_id = str(question.get("id") or "").strip().lower()
    if question_id in _EVENT_QUESTION_IDS:
        return True
    title = str(question.get("title") or "").strip()
    category = str(question.get("category") or "").strip()
    text = f"{category} {title}"
    return any(keyword in text for keyword in ("事件", "活动", "想做什么", "项目"))


def _is_location_question(question: dict) -> bool:
    question_id = str(question.get("id") or "").strip().lower()
    if question_id in _LOCATION_QUESTION_IDS:
        return True

    category = str(question.get("category") or "").strip()
    title = str(question.get("title") or "").strip()
    text = f"{category} {title}"
    return any(keyword in text for keyword in ("地点", "位置", "城市", "区域", "哪片区", "哪里", "在哪"))


def _place_labels_for_cleanup(*values: Any) -> list[str]:
    labels: list[str] = []
    for value in values:
        text = _clean_string(value)
        if text and text not in labels:
            labels.append(text)
    return labels


def _remove_place_labels_from_lists(draft: dict, labels: list[str]) -> None:
    if not labels:
        return
    label_set = {label.strip() for label in labels if label.strip()}
    if not label_set:
        return
    for field in _DRAFT_LIST_FIELDS:
        values = draft.get(field)
        if isinstance(values, list):
            draft[field] = [item for item in values if item not in label_set]


def _merge_age_answer(
    *,
    merged: dict,
    question: dict,
    answer: dict,
    user_birth_date: date | None,
    today: date,
) -> None:
    age_min: int | None = None
    age_max: int | None = None
    mode = question.get("match_filter") or "preference"
    if mode not in {"preference", "hard_filter"}:
        mode = "preference"

    custom = answer.get("custom_value")
    if isinstance(custom, dict):
        age_min = _safe_int(custom.get("min_age"))
        age_max = _safe_int(custom.get("max_age"))

    if age_min is None or age_max is None:
        option_ids = answer.get("option_ids")
        if not isinstance(option_ids, list):
            option_ids = []
        options = {
            str(option.get("id")): option
            for option in question.get("options", [])
            if isinstance(option, dict)
        }
        for option_id in option_ids:
            option = options.get(str(option_id))
            if not option:
                continue
            value = option.get("value")
            label = str(option.get("label") or "")
            if value is None or "不限制" in label:
                return
            if isinstance(value, dict) and _safe_int(value.get("range")) is not None and user_birth_date:
                user_age = age_on_date(user_birth_date, today)
                radius = _safe_int(value.get("range")) or 0
                age_min = max(18, user_age - radius)
                age_max = user_age + radius
                break

    if age_min is None or age_max is None:
        return
    if age_min > age_max:
        age_min, age_max = age_max, age_min

    merged["age_filter_min"] = age_min
    merged["age_filter_max"] = age_max
    merged["age_filter_mode"] = mode

    label = f"年龄范围 {age_min}-{age_max} 岁"
    if mode == "hard_filter":
        if label not in merged["constraints"]:
            merged["constraints"].append(label)
    else:
        pref = f"年龄偏好 {age_min}-{age_max} 岁"
        if pref not in merged["preferences"]:
            merged["preferences"].append(pref)


def age_on_date(birth_date: date, today: date) -> int:
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
