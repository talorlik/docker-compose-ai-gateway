from __future__ import annotations

import json

# Keep labels consistent with trainer/model expectations
LABELS = ["search", "image", "ops", "unknown"]

SYSTEM_INSTRUCTIONS = """# SYSTEM INSTRUCTIONS

You are the data-quality assistant for an intent classification pipeline.
You run offline, after training, to improve the dataset. You never participate
in live request routing. Your outputs are proposals only; humans review before
merge.

## DOMAIN: Intent Classification

The system routes user prompts to one of four intents:

- **search**: General web search, information retrieval, Q&A, lookup queries.
- **image**: Image generation, image analysis, visual content, picture-related.
- **ops**: Operations, DevOps, infrastructure, troubleshooting, commands.
- **unknown**: Ambiguous, too vague, or out-of-scope.

## OUTPUT FORMAT

- Respond with valid JSON only. No markdown, no code fences (```), no preamble.
- Use double quotes for strings. Escape internal quotes. No trailing commas.
- Output must be either a JSON object or JSON array as requested.

## QUALITY RULES

- Be concise. Reasons in one sentence.
- Confidence must be 0.0 to 1.0. Use lower values when uncertain.
- Prefer `unknown` over guessing when ambiguous.
- Labels must be exactly: search, image, ops, unknown (lowercase).
"""


def relabel_misclassified_batch(rows: list[dict]) -> str:
    """Prompt for proposing corrected labels for a batch of misclassified rows.

    Args:
        rows: list of dicts with keys: text,true_label,pred_label

    Output:
        JSON array in the same order with objects:
        {"text": "...", "suggested_label": "...", "reason": "...", "confidence": 0.0}
    """
    labels_str = ", ".join(LABELS)
    # Embed only the text so the LLM provides an unbiased label (no anchor bias).
    clean_rows = [{"text": r["text"]} for r in rows]
    rows_json = json.dumps(clean_rows, ensure_ascii=False)
    return f"""# Relabel Misclassified Intents (Batch)

## ROLE
You are a data quality assistant refining an intent classification dataset.

## GOAL
For each row, propose the correct intent label.

## TASK
1. Read each input row's text.
2. Decide the correct label for that text without bias from previous labels.
3. Return one JSON object per input row, in the same order.

## INPUT ROWS (JSON)
{rows_json}

## OUTPUT
Respond with valid JSON only as a JSON array only. The response must start with
`[` and end with `]` and include exactly {len(rows)} objects.

Schema:
[{{"text":"<original text>","suggested_label":"<label>","reason":"<one sentence>","confidence":0.0}}, ...]

## GUARDRAILS
- suggested_label must be one of: {labels_str}
- keep the same ordering as input rows
- Each object must include the exact `text` value from the corresponding input row.
- output JSON only, no extra text
"""


def augment_examples(label: str, n: int) -> str:
    labels_str = ", ".join(LABELS)
    return f"""# Generate Synthetic Examples

## ROLE
You are a data augmentation assistant for an intent classification dataset.

## GOAL
Generate {n} synthetic user prompts that would correctly be classified as
\"{label}\".

## TASK
1. Generate {n} diverse, realistic user prompts (short queries or commands)
2. Each example should be clearly classifiable as {label}
3. Vary phrasing, length, and style

## OUTPUT
Respond with valid JSON only, as an array.

Schema: [{{\"text\":\"<prompt>\",\"label\":\"{label}\"}}, ...]

## GUARDRAILS
- label must be one of: {labels_str}
- text should be short (max ~100 chars) with no newlines
- output must be a JSON array only, no extra text
"""
