import re
import json
from typing import Any

def parse_json_response(raw: str) -> list[dict[str, Any]] | None:
    """Parse Ollama output into a JSON array of dicts.

    In practice, models sometimes wrap JSON in markdown code fences or return
    a JSON object that contains the array. This parser is intentionally
    forgiving.
    """
    text = (raw or "").strip()

    # Strip common markdown code fences: ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()

    def _coerce_to_list(data: object) -> list[dict[str, Any]] | None:
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            # Sometimes models return a single object instead of an array.
            # Check for keys from relabel (suggested_label) or augment (label) 
            if (
                "text" in data
                and ("suggested_label" in data or "label" in data)
            ):
                return [data]  # type: ignore[list-item]
            # Accept a few likely wrapper keys.
            for key in ("relabels", "items", "data", "results", "proposed_relabels", "examples", "proposed_examples", "augmentations"):
                v = data.get(key)
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
        return None

    # 1) Try parsing the whole thing.
    try:
        data = json.loads(text)
        parsed = _coerce_to_list(data)
        if parsed is not None:
            return parsed
    except json.JSONDecodeError:
        pass

    # 2) If there is extra text, attempt to extract the first JSON array/object.
    start = text.find("[")
    end = text.rfind("]")
    
    # Try array extraction first
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
            parsed = _coerce_to_list(data)
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass
            
    # Try object extraction if array extraction failed
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        candidate = text[start_obj : end_obj + 1]
        try:
            data = json.loads(candidate)
            parsed = _coerce_to_list(data)
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass

    return None
