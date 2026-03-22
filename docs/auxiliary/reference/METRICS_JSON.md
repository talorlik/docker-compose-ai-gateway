# METRICS.JSON - EVALUATION SIGNAL

`metrics.json` is the **evaluation signal** that determines whether a refinement
actually improved the model. It is not used to change labels directly. It is
used to **decide whether a newly trained model is better than the previous one**.

The refinement pipeline uses three artifacts for different purposes:

| Artifact | Purpose |
| -------- | ------- |
| `misclassified.csv` | Identify specific mistakes to analyze |
| `metrics.json` | Measure global model quality |
| `train.csv` | Canonical dataset used for retraining |

`metrics.json` answers the question: **"Did the dataset changes improve the
classifier?"**

## What metrics.json Contains

Example structure:

```json
{
  "accuracy": 0.91,
  "classification_report": {
    "search": {"precision": 0.90, "recall": 0.88, "f1-score": 0.89},
    "image": {"precision": 0.92, "recall": 0.90, "f1-score": 0.91},
    "ops": {"precision": 0.89, "recall": 0.91, "f1-score": 0.90},
    "unknown": {"precision": 0.94, "recall": 0.87, "f1-score": 0.90}
  },
  "confusion_matrix": [
    [43, 2, 1, 0],
    [3, 39, 2, 0],
    [1, 2, 41, 1],
    [0, 1, 2, 35]
  ]
}
```

This provides three types of information.

## 1. Detect Weak Labels

Look at **recall** and **precision** per class.

Example:

| Label | Precision | Recall |
| ----- | --------- | ------ |
| search | 0.90 | 0.88 |
| image | 0.92 | 0.90 |
| ops | 0.70 | 0.52 |
| unknown | 0.93 | 0.90 |

Interpretation:

- `ops` recall is very low - the model misses many ops requests
- Dataset likely lacks enough ops examples

Refinement action:

- Generate more **ops** examples
- Add edge cases that resemble other classes

## 2. Detect Confusion Patterns

The confusion matrix shows **which classes collide**.

Example:

```text
ops -> image confusion = high
```

Interpretation:

Many prompts mentioning "image" actually refer to container images.

Refinement action:

Generate examples like:

```text
kubernetes container image pull error
docker imagepullbackoff debugging
pod cannot pull image from registry
```

All labeled **ops**. This teaches the classifier the correct context.

## 3. Detect Threshold Problems

If model accuracy is good but many requests become `unknown`, the dataset may
be fine and only the gateway threshold needs adjustment.

Example:

```text
macro_f1 = 0.91
unknown recall = 0.98
unknown precision = 0.55
```

Interpretation:

Too many inputs are classified as `unknown`.

Action:

- Reduce `T_ROUTE`
- Or reduce `T_MARGIN`

This is **policy tuning**, not dataset refinement.

## Pipeline Position

Full loop:

```text
train.csv
   |
   v
train.py
   |
   +-- model.joblib
   +-- metrics.json
   +-- misclassified.csv
          |
          v
       refiner
          |
          v
 new examples / relabel suggestions
          |
          v
 updated train.csv
          |
          v
 retrain
```

## Automated Refinement Using Metrics

The refiner uses metrics.json for:

- **Weak labels**: if `class_recall < 0.75`, generate examples for that label
- **Confusion patterns**: if `confusion(A,B) > 10`, generate contrastive
  examples for the true label A

Promotion logic (training-api `run_promote`, when a candidate model finishes
training on `train_candidate.csv`):

```text
tolerance = REFINER_PROMOTE_ACCURACY_TOLERANCE  # e.g. 0.01
if previous_accuracy == 0 or candidate_accuracy >= previous_accuracy - tolerance:
    promote model.joblib
else:
    discard candidate
```

The promote response includes `per_label_recall` (before, after, delta) for each
label in `classification_report` so you can see trade-offs when aggregate
accuracy moves slightly.

This reduces the chance that a small accuracy dip blocks promotion when recall
on weak classes improved, while still rejecting large regressions.

## Practical Usage During Development

When you run training:

```text
trainer
  +-- metrics.json
  +-- misclassified.csv
```

Your workflow becomes:

1. Inspect `metrics.json`
2. Identify weak classes
3. Use LLM refiner to generate new examples
4. Retrain
5. Compare new `metrics.json`

Repeat until metrics stabilize.

## Mental Model

| File | Question it answers |
| ---- | ------------------- |
| misclassified.csv | What mistakes did the model make? |
| metrics.json | Is the model improving overall? |

Both are needed. One gives **local debugging**. The other gives **global
evaluation**.

## Refiner Integration

The refiner uses `metrics.json` to identify weak labels and confusion patterns,
and to decide whether to promote a candidate model. See
[REFINER_PLAN.md](docs/auxiliary/refiner/REFINER_PLAN.md),
[REFINER_TECHNICAL.md](docs/auxiliary/refiner/REFINER_TECHNICAL.md),
[REFINER_FLOW.md](docs/auxiliary/refiner/REFINER_FLOW.md),
[AUGMENTATION_QUALITY_IMPROVEMENTS.md](../planning/AUGMENTATION_QUALITY_IMPROVEMENTS.md).
