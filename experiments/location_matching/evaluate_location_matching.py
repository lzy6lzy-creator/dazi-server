#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = ROOT / "location_eval_cases.json"

STRICTNESS_LEVEL = {
    "none": 0,
    "loose": 1,
    "medium": 2,
    "strict": 3,
}

ACTIVITY_STRICTNESS = {
    "吃饭": "strict",
    "喝茶": "strict",
    "咖啡": "strict",
    "喝咖啡": "strict",
    "酒吧": "strict",
    "看展": "strict",
    "健身": "strict",
    "运动": "strict",
    "看电影": "medium",
    "电影": "medium",
    "桌游": "medium",
    "city walk": "medium",
    "散步": "medium",
    "逛街": "medium",
    "公园": "medium",
    "露营": "loose",
    "徒步": "loose",
    "爬山": "loose",
    "自驾": "loose",
    "旅行": "loose",
    "周边游": "loose",
    "泡温泉": "loose",
    "线上聊天": "none",
    "闲聊": "none",
    "游戏": "none",
}

CITY_ALIASES = {
    "上海": "上海",
    "上海市": "上海",
    "魔都": "上海",
    "北京": "北京",
    "北京市": "北京",
    "帝都": "北京",
    "广州": "广州",
    "广州市": "广州",
    "羊城": "广州",
    "深圳": "深圳",
    "深圳市": "深圳",
    "鹏城": "深圳",
    "成都": "成都",
    "成都市": "成都",
    "蓉城": "成都",
    "杭州": "杭州",
    "杭州市": "杭州",
    "南京": "南京",
    "南京市": "南京",
    "苏州": "苏州",
    "苏州市": "苏州",
    "天津": "天津",
    "天津市": "天津",
    "厦门": "厦门",
    "厦门市": "厦门",
    "香港": "香港",
    "台北": "台北",
    "台北市": "台北",
    "新加坡": "新加坡",
    "东京": "东京",
    "京都": "京都",
    "大理": "大理",
    "佛山": "佛山",
}

CITY_REGION = {
    "上海": "长三角",
    "杭州": "长三角",
    "南京": "长三角",
    "苏州": "长三角",
    "北京": "京津冀",
    "天津": "京津冀",
    "广州": "珠三角",
    "深圳": "珠三角",
    "佛山": "珠三角",
    "香港": "港澳",
    "台北": "台湾",
    "新加坡": "新加坡",
    "成都": "四川",
    "厦门": "福建",
    "东京": "关东",
    "京都": "关西",
    "大理": "云南",
}

REGIONS = {
    "川西": {
        "aliases": ["川西", "甘孜", "阿坝", "康定", "理塘"],
        "cities": ["成都"],
        "admin_region": "四川",
        "geo_scope": "travel",
        "places": ["四姑娘山", "稻城亚丁"],
    },
    "成都周边": {
        "aliases": ["成都周边", "成都周边山里"],
        "cities": ["成都"],
        "admin_region": "四川",
        "geo_scope": "travel",
        "places": ["川西", "四姑娘山"],
    },
    "江浙沪": {
        "aliases": ["江浙沪"],
        "cities": ["上海", "杭州", "南京", "苏州"],
        "admin_region": "江浙沪",
        "geo_scope": "cross_city",
        "places": ["西湖", "苏州园林"],
    },
    "长三角": {
        "aliases": ["长三角"],
        "cities": ["上海", "杭州", "南京", "苏州"],
        "admin_region": "长三角",
        "geo_scope": "cross_city",
        "places": ["西湖", "苏州园林"],
    },
    "上海周边": {
        "aliases": ["上海周边"],
        "cities": ["上海", "杭州", "苏州", "南京"],
        "admin_region": "长三角",
        "geo_scope": "cross_city",
        "places": ["苏州园林", "西湖"],
    },
    "珠三角": {
        "aliases": ["珠三角"],
        "cities": ["广州", "深圳", "佛山", "香港"],
        "admin_region": "珠三角",
        "geo_scope": "cross_city",
        "places": ["大鹏", "岭南天地"],
    },
    "粤港澳大湾区": {
        "aliases": ["粤港澳大湾区", "大湾区"],
        "cities": ["广州", "深圳", "佛山", "香港"],
        "admin_region": "珠三角",
        "geo_scope": "cross_city",
        "places": ["大鹏", "岭南天地"],
    },
    "京津冀": {
        "aliases": ["京津冀"],
        "cities": ["北京", "天津"],
        "admin_region": "京津冀",
        "geo_scope": "cross_city",
        "places": ["蓟州"],
    },
    "东京周边": {
        "aliases": ["东京周边", "关东"],
        "cities": ["东京"],
        "admin_region": "关东",
        "geo_scope": "travel",
        "places": ["箱根"],
    },
    "关西": {
        "aliases": ["关西"],
        "cities": ["京都"],
        "admin_region": "关西",
        "geo_scope": "travel",
        "places": ["岚山"],
    },
}

PLACES = {
    "浦东": {"aliases": ["浦东", "浦东新区", "陆家嘴"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "武康路": {"aliases": ["武康路"], "kind": "landmark", "city": "上海", "region": "长三角"},
    "静安": {"aliases": ["静安", "静安区"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "朝阳": {"aliases": ["朝阳", "朝阳区"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "北京环球影城": {"aliases": ["环球影城", "北京环球影城"], "kind": "venue", "city": "北京", "region": "京津冀"},
    "通州": {"aliases": ["通州", "通州区"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "西湖": {"aliases": ["西湖"], "kind": "landmark", "city": "杭州", "region": "长三角"},
    "新街口": {"aliases": ["新街口"], "kind": "neighborhood", "city": "南京", "region": "长三角"},
    "苏州园林": {"aliases": ["苏州园林"], "kind": "landmark", "city": "苏州", "region": "长三角"},
    "南山": {"aliases": ["南山", "南山区"], "kind": "neighborhood", "city": "深圳", "region": "珠三角"},
    "天河": {"aliases": ["天河", "天河区"], "kind": "neighborhood", "city": "广州", "region": "珠三角"},
    "岭南天地": {"aliases": ["岭南天地"], "kind": "landmark", "city": "佛山", "region": "珠三角"},
    "大鹏": {"aliases": ["大鹏"], "kind": "landmark", "city": "深圳", "region": "珠三角"},
    "中环": {"aliases": ["中环"], "kind": "neighborhood", "city": "香港", "region": "港澳"},
    "铜锣湾": {"aliases": ["铜锣湾"], "kind": "neighborhood", "city": "香港", "region": "港澳"},
    "牛车水": {"aliases": ["牛车水"], "kind": "neighborhood", "city": "新加坡", "region": "新加坡"},
    "乌节路": {"aliases": ["乌节路"], "kind": "neighborhood", "city": "新加坡", "region": "新加坡"},
    "鼓浪屿": {"aliases": ["鼓浪屿"], "kind": "landmark", "city": "厦门", "region": "福建"},
    "曾厝垵": {"aliases": ["曾厝垵"], "kind": "neighborhood", "city": "厦门", "region": "福建"},
    "太古里": {"aliases": ["太古里"], "kind": "neighborhood", "city": "成都", "region": "四川"},
    "四姑娘山": {"aliases": ["四姑娘山"], "kind": "landmark", "city": None, "region": "四川"},
    "稻城亚丁": {"aliases": ["稻城亚丁"], "kind": "landmark", "city": None, "region": "四川"},
    "箱根": {"aliases": ["箱根"], "kind": "landmark", "city": None, "region": "关东"},
    "新宿": {"aliases": ["新宿"], "kind": "neighborhood", "city": "东京", "region": "关东"},
    "岚山": {"aliases": ["岚山"], "kind": "landmark", "city": "京都", "region": "关西"},
    "洱海": {"aliases": ["洱海", "大理洱海"], "kind": "landmark", "city": "大理", "region": "云南"},
    "蓟州": {"aliases": ["蓟州"], "kind": "landmark", "city": "天津", "region": "京津冀"},
    "滨海": {"aliases": ["滨海", "滨海新区"], "kind": "neighborhood", "city": "天津", "region": "京津冀"},
}


@dataclass(frozen=True)
class PlaceProfile:
    place_raw: str
    place_kind: str
    place_normalized: str | None
    admin_city: str | None
    admin_region: str | None
    geo_scope: str
    aliases: tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class MatchDecision:
    should_pass: bool
    score: float
    relation: str
    threshold: float
    source: PlaceProfile
    target: PlaceProfile


def compact_text(*values: str | None) -> str:
    return " ".join(str(value).strip() for value in values if value and str(value).strip())


def normalize_suffix(text: str) -> str:
    value = text.strip()
    for suffix in ["新区", "市", "区", "县"]:
        if value.endswith(suffix) and len(value) > len(suffix) + 1:
            value = value[: -len(suffix)]
    return value


def activity_strictness(activity_type: str | None) -> str:
    raw = (activity_type or "").strip().lower()
    for key, strictness in ACTIVITY_STRICTNESS.items():
        if key.lower() in raw:
            return strictness
    return "medium"


def combined_strictness(a: str | None, b: str | None = None) -> str:
    values = [activity_strictness(a)]
    if b is not None:
        values.append(activity_strictness(b))
    return max(values, key=lambda item: STRICTNESS_LEVEL[item])


def _find_city(text: str) -> str | None:
    normalized = normalize_suffix(text)
    for alias, city in sorted(CITY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in text or alias == normalized:
            return city
    return None


def _region_aliases(region_name: str) -> tuple[str, ...]:
    region = REGIONS[region_name]
    return tuple(dict.fromkeys(region["aliases"] + region["cities"] + region["places"]))


def _find_region(text: str) -> str | None:
    for name, data in sorted(REGIONS.items(), key=lambda item: max(len(a) for a in item[1]["aliases"]), reverse=True):
        if any(alias in text for alias in data["aliases"]):
            return name
    return None


def _find_place(text: str) -> str | None:
    for name, data in sorted(PLACES.items(), key=lambda item: max(len(a) for a in item[1]["aliases"]), reverse=True):
        if any(alias in text for alias in data["aliases"]):
            return name
    return None


def hybrid_parse(activity_type: str | None, city: str | None, location: str | None) -> PlaceProfile:
    raw = compact_text(city, location)
    if not raw:
        return PlaceProfile("", "unknown", None, None, None, "unknown", confidence=0.0)

    if any(token in raw for token in ["线上", "远程", "视频"]):
        return PlaceProfile(raw, "online", "线上", None, None, "none", ("线上", "远程"), 1.0)
    if any(token in raw for token in ["不限地点", "不限", "都可以", "随意"]):
        return PlaceProfile(raw, "flexible", "不限地点", None, None, "none", ("不限地点",), 0.95)

    region_name = _find_region(raw)
    if region_name:
        region = REGIONS[region_name]
        city_hint = _find_city(city or raw)
        admin_city = city_hint if region_name in {"成都周边", "上海周边", "东京周边"} else None
        return PlaceProfile(
            raw,
            "region",
            region_name,
            admin_city,
            str(region["admin_region"]),
            str(region["geo_scope"]),
            _region_aliases(region_name),
            0.95,
        )

    place_name = _find_place(raw)
    if place_name:
        place = PLACES[place_name]
        admin_city = place["city"] or _find_city(city or "")
        admin_region = str(place["region"])
        return PlaceProfile(
            raw,
            str(place["kind"]),
            place_name,
            admin_city,
            admin_region,
            "travel" if place["city"] is None or (activity_strictness(activity_type) == "loose" and not _find_city(city or "")) else "local",
            tuple(place["aliases"]),
            0.9,
        )

    city_name = _find_city(raw)
    if city_name:
        return PlaceProfile(
            raw,
            "city",
            city_name,
            city_name,
            CITY_REGION.get(city_name),
            "city",
            (city_name,),
            0.85,
        )

    normalized = normalize_suffix(location or city or raw)
    return PlaceProfile(raw, "unknown", normalized, None, None, "unknown", (normalized,), 0.25)


def legacy_city_parse(activity_type: str | None, city: str | None, location: str | None) -> PlaceProfile:
    city_name = _find_city(city or "")
    raw = compact_text(city, location)
    return PlaceProfile(
        raw,
        "city" if city_name else "unknown",
        city_name,
        city_name,
        CITY_REGION.get(city_name) if city_name else None,
        "city" if city_name else "unknown",
        (city_name,) if city_name else (),
        0.8 if city_name else 0.0,
    )


def city_in_region(city: str | None, region_name: str | None) -> bool:
    if not city or not region_name:
        return False
    if region_name in REGIONS and city in REGIONS[region_name]["cities"]:
        return True
    if region_name in {"江浙沪", "长三角"} and city in {"上海", "杭州", "南京", "苏州"}:
        return True
    if region_name == "珠三角" and city in {"广州", "深圳", "佛山", "香港"}:
        return True
    if region_name == "京津冀" and city in {"北京", "天津"}:
        return True
    return False


def profile_compatible(source: PlaceProfile, target: PlaceProfile, strictness: str) -> tuple[float, str]:
    if source.place_kind == "online" or target.place_kind == "online":
        return 1.0, "online"
    if source.place_kind == "flexible" or target.place_kind == "flexible":
        return 0.75, "flexible"
    if source.place_normalized and source.place_normalized == target.place_normalized:
        return 1.0, "same_place"
    if source.admin_city and source.admin_city == target.admin_city:
        return 0.85, "same_city"

    source_region = source.place_normalized if source.place_kind == "region" else source.admin_region
    target_region = target.place_normalized if target.place_kind == "region" else target.admin_region

    if strictness == "strict" and (
        source.geo_scope in {"travel", "cross_city", "regional"}
        or target.geo_scope in {"travel", "cross_city", "regional"}
    ):
        return 0.4, "strict_cross_city"

    if city_in_region(target.admin_city, source.place_normalized) and source.place_kind == "region":
        return 0.75, "city_in_region"
    if city_in_region(source.admin_city, target.place_normalized) and target.place_kind == "region":
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


def threshold_for(strictness: str) -> float:
    return {
        "none": 0.0,
        "loose": 0.35,
        "medium": 0.35,
        "strict": 0.6,
    }[strictness]


def hybrid_decide(source: dict[str, Any], target: dict[str, Any]) -> MatchDecision:
    source_profile = hybrid_parse(source.get("activity_type"), source.get("city"), source.get("location"))
    target_profile = hybrid_parse(target.get("activity_type"), target.get("city"), target.get("location"))
    strictness = combined_strictness(source.get("activity_type"), target.get("activity_type"))
    score, relation = profile_compatible(source_profile, target_profile, strictness)
    threshold = threshold_for(strictness)
    return MatchDecision(score >= threshold, score, relation, threshold, source_profile, target_profile)


def legacy_city_decide(source: dict[str, Any], target: dict[str, Any]) -> MatchDecision:
    source_profile = legacy_city_parse(source.get("activity_type"), source.get("city"), source.get("location"))
    target_profile = legacy_city_parse(target.get("activity_type"), target.get("city"), target.get("location"))
    if not source_profile.admin_city:
        score, relation = 0.3, "source_city_unknown"
    elif not target_profile.admin_city:
        score, relation = 0.3, "target_city_unknown"
    elif source_profile.admin_city == target_profile.admin_city:
        score, relation = 0.85, "same_city"
    else:
        score, relation = 0.0, "conflict"
    return MatchDecision(score > 0.0, score, relation, 0.01, source_profile, target_profile)


def char_ngrams(text: str, n: int = 2) -> Counter[str]:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return Counter()
    if len(compact) <= n:
        return Counter([compact])
    return Counter(compact[i:i + n] for i in range(len(compact) - n + 1))


def cosine_counter(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(key, 0) for key, value in a.items())
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def text_vector_decide(source: dict[str, Any], target: dict[str, Any]) -> MatchDecision:
    source_text = compact_text(source.get("activity_type"), source.get("city"), source.get("location"))
    target_text = compact_text(target.get("activity_type"), target.get("city"), target.get("location"))
    score = cosine_counter(char_ngrams(source_text), char_ngrams(target_text))
    strictness = combined_strictness(source.get("activity_type"), target.get("activity_type"))
    threshold = {
        "none": 0.05,
        "loose": 0.12,
        "medium": 0.16,
        "strict": 0.22,
    }[strictness]
    placeholder = PlaceProfile("", "unknown", None, None, None, "unknown")
    return MatchDecision(score >= threshold, score, "text_similarity", threshold, placeholder, placeholder)


def parse_metrics(cases: list[dict[str, Any]], parser) -> dict[str, Any]:
    fields = ["place_kind", "place_normalized", "admin_city", "admin_region", "geo_scope"]
    field_hits = Counter()
    misses = []
    for case in cases:
        expected = case["expected"]
        actual = parser(case.get("activity_type"), case.get("city"), case.get("location"))
        actual_dict = asdict(actual)
        exact = True
        for field in fields:
            if actual_dict[field] == expected.get(field):
                field_hits[field] += 1
            else:
                exact = False
        if exact:
            field_hits["exact"] += 1
        else:
            misses.append({
                "id": case["id"],
                "input": {k: case.get(k) for k in ["activity_type", "city", "location"]},
                "expected": expected,
                "actual": {field: actual_dict[field] for field in fields},
            })
    total = len(cases)
    return {
        "total": total,
        "field_accuracy": {field: round(field_hits[field] / total, 4) for field in fields},
        "exact_accuracy": round(field_hits["exact"] / total, 4),
        "misses": misses,
    }


def decision_metrics(cases: list[dict[str, Any]], decide) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    mistakes = []
    for case in cases:
        expected = bool(case["expected"]["should_pass"])
        decision = decide(case["source"], case["target"])
        actual = bool(decision.should_pass)
        if expected and actual:
            tp += 1
        elif expected and not actual:
            fn += 1
        elif not expected and actual:
            fp += 1
        else:
            tn += 1
        if expected != actual:
            mistakes.append({
                "id": case["id"],
                "expected": case["expected"],
                "actual": {
                    "should_pass": decision.should_pass,
                    "score": round(decision.score, 4),
                    "relation": decision.relation,
                    "threshold": decision.threshold,
                },
                "source": case["source"],
                "target": case["target"],
            })
    total = len(cases)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "total": total,
        "accuracy": round((tp + tn) / total, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "mistakes": mistakes,
    }


def run_eval(cases_path: Path) -> dict[str, Any]:
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    parse_cases = data["parse_cases"]
    match_cases = data["match_cases"]
    return {
        "parse": {
            "legacy_city_only": parse_metrics(parse_cases, legacy_city_parse),
            "hybrid_rule_region": parse_metrics(parse_cases, hybrid_parse),
        },
        "match": {
            "legacy_city_only": decision_metrics(match_cases, legacy_city_decide),
            "full_text_ngram_vector": decision_metrics(match_cases, text_vector_decide),
            "hybrid_rule_region": decision_metrics(match_cases, hybrid_decide),
        },
    }


def sentence_transformer_metrics(match_cases: list[dict[str, Any]], model_name: str) -> dict[str, Any]:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model = SentenceTransformer(model_name)
    texts = []
    for case in match_cases:
        texts.append(compact_text(case["source"].get("activity_type"), case["source"].get("city"), case["source"].get("location")))
        texts.append(compact_text(case["target"].get("activity_type"), case["target"].get("city"), case["target"].get("location")))
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=16)

    scores = []
    for index, case in enumerate(match_cases):
        source_vec = vecs[index * 2]
        target_vec = vecs[index * 2 + 1]
        scores.append(float(np.dot(source_vec, target_vec)))

    best = None
    for threshold_int in range(0, 101):
        threshold = threshold_int / 100
        tp = fp = tn = fn = 0
        mistakes = []
        for case, score in zip(match_cases, scores):
            expected = bool(case["expected"]["should_pass"])
            actual = score >= threshold
            if expected and actual:
                tp += 1
            elif expected and not actual:
                fn += 1
            elif not expected and actual:
                fp += 1
            else:
                tn += 1
            if expected != actual:
                mistakes.append({
                    "id": case["id"],
                    "score": round(score, 4),
                    "threshold": threshold,
                    "expected": case["expected"],
                    "source": case["source"],
                    "target": case["target"],
                })

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics = {
            "total": len(match_cases),
            "accuracy": round((tp + tn) / len(match_cases), 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "threshold": threshold,
            "mistakes": mistakes,
        }
        if best is None or (metrics["f1"], metrics["accuracy"]) > (best["f1"], best["accuracy"]):
            best = metrics

    return best or {}


def print_summary(results: dict[str, Any], show_mistakes: bool) -> None:
    print("Parse metrics")
    print("strategy                 exact   kind    place   city    region  scope")
    for name, metrics in results["parse"].items():
        fields = metrics["field_accuracy"]
        print(
            f"{name:<24} {metrics['exact_accuracy']:<7.4f} "
            f"{fields['place_kind']:<7.4f} {fields['place_normalized']:<7.4f} "
            f"{fields['admin_city']:<7.4f} {fields['admin_region']:<7.4f} {fields['geo_scope']:<7.4f}"
        )

    print("\nMatch decision metrics")
    print("strategy                 acc     precision recall  f1      fp fn")
    for name, metrics in results["match"].items():
        print(
            f"{name:<24} {metrics['accuracy']:<7.4f} {metrics['precision']:<9.4f} "
            f"{metrics['recall']:<7.4f} {metrics['f1']:<7.4f} {metrics['fp']:<2} {metrics['fn']:<2}"
        )
    if results.get("sentence_transformer_match"):
        metrics = results["sentence_transformer_match"]
        print(
            f"{'sentence_transformer':<24} {metrics['accuracy']:<7.4f} {metrics['precision']:<9.4f} "
            f"{metrics['recall']:<7.4f} {metrics['f1']:<7.4f} {metrics['fp']:<2} {metrics['fn']:<2} "
            f"best_threshold={metrics['threshold']:.2f}"
        )

    if show_mistakes:
        for section in ["parse", "match"]:
            for name, metrics in results[section].items():
                mistakes = metrics["misses"] if section == "parse" else metrics["mistakes"]
                if not mistakes:
                    continue
                print(f"\n{section} mistakes: {name}")
                for item in mistakes[:12]:
                    print(json.dumps(item, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--show-mistakes", action="store_true")
    parser.add_argument("--include-sentence-transformer", action="store_true")
    parser.add_argument("--st-model", default="BAAI/bge-base-zh-v1.5")
    args = parser.parse_args()

    results = run_eval(args.cases)
    if args.include_sentence_transformer:
        data = json.loads(args.cases.read_text(encoding="utf-8"))
        results["sentence_transformer_match"] = sentence_transformer_metrics(data["match_cases"], args.st_model)
    print_summary(results, args.show_mistakes)
    if args.json_output:
        args.json_output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_output}")


if __name__ == "__main__":
    main()
