import copy
import json
import sys
from pathlib import Path


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_value(flat, expected_keys, key, value):
    if key in expected_keys and value is not None:
        flat[key] = str(value)


def get_path(data, path, default=""):
    current = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return default if current is None else current


def probability_text(value):
    if isinstance(value, str):
        return value if value.endswith("%") else value + "%"
    return str(value) + "%"


def probability_number(value):
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    return int(value)


def map_direct(flat, expected_keys, canonical):
    mappings = {
        "REPORT_TITLE": ("meta", "report_title"),
        "REPORT_DATETIME": ("meta", "report_datetime"),
        "BRAND_NAME": ("meta", "brand_name"),
        "SAMPLE_BADGE": ("meta", "sample_badge"),
        "INDICATOR_NAME": ("meta", "indicator_name"),
        "MULTI_EVENT_NOTE": ("meta", "multi_event_note"),
        "LEAD_EVENT_LABEL": ("event", "lead_event_label"),
        "SECONDARY_EVENT_NAME": ("event", "secondary", "name"),
        "SECONDARY_EVENT_LABEL": ("event", "secondary", "label"),
        "SECONDARY_EVENT_TITLE": ("event", "secondary", "title"),
        "SECONDARY_EVENT_ACTUAL": ("event", "secondary", "actual"),
        "SECONDARY_EVENT_EXPECTED": ("event", "secondary", "expected"),
        "SECONDARY_EVENT_SUMMARY": ("event", "secondary", "summary"),
        "TABLE_ACTUAL_LABEL": ("event", "table_labels", "actual"),
        "TABLE_EXPECTED_LABEL": ("event", "table_labels", "expected"),
        "TABLE_PREVIOUS_LABEL": ("event", "table_labels", "previous"),
        "CPI_ACTUAL": ("event", "actual"),
        "CPI_EXPECTED": ("event", "expected"),
        "CPI_PREVIOUS": ("event", "previous"),
        "CPI_SUBLABEL": ("event", "sublabel"),
        "CPI_SURPRISE_DELTA": ("event", "surprise_delta"),
        "CORE_INDICATOR_NAME": ("event", "core", "name"),
        "CORE_CPI_ACTUAL": ("event", "core", "actual"),
        "CORE_CPI_EXPECTED": ("event", "core", "expected"),
        "CORE_CPI_PREVIOUS": ("event", "core", "previous"),
        "CORE_CPI_SUBLABEL": ("event", "core", "sublabel"),
        "CORE_CPI_SURPRISE_DELTA": ("event", "core", "surprise_delta"),
        "HEADLINE_PREFIX": ("headline", "prefix"),
        "HEADLINE_SURPRISE": ("headline", "surprise"),
        "HEADLINE_MESSAGE": ("headline", "message"),
        "IMPORTANCE_LABEL": ("headline", "importance_label"),
        "SURPRISE_LABEL": ("headline", "surprise_label"),
        "DETAIL_CONFIRM_LABEL": ("headline", "detail_confirm_label"),
        "NARRATIVE_FIT_LABEL": ("headline", "narrative_fit_label"),
        "OVERALL_CALL": ("market_view", "overall_call"),
        "OVERALL_SCORE": ("market_view", "overall_score"),
        "SCORE_EXPLANATION": ("market_view", "score_explanation"),
        "PREVIOUS_CALL": ("market_view", "previous_call"),
        "CURRENT_CALL": ("market_view", "current_call"),
        "AI_SUMMARY_HTML": ("analysis", "summary_html"),
    }
    for key, path in mappings.items():
        set_value(flat, expected_keys, key, get_path(canonical, path))


def map_assets(flat, expected_keys, canonical):
    set_value(flat, expected_keys, "ASSET_ACCORDION_HINT", get_path(canonical, ("assets_meta", "accordion_hint")))
    set_value(flat, expected_keys, "ASSET_MATCH_LABEL", get_path(canonical, ("assets_meta", "match_label")))
    for index, asset in enumerate(canonical.get("assets", []), start=1):
        set_value(flat, expected_keys, f"ASSET_{index}_NAME", asset.get("name", ""))
        set_value(flat, expected_keys, f"ASSET_{index}_MOVE", asset.get("move", ""))
        set_value(flat, expected_keys, f"ASSET_{index}_NOTE", asset.get("note", ""))
        set_value(flat, expected_keys, f"ASSET_{index}_CHIP", asset.get("chip", ""))


def map_market_view(flat, expected_keys, canonical):
    for index, point in enumerate(get_path(canonical, ("market_view", "key_points"), []), start=1):
        set_value(flat, expected_keys, f"REASON_{index}_TITLE", point.get("title", ""))
        set_value(flat, expected_keys, f"REASON_{index}_TEXT", point.get("text", ""))


def map_historical_cases(flat, expected_keys, canonical):
    meta = canonical.get("historical_cases_meta", {})
    for key, field in {
        "SIMILARITY_KEYLINE": "keyline",
        "SIMILARITY_HINT": "hint",
        "SIMILARITY_SUMMARY_BOLD": "summary_bold",
        "SIMILARITY_SUMMARY_TEXT": "summary_text",
        "CASE_AVG_LABEL": "average_label",
        "CASE_AVG_RETURN": "average_return",
        "CASE_AVG_DETAIL": "average_detail",
    }.items():
        set_value(flat, expected_keys, key, meta.get(field, ""))

    for index, case in enumerate(canonical.get("historical_cases", []), start=1):
        prefix = f"CASE_{index}"
        fields = {
            "TITLE": "title",
            "SUBTITLE": "subtitle",
            "SUBTITLE_PREFIX": "subtitle_prefix",
            "SUBTITLE_BOLD": "subtitle_bold",
            "SIMILARITY": "similarity",
            "RETURN": "return",
            "RETURN_LABEL": "return_label",
        }
        for suffix, field in fields.items():
            set_value(flat, expected_keys, f"{prefix}_{suffix}", case.get(field, ""))


def map_scenarios(flat, expected_keys, canonical):
    total = sum(probability_number(item.get("probability", 0)) for item in canonical.get("scenarios", []))
    if total != 100:
        print(f"ERROR: scenario probability total is {total}")
        return False

    for index, scenario in enumerate(canonical.get("scenarios", []), start=1):
        prefix = f"SCENARIO_{index}"
        set_value(flat, expected_keys, f"{prefix}_NAME", scenario.get("name", ""))
        set_value(flat, expected_keys, f"{prefix}_PROB", probability_text(scenario.get("probability", "")))
        set_value(flat, expected_keys, f"{prefix}_PATH", scenario.get("path", ""))
        set_value(flat, expected_keys, f"{prefix}_BENEFICIARIES", scenario.get("beneficiaries", ""))
        set_value(flat, expected_keys, f"{prefix}_TRIGGER_BOLD", scenario.get("trigger_bold", ""))
        set_value(flat, expected_keys, f"{prefix}_TRIGGER_TEXT", scenario.get("trigger_text", ""))
        set_value(flat, expected_keys, f"{prefix}_INVALIDATION_BOLD", scenario.get("invalidation_bold", ""))
        set_value(flat, expected_keys, f"{prefix}_INVALIDATION_TEXT", scenario.get("invalidation_text", ""))
        set_value(flat, expected_keys, f"{prefix}_INVALIDATION", scenario.get("invalidation", ""))
        set_value(flat, expected_keys, f"{prefix}_AVOID", scenario.get("avoid", ""))
    return True


def map_risks(flat, expected_keys, canonical):
    for index, risk in enumerate(canonical.get("risks", []), start=1):
        prefix = f"RISK_{index}"
        set_value(flat, expected_keys, f"{prefix}_DATE", risk.get("date", ""))
        set_value(flat, expected_keys, f"{prefix}_TITLE", risk.get("title", ""))
        set_value(flat, expected_keys, f"{prefix}_TEXT", risk.get("text", ""))


def build_flat_payload(canonical, reference_flat):
    expected_keys = set(reference_flat)
    flat = copy.deepcopy(canonical.get("flat_overrides", {}))

    map_direct(flat, expected_keys, canonical)
    map_market_view(flat, expected_keys, canonical)
    map_assets(flat, expected_keys, canonical)
    map_historical_cases(flat, expected_keys, canonical)
    if not map_scenarios(flat, expected_keys, canonical):
        return None
    map_risks(flat, expected_keys, canonical)

    extra_keys = sorted(set(flat) - expected_keys)
    missing_keys = sorted(expected_keys - set(flat))

    if missing_keys:
        print("ERROR: missing flat payload keys")
        for key in missing_keys:
            print(key)
    if extra_keys:
        print("ERROR: unexpected flat payload keys")
        for key in extra_keys:
            print(key)
    if missing_keys or extra_keys:
        return None

    return {key: flat[key] for key in reference_flat}


def main():
    root = Path(__file__).resolve().parents[1]
    canonical_path = root / "data" / "canonical_sample_payload.json"
    flat_path = root / "data" / "sample_payload.json"

    canonical = load_json(canonical_path)
    reference_flat = load_json(flat_path)

    flat = build_flat_payload(canonical, reference_flat)
    if flat is None:
        return 1

    save_json(flat_path, flat)
    print("OK: data/sample_payload.json regenerated from canonical payload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
