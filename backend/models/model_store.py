"""
models/model_store.py — Joblib model persistence with versioning.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
from sklearn.pipeline import Pipeline

from config import settings


def _model_filename(algorithm: str, version_id: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return settings.MODEL_STORE_PATH / f"model_{algorithm}_{version_id[:8]}_{ts}.pkl"


def save_model(pipeline: Pipeline, algorithm: str, version_id: str) -> str:
    """Persist a trained pipeline to disk. Returns the file path."""
    path = _model_filename(algorithm, version_id)
    joblib.dump(pipeline, path, compress=3)
    return str(path)


def load_model(file_path: str) -> Pipeline:
    """Load a persisted pipeline from disk."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {file_path}")
    return joblib.load(path)


def get_active_model_path(db) -> Optional[str]:
    """Query the DB for the active model's file path."""
    from database.models import ModelVersion
    mv = db.query(ModelVersion).filter(ModelVersion.is_active == True).first()
    if mv:
        return mv.model_file_path
    return None
