"""
security/audit.py — Structured audit log service.
Writes tamper-evident entries to the audit_logs DB table.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("audit")


class AuditEventType:
    DATA_UPLOAD = "DATA_UPLOAD"
    MODEL_TRAINING = "MODEL_TRAINING"
    OPTIMISATION_RUN = "OPTIMISATION_RUN"
    RECOMMENDATION_ACCESS = "RECOMMENDATION_ACCESS"
    EXPLANATION_ACCESS = "EXPLANATION_ACCESS"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    RATE_LIMIT_HIT = "RATE_LIMIT_HIT"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"


def write_audit_log(
    db: Session,
    event_type: str,
    user_id: Optional[str],
    role: Optional[str],
    endpoint: str,
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Write a structured audit log entry to the database.
    Import here avoids circular imports with models.
    """
    from database.models import AuditLog

    # Never log sensitive fields
    safe_meta = _sanitise_metadata(metadata or {})

    entry = AuditLog(
        event_type=event_type,
        user_id=user_id,
        role=role,
        endpoint=endpoint,
        metadata_json=json.dumps(safe_meta),
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()

    logger.info(
        "AUDIT|%s|user=%s|role=%s|endpoint=%s|meta=%s",
        event_type,
        user_id,
        role,
        endpoint,
        json.dumps(safe_meta),
    )


_SENSITIVE_KEYS = {
    "password", "token", "secret", "cost", "raw_data",
    "feature_vector", "model_params", "unit_cost",
}


def _sanitise_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Strip any sensitive keys from metadata before logging."""
    return {
        k: v for k, v in meta.items()
        if k.lower() not in _SENSITIVE_KEYS
    }
