from __future__ import annotations

import json

from import_training_api import training_api_imported

with training_api_imported():
    from app.refine.prompts import relabel_misclassified_batch  # pylint: disable=import-error


def test_relabel_batch_prompt_embeds_json_rows():
    rows = [
        {"text": "t1", "true_label": "search", "pred_label": "ops"},
        {"text": "t2", "true_label": "image", "pred_label": "image"},
    ]
    prompt = relabel_misclassified_batch(rows)
    # Ensure the serialized JSON is present so ordering can be preserved.
    clean_rows = [{"text": r["text"]} for r in rows]
    assert json.dumps(clean_rows, ensure_ascii=False) in prompt
