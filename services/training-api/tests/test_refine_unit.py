from __future__ import annotations

import json

import pandas as pd  # pylint: disable=import-error

from import_training_api import training_api_imported

with training_api_imported():
    from app.refine.augment import _parse_json_array as parse_augment_json  # pylint: disable=import-error
    from app.refine.relabel import _parse_json_response as parse_relabel_json  # pylint: disable=import-error
    from app.refine.augment import merge_augment_outputs  # pylint: disable=import-error
    from app.refine.relabel import merge_relabel_outputs  # pylint: disable=import-error
    from app.refine.config import RefineConfig  # pylint: disable=import-error


def test_parse_relabel_json_array_valid():
    raw = json.dumps([{"text": "a", "suggested_label": "search"}])
    assert parse_relabel_json(raw) == [{"text": "a", "suggested_label": "search"}]


def test_parse_relabel_json_array_invalid():
    assert parse_relabel_json("{not json") is None
    assert parse_relabel_json(json.dumps({"x": 1})) is None


def test_parse_augment_json_filters_invalid_items():
    raw = json.dumps(
        [
            {"text": "okay", "label": "search"},
            {"text": "bad\nnl", "label": "search"},
            {"text": "x", "label": "search"},
            {"text": "ok2", "label": "not_a_label"},
        ]
    )
    out = parse_augment_json(raw)
    assert out is not None
    assert [r["text"] for r in out] == ["okay"]


def test_merge_relabel_outputs_applies_last_suggestion(tmp_path):  # type: ignore[no-untyped-def]
    cfg = RefineConfig.from_env(str(tmp_path))
    run_id = "r1"
    batches_dir = cfg.relabel_dir(run_id) / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    # Two batches propose different labels for same text; last one should win.
    (batches_dir / "proposed_relabels.batch_0000.csv").write_text(
        "text,suggested_label,reason,confidence\nhello,search,r,0.9\n",
        encoding="utf-8",
    )
    (batches_dir / "proposed_relabels.batch_0001.csv").write_text(
        "text,suggested_label,reason,confidence\nhello,ops,r,0.95\n",
        encoding="utf-8",
    )

    train_df = pd.DataFrame([{"text": "hello", "label": "search"}])
    out = merge_relabel_outputs(cfg, run_id=run_id, train_df=train_df)
    assert out.loc[0, "label"] == "ops"


def test_merge_augment_outputs_dedupes_existing_text(tmp_path):  # type: ignore[no-untyped-def]
    cfg = RefineConfig.from_env(str(tmp_path))
    run_id = "r2"
    labels_dir = cfg.augment_dir(run_id) / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    (labels_dir / "proposed_examples.label_search.csv").write_text(
        "text,label,source_pattern\nhello,search,augmentation\nnew,search,augmentation\n",
        encoding="utf-8",
    )

    train_df = pd.DataFrame([{"text": "hello", "label": "ops"}])
    out = merge_augment_outputs(cfg, run_id=run_id, train_df=train_df)
    assert "new" in set(out["text"].astype(str))
    # existing 'hello' should not be duplicated
    assert list(out["text"].astype(str)).count("hello") == 1
