"""
models/demand_model.py — Train Linear Regression, Random Forest, and Gradient Boosting demand models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from data.feature_engineer import MODEL_FEATURES, get_feature_matrix


@dataclass
class ModelResult:
    algorithm: str
    pipeline: Pipeline
    feature_names: List[str]
    train_r2: float
    val_r2: float
    rmse: float
    metadata: Dict = field(default_factory=dict)


def _build_pipelines() -> Dict[str, Pipeline]:
    return {
        "LinearRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=1.0)),
        ]),
        "RandomForest": Pipeline([
            ("model", RandomForestRegressor(
                n_estimators=200,
                max_depth=12,
                min_samples_leaf=5,
                n_jobs=-1,
                random_state=42,
            )),
        ]),
        "GradientBoosting": Pipeline([
            ("model", GradientBoostingRegressor(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42,
            )),
        ]),
    }


def train_all_models(df: pd.DataFrame) -> List[ModelResult]:
    """
    Train all three demand models on the engineered feature set.
    Uses a time-aware 80/20 split to prevent future leakage.
    """
    X, y, feature_names = get_feature_matrix(df)

    if len(X) < 20:
        raise ValueError("Insufficient data: need at least 20 rows to train models")

    # ── Time-aware split: use last 20% as validation ──────────────────────────
    split_idx = int(len(X) * 0.80)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    if len(X_train) < 10 or len(X_val) < 5:
        # Fall back to random split for small datasets
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

    results: List[ModelResult] = []
    pipelines = _build_pipelines()

    for name, pipeline in pipelines.items():
        pipeline.fit(X_train, y_train)

        train_pred = pipeline.predict(X_train)
        val_pred = pipeline.predict(X_val)

        # Clip negative demand predictions
        val_pred = np.clip(val_pred, 0, None)
        train_pred = np.clip(train_pred, 0, None)

        train_r2 = float(r2_score(y_train, train_pred))
        val_r2 = float(r2_score(y_val, val_pred))
        rmse = float(np.sqrt(mean_squared_error(y_val, val_pred)))

        results.append(ModelResult(
            algorithm=name,
            pipeline=pipeline,
            feature_names=feature_names,
            train_r2=round(train_r2, 4),
            val_r2=round(val_r2, 4),
            rmse=round(rmse, 4),
            metadata={"val_size": len(X_val), "train_size": len(X_train)},
        ))

    return results


def predict_demand(pipeline: Pipeline, feature_df: pd.DataFrame) -> np.ndarray:
    """Generate demand predictions from a trained pipeline."""
    preds = pipeline.predict(feature_df)
    return np.clip(preds, 0, None)
