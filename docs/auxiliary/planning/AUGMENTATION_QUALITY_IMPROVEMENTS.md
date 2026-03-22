# Augmentation Quality Improvements

This document describes the **training-api** augmentation and promotion
behavior implemented to reduce off-distribution synthetic examples and to
allow promotion when accuracy is slightly lower but still within a configured
band.

## Scope

- **In scope:** `services/training-api/app/refine/augment.py`,
  `services/training-api/app/refine/prompts.py`,
  `services/training-api/app/jobs/runner.py` (`run_promote`), and
  `services/training-api/app/refine/config.py` (`RefineConfig`).
- **Out of scope:** The legacy `services/refiner/` container still uses its own
  prompts; it does not include these gates unless aligned separately.

## Behavior Summary

1. **Seed examples:** The augment prompt includes real `train.csv` rows for the
   target label (up to `REFINER_AUGMENT_SEED_EXAMPLES`) so the LLM paraphrases
   in-distribution text.
2. **Validation:** Parsed rows must match the requested label, respect max
   length, and pass existing length and newline rules.
3. **Self-consistency:** After generation, each batch is re-labeled with the
   relabel prompt; rows where `suggested_label` or confidence fail the gate
   are dropped. Disable with `REFINER_AUGMENT_VERIFY_LABELS=false` to save
   latency (roughly one fewer LLM call per label).
4. **Merge:** Exact dedupe against `train.csv` plus character-trigram Jaccard
   similarity (> 0.85) against same-label texts to avoid near-duplicate bloat.
5. **Per-class counts:** `REFINER_AUGMENT_N_PER_LABEL` is a base; rarer classes
   get a higher `N` (capped at `3 * base_n`).
6. **Promote:** Promotion runs if accuracy is at least
   `previous_accuracy - REFINER_PROMOTE_ACCURACY_TOLERANCE`, or if baseline
   accuracy was zero. The API response includes per-label recall deltas for
   observability.

## Environment Variables

| Variable | Role |
| -------- | ---- |
| `REFINER_AUGMENT_VERIFY_LABELS` | Enable post-generation verification (`true` / `false`). |
| `REFINER_AUGMENT_VERIFY_MIN_CONFIDENCE` | Minimum confidence for verification to keep a row. |
| `REFINER_AUGMENT_MAX_TEXT_LENGTH` | Max characters for generated `text`. |
| `REFINER_AUGMENT_SEED_EXAMPLES` | Number of real seed strings per label in the prompt. |
| `REFINER_PROMOTE_ACCURACY_TOLERANCE` | Allowed drop in aggregate accuracy before promote rejects. |

Defaults live in `config/PROJECT_CONFIG.yaml` under `default`. Regenerate
`env/.env.<env>` with `python scripts/generate_env.py <env>` after edits.

## Artifact Notes

- Per-label `augment.label_*.validation.json` may include `verified_count` and
  `verification_rejected_count`.
- `merge_augment.validation.json` includes `fuzzy_duplicate_count`.
- Augment completion events may include `label_counts` (per-label N used for
  the run).

## See Also

- [REFINER_FLOW.md](../refiner/REFINER_FLOW.md)
- [CONFIGURATION.md](../architecture/CONFIGURATION.md)
- [METRICS_JSON.md](../reference/METRICS_JSON.md)
- [PERFORMANCE_IMPROVEMENTS.md](PERFORMANCE_IMPROVEMENTS.md)
