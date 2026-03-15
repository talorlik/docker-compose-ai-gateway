"""Background job runners for train, refine, and promote.

Per TRAIN_AND_REFINE_GUI_PAGES_TECH §2, §4: run_train/run_refine/run_promote
invoke trainer/refiner via Docker Compose and read artifacts from
model_artifacts volume. Mounts are configured in Compose (Batch 7).
"""

from app.jobs.runner import run_promote, run_refine, run_train

__all__ = ["run_train", "run_refine", "run_promote"]
