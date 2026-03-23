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


def augment_examples(label: str, n: int, seed_examples: list[str]) -> str:
    labels_str = ", ".join(LABELS)
    seeds_block = ""
    if seed_examples:
        seeds_json = json.dumps(seed_examples, ensure_ascii=False)
        seeds_block = f"""
## SEED EXAMPLES (REAL DATA)
These are real user prompts from the training set for intent \"{label}\":
{seeds_json}

"""
    return f"""# Generate Synthetic Examples

## ROLE
You are a data augmentation assistant for an intent classification dataset.

## GOAL
Generate {n} synthetic user prompts that would correctly be classified as
\"{label}\".
{seeds_block}## TASK
1. Use the examples above as guidance for style and intent boundaries.
2. Generate exactly {n} realistic user prompts (short queries or commands)
   that match only the \"{label}\" intent.
3. {"Paraphrase and vary these seed examples: vary phrasing, length, and style while preserving the same intent." if seed_examples else "Vary phrasing, length, and style while preserving intent."}
4. Use synonyms and close paraphrases naturally (for example: create/make,
   check/inspect, find/look up, troubleshoot/debug).
5. Include intent-revealing phrases that imply routing even without explicit
   keywords (for example: \"create me a logo\" -> image, \"what services are running\" -> ops).
6. For label \"ops\", cover a wide range of technical domains:
   DevOps, IT support, systems administration, cloud operations, and AI/ML ops.
7. For label \"ops\", include a mix of:
   - full commands (for example: \"kubectl get pods -A\")
   - partial command fragments (for example: \"kubectl logs\", \"docker ps\")
   - natural-language operational requests (for example: \"check GPU memory usage\")
8. Avoid duplicates and near-duplicates within the generated set.
9. Each output row must be clearly classifiable as \"{label}\".

## OUTPUT
Respond with valid JSON only, as an array.

Schema: [{{\"text\":\"<prompt>\",\"label\":\"{label}\"}}, ...]

## GUARDRAILS
- label must be one of: {labels_str}
- Each object's label must be exactly \"{label}\" (the target intent for this task).
- text should be short (max ~100 chars) with no newlines
- avoid duplicates and near-duplicates (including small wording changes)
- output must be a JSON array only, no extra text
"""
