"""Tests for relabel and augment enqueue/process via Redis Streams."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from import_training_api import training_api_imported

with training_api_imported():
    from app.refine import relabel as relabel_mod
    from app.refine import augment as augment_mod
    from app.refine.config import RefineConfig
    from app.refine.relabel import (
        RelabelTask,
        enqueue_relabel_batches,
        run_relabel_workers,
        _handle_task as handle_relabel_task,
    )
    from app.refine.augment import (
        enqueue_augment_tasks,
        run_augment_workers,
    )
    from app.refine.ollama_pool import OllamaPool


def _cfg(tmp_path) -> RefineConfig:
    return RefineConfig(
        runs_root=tmp_path / "runs",
        relabel_batch_size=2,
        relabel_max_parallel_batches=2,
        augment_n_per_label=3,
        augment_max_parallel_labels=2,
        ollama_urls=["http://ollama1:11434"],
        ollama_model="phi3:mini",
        ollama_timeout_seconds=10,
        ollama_max_inflight_per_instance=2,
        relabel_tasks_stream="test:relabel:tasks",
        augment_tasks_stream="test:augment:tasks",
        relabel_consumer_group="relabel-workers",
        augment_consumer_group="augment-workers",
        events_channel_prefix="test:events:",
    )


# --- enqueue_relabel_batches ---


def test_enqueue_relabel_batches_creates_correct_number(tmp_path):
    cfg = _cfg(tmp_path)
    rows = [
        {"text": f"t{i}", "true_label": "search", "pred_label": "ops"}
        for i in range(5)
    ]
    with patch.object(relabel_mod, "stream_add") as mock_add:
        count = enqueue_relabel_batches(cfg, run_id="r1", misclassified_rows=rows)
    # batch_size=2, 5 rows -> 3 batches (2+2+1)
    assert count == 3
    assert mock_add.call_count == 3


def test_enqueue_relabel_batches_uses_correct_stream(tmp_path):
    cfg = _cfg(tmp_path)
    rows = [{"text": "t1", "true_label": "search", "pred_label": "ops"}]
    with patch.object(relabel_mod, "stream_add") as mock_add:
        enqueue_relabel_batches(cfg, run_id="r1", misclassified_rows=rows)
    assert mock_add.call_args[0][0] == "test:relabel:tasks"


def test_enqueue_relabel_batches_fields_contain_run_id(tmp_path):
    cfg = _cfg(tmp_path)
    rows = [{"text": "t1", "true_label": "search", "pred_label": "ops"}]
    with patch.object(relabel_mod, "stream_add") as mock_add:
        enqueue_relabel_batches(cfg, run_id="r1", misclassified_rows=rows)
    fields = mock_add.call_args[0][1]
    assert fields["run_id"] == "r1"
    assert "batch_id" in fields
    assert "rows" in fields


def test_enqueue_relabel_batches_empty_rows(tmp_path):
    cfg = _cfg(tmp_path)
    with patch.object(relabel_mod, "stream_add") as mock_add:
        count = enqueue_relabel_batches(cfg, run_id="r1", misclassified_rows=[])
    assert count == 0
    mock_add.assert_not_called()


# --- enqueue_augment_tasks ---


def test_enqueue_augment_tasks_creates_one_per_label(tmp_path):
    cfg = _cfg(tmp_path)
    labels = ["search", "image", "ops"]
    with patch.object(augment_mod, "stream_add") as mock_add:
        count = enqueue_augment_tasks(cfg, run_id="r2", labels=labels)
    assert count == 3
    assert mock_add.call_count == 3


def test_enqueue_augment_tasks_uses_correct_stream(tmp_path):
    cfg = _cfg(tmp_path)
    with patch.object(augment_mod, "stream_add") as mock_add:
        enqueue_augment_tasks(cfg, run_id="r2", labels=["search"])
    assert mock_add.call_args[0][0] == "test:augment:tasks"


def test_enqueue_augment_fields_contain_label_and_n(tmp_path):
    cfg = _cfg(tmp_path)
    with patch.object(augment_mod, "stream_add") as mock_add:
        enqueue_augment_tasks(cfg, run_id="r2", labels=["image"])
    fields = mock_add.call_args[0][1]
    assert fields["run_id"] == "r2"
    assert fields["label"] == "image"
    assert fields["n"] == 3  # augment_n_per_label


# --- handle_relabel_task ---


def test_handle_relabel_task_parses_valid_response(tmp_path):
    cfg = _cfg(tmp_path)
    task = RelabelTask(
        run_id="r1",
        batch_id="0000",
        rows=[{"text": "hello", "true_label": "search", "pred_label": "ops"}],
    )
    ollama_response = json.dumps([
        {
            "text": "hello",
            "suggested_label": "search",
            "reason": "clearly a search",
            "confidence": 0.95,
        }
    ])

    pool = MagicMock(spec=OllamaPool)
    pool.generate.return_value = ollama_response

    result = handle_relabel_task(cfg=cfg, pool=pool, task=task)
    assert len(result) == 1
    assert result[0]["text"] == "hello"
    assert result[0]["suggested_label"] == "search"
    assert result[0]["confidence"] == 0.95


def test_handle_relabel_task_raises_on_invalid_json(tmp_path):
    cfg = _cfg(tmp_path)
    task = RelabelTask(run_id="r1", batch_id="0000", rows=[])

    pool = MagicMock(spec=OllamaPool)
    pool.generate.return_value = "not valid json"

    with pytest.raises(ValueError, match="Invalid JSON"):
        handle_relabel_task(cfg=cfg, pool=pool, task=task)


def test_handle_relabel_task_filters_invalid_labels(tmp_path):
    cfg = _cfg(tmp_path)
    task = RelabelTask(
        run_id="r1",
        batch_id="0000",
        rows=[
            {"text": "a", "true_label": "search", "pred_label": "ops"},
            {"text": "b", "true_label": "search", "pred_label": "ops"},
        ],
    )
    ollama_response = json.dumps([
        {"text": "a", "suggested_label": "search", "reason": "ok", "confidence": 0.9},
        {"text": "b", "suggested_label": "INVALID", "reason": "bad", "confidence": 0.5},
    ])

    pool = MagicMock(spec=OllamaPool)
    pool.generate.return_value = ollama_response

    result = handle_relabel_task(cfg=cfg, pool=pool, task=task)
    assert len(result) == 1
    assert result[0]["text"] == "a"


# --- run_relabel_workers (integration with mocked Redis) ---


def test_run_relabel_workers_processes_batch(tmp_path):
    cfg = _cfg(tmp_path)
    run_id = "r1"
    cfg.relabel_dir(run_id).mkdir(parents=True, exist_ok=True)

    entry_fields = {
        "run_id": run_id,
        "batch_id": "0000",
        "rows": json.dumps([{"text": "hello", "true_label": "search", "pred_label": "ops"}]),
    }

    pool = MagicMock(spec=OllamaPool)
    pool.generate.return_value = json.dumps([
        {"text": "hello", "suggested_label": "search", "reason": "ok", "confidence": 0.9}
    ])

    progress_events = []
    with (
        patch.object(relabel_mod, "stream_group_create"),
        patch.object(relabel_mod, "stream_read_group", side_effect=[
            [("entry-1", entry_fields)],
            [],
        ]),
        patch.object(relabel_mod, "stream_ack") as mock_ack,
        patch.object(relabel_mod, "publish_event"),
        patch.object(relabel_mod, "get_ollama_pool", return_value=pool),
    ):
        run_relabel_workers(
            cfg,
            run_id=run_id,
            expected_batches=1,
            progress=lambda evt: progress_events.append(evt),
        )

    mock_ack.assert_called_once_with("test:relabel:tasks", f"relabel-workers:{run_id}", "entry-1")
    assert any("complete" in str(evt.get("detail", "")) for evt in progress_events)


# --- run_augment_workers (integration with mocked Redis) ---


def test_run_augment_workers_processes_label(tmp_path):
    cfg = _cfg(tmp_path)
    run_id = "r2"
    cfg.augment_dir(run_id).mkdir(parents=True, exist_ok=True)

    entry_fields = {
        "run_id": run_id,
        "label": "search",
        "n": "3",
    }

    pool = MagicMock(spec=OllamaPool)
    pool.generate.return_value = json.dumps([
        {"text": "find restaurants nearby", "label": "search"},
        {"text": "compare cloud providers", "label": "search"},
        {"text": "what is kubernetes", "label": "search"},
    ])

    progress_events = []
    with (
        patch.object(augment_mod, "stream_group_create"),
        patch.object(augment_mod, "stream_read_group", side_effect=[
            [("entry-1", entry_fields)],
            [],
        ]),
        patch.object(augment_mod, "stream_ack") as mock_ack,
        patch.object(augment_mod, "publish_event"),
        patch.object(augment_mod, "get_ollama_pool", return_value=pool),
    ):
        run_augment_workers(
            cfg,
            run_id=run_id,
            expected_labels=1,
            progress=lambda evt: progress_events.append(evt),
        )

    mock_ack.assert_called_once_with("test:augment:tasks", f"augment-workers:{run_id}", "entry-1")
    assert any("complete" in str(evt.get("detail", "")) for evt in progress_events)


def test_augment_worker_skips_wrong_run_id(tmp_path):
    cfg = _cfg(tmp_path)
    run_id = "r3"
    cfg.augment_dir(run_id).mkdir(parents=True, exist_ok=True)

    entry_fields = {"run_id": "other-run", "label": "search", "n": "3"}

    pool = MagicMock(spec=OllamaPool)

    with (
        patch.object(augment_mod, "stream_group_create"),
        patch.object(augment_mod, "stream_read_group", side_effect=[
            [("entry-1", entry_fields)],
            [],
        ]),
        patch.object(augment_mod, "stream_ack") as mock_ack,
        patch.object(augment_mod, "publish_event"),
        patch.object(augment_mod, "get_ollama_pool", return_value=pool),
    ):
        run_augment_workers(cfg, run_id=run_id, expected_labels=0)

    mock_ack.assert_not_called()
    pool.generate.assert_not_called()


def test_relabel_worker_publishes_error_on_bad_ollama_response(tmp_path):
    cfg = _cfg(tmp_path)
    run_id = "r4"
    cfg.relabel_dir(run_id).mkdir(parents=True, exist_ok=True)

    entry_fields = {
        "run_id": run_id,
        "batch_id": "0000",
        "rows": json.dumps([{"text": "x", "true_label": "search", "pred_label": "ops"}]),
    }

    pool = MagicMock(spec=OllamaPool)
    pool.generate.return_value = "not json"

    progress_events = []
    with (
        patch.object(relabel_mod, "stream_group_create"),
        patch.object(relabel_mod, "stream_read_group", side_effect=[
            [("entry-1", entry_fields)],
            [],
        ]),
        patch.object(relabel_mod, "stream_ack") as mock_ack,
        patch.object(relabel_mod, "publish_event"),
        patch.object(relabel_mod, "get_ollama_pool", return_value=pool),
    ):
        run_relabel_workers(
            cfg,
            run_id=run_id,
            expected_batches=1,
            progress=lambda evt: progress_events.append(evt),
        )

    # Should NOT ack on failure (left for retry)
    mock_ack.assert_not_called()
    # Should publish an error progress event
    assert any("failed" in str(evt.get("detail", "")).lower() for evt in progress_events)
