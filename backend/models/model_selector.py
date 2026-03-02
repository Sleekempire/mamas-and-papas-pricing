"""
models/model_selector.py — Auto-select best model by validation R².
"""
from __future__ import annotations

from typing import List, Optional

from models.demand_model import ModelResult


def select_best_model(results: List[ModelResult]) -> ModelResult:
    """
    Select the model with the highest validation R².
    Penalise models with very high train-val gap (overfitting).
    """
    def score(r: ModelResult) -> float:
        overfit_penalty = max(0.0, r.train_r2 - r.val_r2 - 0.1) * 0.5
        return r.val_r2 - overfit_penalty

    best = max(results, key=score)
    return best


def summarise_results(results: List[ModelResult]) -> List[dict]:
    """Return summary dicts for all model results (safe to serialise)."""
    return [
        {
            "algorithm": r.algorithm,
            "train_r2": r.train_r2,
            "val_r2": r.val_r2,
            "rmse": r.rmse,
            "feature_count": len(r.feature_names),
        }
        for r in results
    ]
