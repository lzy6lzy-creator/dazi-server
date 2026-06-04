#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = ROOT / "event_location_vector_cases.json"
DEFAULT_CACHE = ROOT / "kimi_event_location_cache.json"

CITY_ALIASES = {
    "上海": "上海",
    "上海市": "上海",
    "魔都": "上海",
    "北京": "北京",
    "北京市": "北京",
    "帝都": "北京",
    "广州": "广州",
    "广州市": "广州",
    "深圳": "深圳",
    "深圳市": "深圳",
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

CITY_GROUPS = {
    "长三角": {"上海", "杭州", "南京", "苏州"},
    "江浙沪": {"上海", "杭州", "南京", "苏州"},
    "上海周边": {"上海", "杭州", "南京", "苏州"},
    "珠三角": {"广州", "深圳", "佛山", "香港"},
    "粤港澳大湾区": {"广州", "深圳", "佛山", "香港"},
    "大湾区": {"广州", "深圳", "佛山", "香港"},
    "京津冀": {"北京", "天津"},
    "川西": {"成都"},
    "成都周边": {"成都"},
    "东京周边": {"东京"},
    "关西": {"京都"},
}

LOCATION_EXPANSIONS = {
    "川西": "川西 四川 成都周边 甘孜 阿坝 康定 四姑娘山 稻城亚丁 徒步 自驾 旅行",
    "成都周边": "成都周边 川西 四川 山里 徒步 露营 四姑娘山",
    "四姑娘山": "四姑娘山 川西 四川 阿坝 小金 徒步 自驾",
    "稻城亚丁": "稻城亚丁 川西 四川 甘孜 旅行 自驾",
    "江浙沪": "江浙沪 长三角 上海 杭州 南京 苏州 西湖 苏州园林 周边游 自驾",
    "长三角": "长三角 江浙沪 上海 杭州 南京 苏州 西湖 苏州园林 周边游 自驾",
    "上海周边": "上海周边 长三角 江浙沪 杭州 苏州 南京 西湖 苏州园林 露营 自驾",
    "珠三角": "珠三角 大湾区 粤港澳大湾区 广州 深圳 佛山 香港 大鹏 岭南天地",
    "粤港澳大湾区": "粤港澳大湾区 大湾区 珠三角 广州 深圳 佛山 香港 大鹏 岭南天地",
    "大湾区": "大湾区 粤港澳大湾区 珠三角 广州 深圳 佛山 香港 大鹏 岭南天地",
    "京津冀": "京津冀 北京 天津 蓟州 通州 周边 自驾 爬山 露营",
    "东京周边": "东京周边 关东 东京 箱根 温泉 旅行",
    "箱根": "箱根 东京周边 关东 温泉 旅行",
    "关西": "关西 京都 大阪 岚山 旅行",
    "岚山": "岚山 京都 关西 旅行",
    "浦东": "浦东 上海 陆家嘴 咖啡",
    "陆家嘴": "陆家嘴 上海 浦东 咖啡",
    "武康路": "武康路 上海 徐汇 city walk brunch 咖啡",
    "静安": "静安 上海 看电影 咖啡",
    "朝阳": "朝阳 北京 看展",
    "环球影城": "环球影城 北京 通州 看电影",
    "北京环球影城": "北京环球影城 环球影城 北京 通州 看电影",
    "通州": "通州 北京 环球影城 看电影",
    "西湖": "西湖 杭州 长三角 江浙沪 散步 旅行",
    "新街口": "新街口 南京 长三角 吃饭",
    "苏州园林": "苏州园林 苏州 长三角 江浙沪 拍照 旅行",
    "南山": "南山 深圳 珠三角 健身",
    "天河": "天河 广州 珠三角 喝茶 吃饭",
    "岭南天地": "岭南天地 佛山 珠三角 喝茶",
    "大鹏": "大鹏 深圳 珠三角 露营",
    "中环": "中环 香港 港岛 酒吧 逛街",
    "铜锣湾": "铜锣湾 香港 逛街",
    "牛车水": "牛车水 新加坡 吃饭",
    "乌节路": "乌节路 新加坡 逛街",
    "鼓浪屿": "鼓浪屿 厦门 福建 旅行",
    "曾厝垵": "曾厝垵 厦门 福建 逛吃",
    "太古里": "太古里 成都 春熙路 吃饭 咖啡",
    "洱海": "洱海 大理 云南 旅行",
    "蓟州": "蓟州 天津 京津冀 爬山",
}

BROAD_LOCATION_TOKENS = {
    "川西",
    "成都周边",
    "江浙沪",
    "长三角",
    "上海周边",
    "珠三角",
    "粤港澳大湾区",
    "大湾区",
    "京津冀",
    "东京周边",
    "关西",
}

STRICT_ACTIVITY_TOKENS = {"吃饭", "火锅", "咖啡", "喝咖啡", "喝茶", "酒吧", "看展", "健身", "拉面"}
MEDIUM_ACTIVITY_TOKENS = {"看电影", "电影", "桌游", "city walk", "散步", "逛街", "brunch"}
LOOSE_ACTIVITY_TOKENS = {"徒步", "旅行", "自驾", "周边游", "露营", "爬山", "温泉", "拍照", "发呆", "吸氧"}

LOCATION_ONLY_STOP_TOKENS = STRICT_ACTIVITY_TOKENS | MEDIUM_ACTIVITY_TOKENS | LOOSE_ACTIVITY_TOKENS | {
    "喝茶聊天",
    "散步拍照",
    "逛吃",
    "购物",
    "摄影",
    "餐饮",
    "户外",
}

LOCATION_ONLY_REGION_COVERAGE = {
    "川西": {"四川", "甘孜", "阿坝", "康定", "理塘", "四姑娘山", "稻城亚丁"},
    "成都周边": {"川西", "四川", "山里", "四姑娘山", "甘孜", "阿坝"},
    "江浙沪": {"上海", "杭州", "南京", "苏州", "西湖", "苏州园林", "长三角"},
    "长三角": {"上海", "杭州", "南京", "苏州", "西湖", "苏州园林", "江浙沪"},
    "上海周边": {"杭州", "南京", "苏州", "西湖", "苏州园林", "江浙沪", "长三角"},
    "珠三角": {"广州", "深圳", "佛山", "香港", "大鹏", "岭南天地", "粤港澳大湾区", "大湾区"},
    "粤港澳大湾区": {"广州", "深圳", "佛山", "香港", "大鹏", "岭南天地", "珠三角", "大湾区"},
    "大湾区": {"广州", "深圳", "佛山", "香港", "大鹏", "岭南天地", "珠三角", "粤港澳大湾区"},
    "京津冀": {"北京", "天津", "蓟州", "通州"},
    "东京周边": {"关东", "箱根"},
    "关西": {"京都", "大阪", "岚山"},
}

LOCATION_ONLY_CITY_GROUPS = {
    "江浙沪": {"上海", "杭州", "南京", "苏州"},
    "长三角": {"上海", "杭州", "南京", "苏州"},
    "珠三角": {"广州", "深圳", "佛山", "香港"},
    "粤港澳大湾区": {"广州", "深圳", "佛山", "香港"},
    "大湾区": {"广州", "深圳", "佛山", "香港"},
    "京津冀": {"北京", "天津"},
    "关西": {"京都", "大阪"},
}

LOCATION_ALIAS_GROUPS = [
    {"大湾区", "粤港澳大湾区"},
    {"浦东", "浦东新区", "陆家嘴"},
    {"北京环球影城", "环球影城"},
    {"江浙沪", "长三角"},
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "null":
        return ""
    return text


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def extract_json(text: str) -> Any:
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def normalize_compare_text(text: str) -> str:
    value = clean_text(text).lower()
    replacements = {
        "魔都": "上海",
        "蓉城": "成都",
        "大湾区": "粤港澳大湾区",
        "陆家嘴": "浦东",
        "浦东新区": "浦东",
        "朝阳区": "朝阳",
        "南山区": "南山",
        "静安区": "静安",
        "通州区": "通州",
        "大理洱海": "洱海",
        "北京环球影城": "环球影城",
    }
    for source, target in replacements.items():
        value = value.replace(source.lower(), target.lower())
    value = re.sub(r"[\s,，。；;:：/\\|_-]+", "", value)
    for suffix in ["市", "新区", "区", "县"]:
        value = value.replace(suffix, "")
    return value


def merge_event_location(event: dict[str, Any]) -> str:
    city = clean_text(event.get("city"))
    location = clean_text(event.get("location"))
    if location and city and city not in location and location not in {"线上", "不限地点", "地点不限", "不限"}:
        return f"{city} {location}"
    return location or city


def location_matches(actual: str, expected: str, aliases: list[str] | None = None) -> bool:
    actual_norm = normalize_compare_text(actual)
    if not actual_norm:
        return False
    candidates = [expected] + list(aliases or [])
    for candidate in candidates:
        candidate_norm = normalize_compare_text(candidate)
        if not candidate_norm:
            continue
        if actual_norm == candidate_norm:
            return True
        if len(candidate_norm) >= 2 and candidate_norm in actual_norm:
            return True
        if len(actual_norm) >= 2 and actual_norm in candidate_norm:
            return True
    return False


def augment_location_text(location: str) -> str:
    base = clean_text(location)
    if not base:
        return ""
    pieces = [base]
    compact = normalize_compare_text(base)
    for key, expansion in LOCATION_EXPANSIONS.items():
        key_norm = normalize_compare_text(key)
        if key_norm and (key_norm in compact or compact in key_norm):
            pieces.append(expansion)
    for alias, city in CITY_ALIASES.items():
        if normalize_compare_text(alias) in compact:
            pieces.append(city)
    return " ".join(dict.fromkeys(" ".join(pieces).split()))


def location_only_tokens(location: str) -> set[str]:
    text = clean_text(location)
    if not text:
        return set()
    pieces: list[str] = []
    pieces.extend(token for token in re.split(r"[\s,，。；;:：/\\|_-]+", text) if token)
    compact = normalize_compare_text(text)
    for key, expansion in LOCATION_EXPANSIONS.items():
        key_norm = normalize_compare_text(key)
        # Location-only matching must not expand "上海" into "上海周边".
        if key_norm and key_norm in compact:
            pieces.append(key)
            pieces.extend(expansion.split())
    for region, covered in LOCATION_ONLY_REGION_COVERAGE.items():
        if normalize_compare_text(region) in compact:
            pieces.append(region)
            pieces.extend(covered)
    tokens = {
        normalize_compare_text(piece)
        for piece in pieces
        if piece and piece not in LOCATION_ONLY_STOP_TOKENS
    }
    return {token for token in tokens if token and token not in {normalize_compare_text(stop) for stop in LOCATION_ONLY_STOP_TOKENS}}


def augment_location_text_location_only(location: str) -> str:
    base = clean_text(location)
    if not base:
        return ""
    tokens = [base]
    tokens.extend(sorted(location_only_tokens(base), key=lambda token: (-len(token), token)))
    return " ".join(dict.fromkeys(token for token in tokens if token))


def location_alias_score(source_location: str, target_location: str) -> float:
    source = clean_text(source_location)
    target = clean_text(target_location)
    if not source or not target:
        return 0.0
    if "不限" in source or "不限" in target:
        return 1.0
    source_online = any(token in source for token in ["线上", "远程", "视频"])
    target_online = any(token in target for token in ["线上", "远程", "视频"])
    if source_online or target_online:
        return 1.0 if source_online and target_online else 0.0

    source_compact = normalize_compare_text(source)
    target_compact = normalize_compare_text(target)
    for group in LOCATION_ALIAS_GROUPS:
        group_norm = {normalize_compare_text(item) for item in group}
        if any(item and item in source_compact for item in group_norm) and any(item and item in target_compact for item in group_norm):
            return 1.0

    source_norm = normalize_compare_text(source)
    target_norm = normalize_compare_text(target)
    if source_norm == target_norm:
        return 1.0
    if len(source_norm) >= 2 and source_norm in target_norm:
        return 0.9
    if len(target_norm) >= 2 and target_norm in source_norm:
        return 0.9
    return 0.0


def location_containment_score(source_location: str, target_location: str) -> float:
    source = clean_text(source_location)
    target = clean_text(target_location)
    if not source or not target:
        return 0.0
    if "不限" in source or "不限" in target:
        return 1.0
    source_online = any(token in source for token in ["线上", "远程", "视频"])
    target_online = any(token in target for token in ["线上", "远程", "视频"])
    if source_online or target_online:
        return 1.0 if source_online and target_online else 0.0

    source_norm = normalize_compare_text(source)
    target_norm = normalize_compare_text(target)
    source_tokens = location_only_tokens(source)
    target_tokens = location_only_tokens(target)
    source_direct = {
        normalize_compare_text(token)
        for token in re.split(r"[\s,，。；;:：/\\|_-]+", source)
        if token
    }
    target_direct = {
        normalize_compare_text(token)
        for token in re.split(r"[\s,，。；;:：/\\|_-]+", target)
        if token
    }

    for region, covered in LOCATION_ONLY_REGION_COVERAGE.items():
        region_norm = normalize_compare_text(region)
        covered_norm = {normalize_compare_text(item) for item in covered}
        if region_norm in source_norm and (target_direct & covered_norm or target_tokens & covered_norm):
            return 0.88
        if region_norm in target_norm and (source_direct & covered_norm or source_tokens & covered_norm):
            return 0.88

    shared_region_tokens = source_tokens & target_tokens & {
        normalize_compare_text(region) for region in ["川西", "四川"]
    }
    if shared_region_tokens:
        return 0.82
    return 0.0


def location_only_cities(location: str) -> set[str]:
    text = clean_text(location)
    compact = normalize_compare_text(text)
    if not compact:
        return set()

    for region, cities in LOCATION_ONLY_CITY_GROUPS.items():
        if normalize_compare_text(region) in compact:
            return set(cities)

    # Travel "周边" expressions are intentionally not collapsed to their anchor city.
    if any(normalize_compare_text(region) in compact for region in ["川西", "成都周边", "东京周边", "上海周边"]):
        return set()

    cities = set()
    for alias, city in CITY_ALIASES.items():
        if normalize_compare_text(alias) in compact:
            cities.add(city)
    return cities


def location_same_city_score(source_location: str, target_location: str) -> float:
    source_cities = location_only_cities(source_location)
    target_cities = location_only_cities(target_location)
    if source_cities and target_cities and source_cities.intersection(target_cities):
        return 0.78
    return 0.0


def score_location_hybrid_text(source: dict[str, Any], target: dict[str, Any]) -> float:
    source_loc = source["eval_location"]
    target_loc = target["eval_location"]
    return max(
        location_alias_score(source_loc, target_loc),
        location_containment_score(source_loc, target_loc),
        location_same_city_score(source_loc, target_loc),
        char_ngram_similarity(
            augment_location_text_location_only(source_loc),
            augment_location_text_location_only(target_loc),
        ),
    )


def char_ngrams(text: str, n: int = 2) -> Counter[str]:
    compact = normalize_compare_text(text)
    if not compact:
        return Counter()
    if len(compact) <= n:
        return Counter([compact])
    return Counter(compact[index:index + n] for index in range(len(compact) - n + 1))


def cosine_counter(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(key, 0) for key, value in a.items())
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def char_ngram_similarity(source: str, target: str) -> float:
    return cosine_counter(char_ngrams(source), char_ngrams(target))


def activity_strictness(activity_type: str) -> int:
    text = clean_text(activity_type).lower()
    if any(token.lower() in text for token in STRICT_ACTIVITY_TOKENS):
        return 3
    if any(token.lower() in text for token in MEDIUM_ACTIVITY_TOKENS):
        return 2
    if any(token.lower() in text for token in LOOSE_ACTIVITY_TOKENS):
        return 1
    if any(token in text for token in ["线上", "闲聊"]):
        return 0
    return 2


def combined_strictness(source: dict[str, Any], target: dict[str, Any]) -> int:
    return max(activity_strictness(source.get("activity_type", "")), activity_strictness(target.get("activity_type", "")))


def is_online_or_flexible(location: str) -> bool:
    return any(token in clean_text(location) for token in ["线上", "远程", "不限", "地点不限", "都可以"])


def find_city(location: str) -> str | None:
    text = clean_text(location)
    compact = normalize_compare_text(text)
    for alias, city in sorted(CITY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if normalize_compare_text(alias) in compact:
            return city
    for key, expansion in LOCATION_EXPANSIONS.items():
        key_norm = normalize_compare_text(key)
        if key_norm and key_norm in compact:
            for city in CITY_ALIASES.values():
                if city in expansion:
                    return city
    return None


def location_cities(location: str) -> set[str]:
    compact = normalize_compare_text(location)
    cities: set[str] = set()
    for alias, city in CITY_ALIASES.items():
        if normalize_compare_text(alias) in compact:
            cities.add(city)
    for group, group_cities in CITY_GROUPS.items():
        if normalize_compare_text(group) in compact:
            cities.update(group_cities)
    for key, expansion in LOCATION_EXPANSIONS.items():
        key_norm = normalize_compare_text(key)
        if key_norm and key_norm in compact:
            cities.update(city for city in CITY_ALIASES.values() if city in expansion)
    return cities


def has_broad_location(location: str) -> bool:
    compact = normalize_compare_text(location)
    return any(normalize_compare_text(token) in compact for token in BROAD_LOCATION_TOKENS)


def strict_location_gate(source: dict[str, Any], target: dict[str, Any]) -> bool:
    source_loc = source["eval_location"]
    target_loc = target["eval_location"]
    if is_online_or_flexible(source_loc) or is_online_or_flexible(target_loc):
        return True
    if combined_strictness(source, target) < 3:
        return True
    source_city = find_city(source_loc)
    target_city = find_city(target_loc)
    if source_city and target_city and source_city != target_city:
        return False
    if has_broad_location(source_loc) or has_broad_location(target_loc):
        return False
    return True


def best_threshold_metrics(scores: list[float], labels: list[bool]) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for threshold_int in range(0, 101):
        threshold = threshold_int / 100
        tp = fp = tn = fn = 0
        for score, expected in zip(scores, labels):
            actual = score >= threshold
            if expected and actual:
                tp += 1
            elif expected and not actual:
                fn += 1
            elif not expected and actual:
                fp += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics = {
            "threshold": threshold,
            "accuracy": round((tp + tn) / len(labels), 4) if labels else 0.0,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
        }
        if best is None or (metrics["f1"], metrics["accuracy"], metrics["precision"]) > (
            best["f1"],
            best["accuracy"],
            best["precision"],
        ):
            best = metrics
    return best or {}


def load_prompt_builder_default() -> str:
    try:
        from app.services.prompt_builder import PromptBuilder

        return PromptBuilder.build_event_extraction_prompt()
    except Exception:
        return """请从用户口语化描述中提取活动信息，以严格 JSON 返回。
字段：title, activity_type, city, start_time, end_time, location, preferences, constraints。
city 只放明确行政城市；区域/目的地放 location。只返回 JSON。"""


def build_messages(case: dict[str, Any], variant: str) -> list[dict[str, str]]:
    utterance = case["utterance"]
    if variant == "default":
        return [
            {"role": "system", "content": load_prompt_builder_default()},
            {"role": "user", "content": f"user: {utterance}"},
        ]
    if variant == "single_location":
        system = """你是活动需求抽取器。请从用户一句口语化描述中抽取活动 JSON。

字段：
- title: 简短标题
- activity_type: 用户想做的活动，保留口语含义
- location: 单一地点字符串。请把行政城市、商圈、目的地、区域合并到这一个字段，例如 "上海 浦东"、"北京 朝阳"、"川西"、"江浙沪"、"东京周边"、"线上"、"不限地点"。
- city: 如果用户明确说了行政城市可填，否则为 null。注意最终地点匹配只使用 location。
- preferences: 偏好列表
- constraints: 限制列表
- start_time/end_time: 不确定则 null

规则：
- 川西、江浙沪、长三角、珠三角、粤港澳大湾区、京津冀、东京周边、关西放到 location，不要硬改成单个城市。
- 只说城市时 location 就填城市，例如 "上海"。
- 只返回严格 JSON，不要解释。"""
    elif variant == "single_location_fewshot":
        system = """你是活动需求抽取器。请从用户一句口语化描述中抽取活动 JSON。

只需要服务后续地点匹配，所以 location 必须是一个可直接向量化的地点字符串：
{"title":"...","activity_type":"...","city":"城市或null","location":"单一地点字符串或null","start_time":null,"end_time":null,"preferences":[],"constraints":[]}

示例：
用户：周五下班想在上海浦东喝咖啡
输出：{"title":"上海浦东咖啡","activity_type":"咖啡","city":"上海","location":"上海 浦东","start_time":null,"end_time":null,"preferences":[],"constraints":[]}
用户：成都出发去川西徒步
输出：{"title":"川西徒步","activity_type":"徒步","city":"成都","location":"川西","start_time":null,"end_time":null,"preferences":[],"constraints":[]}
用户：江浙沪周边游
输出：{"title":"江浙沪周边游","activity_type":"周边游","city":null,"location":"江浙沪","start_time":null,"end_time":null,"preferences":[],"constraints":[]}

规则：
- location 不要拆成 place_kind/admin_city 等 profile 字段。
- city 只作为辅助字段，地点匹配只使用 location。
- 只返回严格 JSON，不要解释。"""
    elif variant == "single_location_guarded":
        system = """你是活动需求抽取器。请从用户一句口语化描述中抽取活动 JSON。

输出格式固定：
{"title":"...","activity_type":"...","city":"城市或null","location":"单一地点字符串或null","start_time":null,"end_time":null,"preferences":[],"constraints":[]}

location 是后续地点匹配唯一使用的字段，必须遵守：
- 线上/远程/视频活动：location 必须填 "线上"，不要放到 constraints。
- 地点不限/不限地点/都可以/位置再约：location 必须填 "不限地点"，不要放到 constraints。
- 明确城市+地点：合并成一个字符串，例如 "上海 浦东"、"北京 朝阳"、"新加坡 牛车水"。
- 只说城市：location 填城市，例如 "上海"。
- 川西、江浙沪、长三角、珠三角、大湾区、粤港澳大湾区、京津冀、东京周边、关西、成都周边、上海周边：location 填这个区域本身，不要改成单个城市。
- city 只作为辅助字段；如果能明确行政城市就填，否则为 null。

示例：
用户：线上聊天，随便聊聊电影
输出：{"title":"线上聊天","activity_type":"线上聊天","city":null,"location":"线上","start_time":null,"end_time":null,"preferences":["电影"],"constraints":[]}
用户：地点不限，找桌游搭子
输出：{"title":"桌游搭子","activity_type":"桌游","city":null,"location":"不限地点","start_time":null,"end_time":null,"preferences":[],"constraints":[]}
用户：周五下班想在上海浦东喝咖啡
输出：{"title":"上海浦东咖啡","activity_type":"咖啡","city":"上海","location":"上海 浦东","start_time":null,"end_time":null,"preferences":[],"constraints":[]}
用户：成都出发去川西徒步
输出：{"title":"川西徒步","activity_type":"徒步","city":"成都","location":"川西","start_time":null,"end_time":null,"preferences":[],"constraints":[]}

只返回严格 JSON，不要解释。"""
    elif variant == "location_only_guarded":
        system = """你是地点抽取器。请从用户一句口语化活动需求中只抽取后续地点匹配需要的 location。

输出格式固定：
{"location":"单一地点字符串或null"}

location 规则：
- 只输出地点，不输出 activity_type、title、city、preferences、constraints。
- 明确城市+区/商圈/地标：合并为一个字符串，例如 "上海 浦东"、"北京 朝阳"、"新加坡 牛车水"。
- 只说城市：输出城市，例如 "上海"。
- 城市明确但具体地点再约/位置再定：保留城市，例如 "台北周末桌游，地点可以再约" 输出 "台北"。
- 地点不限/不限地点/哪里都行，且没有明确城市：输出 "不限地点"。
- 线上/远程/视频：输出 "线上"。
- 川西、江浙沪、长三角、珠三角、大湾区、粤港澳大湾区、京津冀、东京周边、关西、成都周边、上海周边：输出这个区域本身。
- 如果用户说“成都出发去川西”“广州出发珠三角”，最终 location 输出目的地/区域，例如 "川西"、"珠三角"，不要把出发城市拼进去。

示例：
用户：周五下班想在上海浦东喝咖啡
输出：{"location":"上海 浦东"}
用户：成都出发去川西徒步
输出：{"location":"川西"}
用户：线上聊天，随便聊聊电影
输出：{"location":"线上"}
用户：地点不限，找桌游搭子
输出：{"location":"不限地点"}
用户：台北周末桌游，地点可以再约
输出：{"location":"台北"}

只返回严格 JSON，不要解释。"""
    else:
        raise ValueError(f"unknown prompt variant: {variant}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": utterance},
    ]


def call_kimi(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    retries: int,
    delay: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.6 if "k2" in model else 0.2,
        "max_tokens": 768,
    }
    if "k2" in model:
        payload["thinking"] = {"type": "disabled"}

    last_error = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"].get("content") or ""
            parsed = extract_json(content)
            return {"ok": isinstance(parsed, dict), "parsed": parsed, "raw": content}
        except urllib.error.HTTPError as exc:
            last_error = exc.read().decode("utf-8")[:500]
            if exc.code == 429 or exc.code >= 500:
                wait = min(60.0, max(delay, (2 ** attempt) + delay))
                print(f"[warn] Kimi HTTP {exc.code}, retry {attempt + 1}/{retries} after {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            return {"ok": False, "parsed": None, "raw": "", "error": f"HTTP {exc.code}: {last_error}"}
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            wait = min(60.0, max(delay, (2 ** attempt) + delay))
            print(f"[warn] Kimi network error: {last_error}, retry {attempt + 1}/{retries} after {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
    return {"ok": False, "parsed": None, "raw": "", "error": last_error or "request failed"}


def ensure_kimi_outputs(
    cases: list[dict[str, Any]],
    variants: list[str],
    cache_path: Path,
    env_path: Path,
    delay: float,
    retries: int,
    limit: int,
) -> dict[str, dict[str, Any]]:
    env_values = {**parse_env(env_path), **os.environ}
    api_key = env_values.get("LLM_API_KEY", "")
    base_url = env_values.get("LLM_BASE_URL", "https://api.moonshot.cn/v1")
    model = env_values.get("LLM_MODEL", "kimi-k2.5")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required for --call-kimi")

    cache: dict[str, dict[str, Any]] = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    selected_cases = cases[:limit] if limit else cases
    for variant in variants:
        cache.setdefault(variant, {})
        for index, case in enumerate(selected_cases, start=1):
            cached = cache[variant].get(case["id"])
            if isinstance(cached, dict) and cached.get("ok") is True:
                continue
            print(f"[kimi] {variant} {index}/{len(selected_cases)} {case['id']}")
            result = call_kimi(base_url, api_key, model, build_messages(case, variant), retries=retries, delay=delay)
            cache[variant][case["id"]] = result
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(max(0.0, delay))
    return cache


def evaluate_extraction(events: list[dict[str, Any]], outputs: dict[str, Any]) -> dict[str, Any]:
    misses = []
    valid_json = 0
    location_hits = 0
    non_empty_locations = 0
    for event in events:
        result = outputs.get(event["id"]) or {}
        parsed = result.get("parsed") if isinstance(result, dict) else None
        if isinstance(parsed, dict):
            valid_json += 1
        actual_location = merge_event_location(parsed or {})
        if actual_location:
            non_empty_locations += 1
        hit = location_matches(actual_location, event["expected_location"], event.get("location_aliases", []))
        if hit:
            location_hits += 1
        else:
            misses.append({
                "id": event["id"],
                "utterance": event["utterance"],
                "expected_location": event["expected_location"],
                "actual_location": actual_location,
                "parsed": parsed,
                "error": result.get("error") if isinstance(result, dict) else None,
            })
    total = len(events)
    return {
        "total": total,
        "valid_json_rate": round(valid_json / total, 4) if total else 0.0,
        "non_empty_location_rate": round(non_empty_locations / total, 4) if total else 0.0,
        "location_accuracy": round(location_hits / total, 4) if total else 0.0,
        "misses": misses,
    }


def build_eval_events(events: list[dict[str, Any]], outputs: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    records = {}
    for event in events:
        if outputs:
            parsed = (outputs.get(event["id"]) or {}).get("parsed") or {}
            location = merge_event_location(parsed)
            activity_type = clean_text(parsed.get("activity_type")) or event["expected_activity_type"]
        else:
            location = event["expected_location"]
            activity_type = event["expected_activity_type"]
        records[event["id"]] = {
            "id": event["id"],
            "activity_type": activity_type,
            "eval_location": location,
            "utterance": event["utterance"],
        }
    return records


def load_case_data(cases_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if data.get("base_cases"):
        base_path = cases_path.parent / data["base_cases"]
        base_data = json.loads(base_path.read_text(encoding="utf-8"))
        events = data.get("events") or base_data["events"]
        pairs = data["pairs"]
        return events, pairs
    return data["events"], data["pairs"]


def pair_labels(pairs: list[dict[str, Any]]) -> list[bool]:
    return [bool(pair["expected_should_match"]) for pair in pairs]


def pair_records(pairs: list[dict[str, Any]], events_by_id: dict[str, dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    return [(pair, events_by_id[pair["source_id"]], events_by_id[pair["target_id"]]) for pair in pairs]


def score_char_raw(source: dict[str, Any], target: dict[str, Any]) -> float:
    if is_online_or_flexible(source["eval_location"]) or is_online_or_flexible(target["eval_location"]):
        return 1.0
    return char_ngram_similarity(source["eval_location"], target["eval_location"])


def score_char_augmented(source: dict[str, Any], target: dict[str, Any]) -> float:
    if is_online_or_flexible(source["eval_location"]) or is_online_or_flexible(target["eval_location"]):
        return 1.0
    return char_ngram_similarity(augment_location_text(source["eval_location"]), augment_location_text(target["eval_location"]))


def score_char_augmented_gate(source: dict[str, Any], target: dict[str, Any]) -> float:
    if not strict_location_gate(source, target):
        return 0.0
    return score_char_augmented(source, target)


def score_city_overlap(source: dict[str, Any], target: dict[str, Any]) -> float:
    if is_online_or_flexible(source["eval_location"]) or is_online_or_flexible(target["eval_location"]):
        return 1.0
    source_cities = location_cities(source["eval_location"])
    target_cities = location_cities(target["eval_location"])
    if source_cities and target_cities and source_cities.intersection(target_cities):
        return 1.0
    return 0.0


def score_location_city_overlap(source: dict[str, Any], target: dict[str, Any]) -> float:
    source_loc = source["eval_location"]
    target_loc = target["eval_location"]
    if "不限" in clean_text(source_loc) or "不限" in clean_text(target_loc):
        return 1.0
    source_online = any(token in clean_text(source_loc) for token in ["线上", "远程", "视频"])
    target_online = any(token in clean_text(target_loc) for token in ["线上", "远程", "视频"])
    if source_online or target_online:
        return 1.0 if source_online and target_online else 0.0
    source_cities = location_only_cities(source_loc)
    target_cities = location_only_cities(target_loc)
    if source_cities and target_cities and source_cities.intersection(target_cities):
        return 1.0
    return 0.0


def score_location_alias_event(source: dict[str, Any], target: dict[str, Any]) -> float:
    return location_alias_score(source["eval_location"], target["eval_location"])


def score_location_containment_event(source: dict[str, Any], target: dict[str, Any]) -> float:
    return location_containment_score(source["eval_location"], target["eval_location"])


def score_location_augmented_char(source: dict[str, Any], target: dict[str, Any]) -> float:
    source_loc = source["eval_location"]
    target_loc = target["eval_location"]
    if "不限" in clean_text(source_loc) or "不限" in clean_text(target_loc):
        return 1.0
    source_online = any(token in clean_text(source_loc) for token in ["线上", "远程", "视频"])
    target_online = any(token in clean_text(target_loc) for token in ["线上", "远程", "视频"])
    if source_online or target_online:
        return 1.0 if source_online and target_online else 0.0
    return char_ngram_similarity(
        augment_location_text_location_only(source_loc),
        augment_location_text_location_only(target_loc),
    )


def evaluate_scores(
    name: str,
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
    scorer: Callable[[dict[str, Any], dict[str, Any]], float],
) -> dict[str, Any]:
    rows = pair_records(pairs, events_by_id)
    labels = pair_labels(pairs)
    scores = [scorer(source, target) for _, source, target in rows]
    metrics = best_threshold_metrics(scores, labels)
    mistakes = []
    threshold = metrics["threshold"]
    for score, expected, (pair, source, target) in zip(scores, labels, rows):
        actual = score >= threshold
        if actual != expected:
            mistakes.append({
                "id": pair["id"],
                "expected": expected,
                "actual": actual,
                "score": round(score, 4),
                "source": source,
                "target": target,
                "note": pair.get("note", ""),
            })
    metrics.update({"name": name, "mistakes": mistakes})
    return metrics


def sentence_embedding_scores(
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
    model_name: str,
    augmented: bool,
    include_activity: bool,
    gated: bool,
    local_files_only: bool,
    location_only: bool = False,
) -> list[float]:
    from sentence_transformers import SentenceTransformer
    import numpy as np

    try:
        model = SentenceTransformer(model_name, local_files_only=local_files_only)
    except TypeError:
        model = SentenceTransformer(model_name)

    text_by_id: dict[str, str] = {}
    for event_id, event in events_by_id.items():
        if augmented and location_only:
            location = augment_location_text_location_only(event["eval_location"])
        elif augmented:
            location = augment_location_text(event["eval_location"])
        else:
            location = event["eval_location"]
        text_by_id[event_id] = f"{event['activity_type']} {location}" if include_activity and not location_only else location

    texts = [text_by_id[event_id] for pair in pairs for event_id in [pair["source_id"], pair["target_id"]]]
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=16)
    scores = []
    for index, pair in enumerate(pairs):
        score = float(np.dot(vecs[index * 2], vecs[index * 2 + 1]))
        if gated:
            source = events_by_id[pair["source_id"]]
            target = events_by_id[pair["target_id"]]
            if not strict_location_gate(source, target):
                score = 0.0
        source_loc = events_by_id[pair["source_id"]]["eval_location"]
        target_loc = events_by_id[pair["target_id"]]["eval_location"]
        if is_online_or_flexible(source_loc) or is_online_or_flexible(target_loc):
            score = 1.0
        scores.append(score)
    return scores


def location_hybrid_embedding_scores(
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
    model_name: str,
    local_files_only: bool,
) -> list[float]:
    embedding_scores = sentence_embedding_scores(
        pairs,
        events_by_id,
        model_name=model_name,
        augmented=True,
        include_activity=False,
        gated=False,
        local_files_only=local_files_only,
        location_only=True,
    )
    text_scores = [
        score_location_hybrid_text(events_by_id[pair["source_id"]], events_by_id[pair["target_id"]])
        for pair in pairs
    ]
    return [max(text_score, embedding_score) for text_score, embedding_score in zip(text_scores, embedding_scores)]


def evaluate_embedding_strategy(
    name: str,
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
    scores: list[float],
) -> dict[str, Any]:
    labels = pair_labels(pairs)
    metrics = best_threshold_metrics(scores, labels)
    threshold = metrics["threshold"]
    mistakes = []
    for score, expected, pair in zip(scores, labels, pairs):
        actual = score >= threshold
        if actual != expected:
            mistakes.append({
                "id": pair["id"],
                "expected": expected,
                "actual": actual,
                "score": round(score, 4),
                "source": events_by_id[pair["source_id"]],
                "target": events_by_id[pair["target_id"]],
                "note": pair.get("note", ""),
            })
    metrics.update({"name": name, "mistakes": mistakes})
    return metrics


def evaluate_matching(
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
    include_embeddings: bool,
    embedding_model: str,
    local_files_only: bool,
) -> dict[str, Any]:
    strategies = {
        "city_overlap": evaluate_scores("city_overlap", pairs, events_by_id, score_city_overlap),
        "location_char_ngram": evaluate_scores("location_char_ngram", pairs, events_by_id, score_char_raw),
        "augmented_location_char_ngram": evaluate_scores("augmented_location_char_ngram", pairs, events_by_id, score_char_augmented),
        "augmented_char_ngram_strict_gate": evaluate_scores("augmented_char_ngram_strict_gate", pairs, events_by_id, score_char_augmented_gate),
    }
    if include_embeddings:
        embedding_specs = [
            ("location_embedding_raw", False, False, False),
            ("location_embedding_augmented", True, False, False),
            ("event_location_embedding_augmented", True, True, False),
            ("augmented_embedding_strict_gate", True, False, True),
        ]
        for name, augmented, include_activity, gated in embedding_specs:
            scores = sentence_embedding_scores(
                pairs,
                events_by_id,
                model_name=embedding_model,
                augmented=augmented,
                include_activity=include_activity,
                gated=gated,
                local_files_only=local_files_only,
            )
            strategies[name] = evaluate_embedding_strategy(name, pairs, events_by_id, scores)
    return strategies


def evaluate_location_only_matching(
    pairs: list[dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
    include_embeddings: bool,
    embedding_model: str,
    local_files_only: bool,
) -> dict[str, Any]:
    strategies = {
        "location_city_overlap": evaluate_scores("location_city_overlap", pairs, events_by_id, score_location_city_overlap),
        "location_alias": evaluate_scores("location_alias", pairs, events_by_id, score_location_alias_event),
        "location_containment": evaluate_scores("location_containment", pairs, events_by_id, score_location_containment_event),
        "location_char_ngram": evaluate_scores("location_char_ngram", pairs, events_by_id, score_char_raw),
        "location_augmented_char_ngram": evaluate_scores("location_augmented_char_ngram", pairs, events_by_id, score_location_augmented_char),
        "location_hybrid_text": evaluate_scores("location_hybrid_text", pairs, events_by_id, score_location_hybrid_text),
    }
    if include_embeddings:
        embedding_specs = [
            ("location_embedding_raw", False),
            ("location_embedding_augmented", True),
        ]
        for name, augmented in embedding_specs:
            scores = sentence_embedding_scores(
                pairs,
                events_by_id,
                model_name=embedding_model,
                augmented=augmented,
                include_activity=False,
                gated=False,
                local_files_only=local_files_only,
                location_only=True,
            )
            strategies[name] = evaluate_embedding_strategy(name, pairs, events_by_id, scores)
        hybrid_scores = location_hybrid_embedding_scores(
            pairs,
            events_by_id,
            model_name=embedding_model,
            local_files_only=local_files_only,
        )
        strategies["location_hybrid_embedding"] = evaluate_embedding_strategy(
            "location_hybrid_embedding",
            pairs,
            events_by_id,
            hybrid_scores,
        )
    return strategies


def print_extraction_summary(results: dict[str, Any], show_misses: bool) -> None:
    if not results:
        return
    print("Kimi event extraction")
    print("variant                    valid_json non_empty_loc location_acc")
    for variant, metrics in results.items():
        print(
            f"{variant:<26} {metrics['valid_json_rate']:<10.4f} "
            f"{metrics['non_empty_location_rate']:<13.4f} {metrics['location_accuracy']:<.4f}"
        )
        if show_misses and metrics["misses"]:
            print(f"  misses: {variant}")
            for miss in metrics["misses"][:16]:
                print("  " + json.dumps(miss, ensure_ascii=False))


def print_matching_summary(title: str, results: dict[str, Any], show_mistakes: bool) -> None:
    print(f"\n{title}")
    print("strategy                          acc     precision recall  f1      fp fn threshold")
    for name, metrics in results.items():
        print(
            f"{name:<33} {metrics['accuracy']:<7.4f} {metrics['precision']:<9.4f} "
            f"{metrics['recall']:<7.4f} {metrics['f1']:<7.4f} {metrics['fp']:<2} {metrics['fn']:<2} "
            f"{metrics['threshold']:<.2f}"
        )
    if show_mistakes:
        for name, metrics in results.items():
            if not metrics["mistakes"]:
                continue
            print(f"\nMistakes: {title} / {name}")
            for mistake in metrics["mistakes"][:16]:
                print(json.dumps(mistake, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--call-kimi", action="store_true")
    parser.add_argument("--variants", nargs="+", default=["default", "single_location_fewshot"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--include-embeddings", action="store_true")
    parser.add_argument("--embedding-model", default="shibing624/text2vec-base-chinese")
    parser.add_argument("--allow-model-download", action="store_true")
    parser.add_argument("--location-only", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--show-misses", action="store_true")
    args = parser.parse_args()

    all_events, all_pairs = load_case_data(args.cases)
    events = all_events[: args.limit] if args.limit else all_events
    event_ids = {event["id"] for event in events}
    pairs = [pair for pair in all_pairs if pair["source_id"] in event_ids and pair["target_id"] in event_ids]

    cache: dict[str, dict[str, Any]] = {}
    if args.call_kimi:
        cache = ensure_kimi_outputs(events, args.variants, args.cache, args.env, args.delay, args.retries, args.limit)
    elif args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))

    extraction_results = {
        variant: evaluate_extraction(events, cache.get(variant, {}))
        for variant in args.variants
        if cache.get(variant)
    }

    gold_events = build_eval_events(events)
    evaluator = evaluate_location_only_matching if args.location_only else evaluate_matching
    matching_results = {
        "gold_location": evaluator(
            pairs,
            gold_events,
            include_embeddings=args.include_embeddings,
            embedding_model=args.embedding_model,
            local_files_only=not args.allow_model_download,
        )
    }
    for variant in args.variants:
        if cache.get(variant):
            extracted_events = build_eval_events(events, cache.get(variant, {}))
            matching_results[f"kimi_{variant}"] = evaluator(
                pairs,
                extracted_events,
                include_embeddings=args.include_embeddings,
                embedding_model=args.embedding_model,
                local_files_only=not args.allow_model_download,
            )

    print(f"events={len(events)} pairs={len(pairs)}")
    print_extraction_summary(extraction_results, args.show_misses)
    for title, results in matching_results.items():
        print_matching_summary(f"Match decision metrics: {title}", results, args.show_misses)

    if args.json_output:
        payload = {"extraction": extraction_results, "matching": matching_results}
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_output}")


if __name__ == "__main__":
    main()
