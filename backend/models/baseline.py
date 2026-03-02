"""
models/baseline.py — Baseline demand modelling gateway.

Re-exports the core train/predict functions from demand_model as the
canonical 'baseline' entry point per the modular spec:

    Step 1: Baseline demand modelling
"""
from __future__ import annotations

from models.demand_model import (  # noqa: F401
    ModelResult,
    predict_demand,
    train_all_models,
)

__all__ = ["ModelResult", "train_all_models", "predict_demand"]
