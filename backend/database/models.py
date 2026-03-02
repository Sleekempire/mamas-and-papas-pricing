"""
database/models.py — SQLAlchemy ORM models for the Mamas & Papas pricing platform.
Updated to reflect the retail channel-based data schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, JSON, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="Viewer")  # Admin|Analyst|Merchandiser|Viewer
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    uploads = relationship("DataUpload", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")


# ─────────────────────────────────────────────────────────────────────────────
class DataUpload(Base):
    __tablename__ = "data_uploads"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_row_count = Column(Integer, nullable=True)
    cleaned_row_count = Column(Integer, nullable=True)
    quarantine_count = Column(Integer, default=0)
    status = Column(String(30), default="pending")  # pending|processing|complete|failed
    error_message = Column(Text, nullable=True)
    ingested_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    user = relationship("User", back_populates="uploads")
    raw_records = relationship("RawDataRecord", back_populates="upload")
    cleaned_records = relationship("CleanedDataRecord", back_populates="upload")


# ─────────────────────────────────────────────────────────────────────────────
class RawDataRecord(Base):
    """Immutable record of raw CSV data as ingested (before cleaning)."""
    __tablename__ = "raw_data"

    id = Column(String(36), primary_key=True, default=_uuid)
    upload_id = Column(String(36), ForeignKey("data_uploads.id"), nullable=False)

    # Product identity
    description = Column(String(255), nullable=False, index=True)
    analyst_category = Column(String(100), nullable=True)
    group_name = Column(String(100), nullable=True)
    sub_group = Column(String(100), nullable=True)

    # Time dimensions
    fiscal_year = Column(Integer, nullable=True)
    fiscal_week_number = Column(Integer, nullable=True)
    day_of_week = Column(String(20), nullable=True)

    # Channel quantities
    nb_qty_total = Column(Float, nullable=True)
    nb_net_total = Column(Float, nullable=True)
    home_shopping_nb_qty = Column(Float, nullable=True)
    home_shop_nb_qty = Column(Float, nullable=True)
    nb_c_stores = Column(Float, nullable=True)
    nb_p_total = Column(Float, nullable=True)
    nb_pre_event = Column(Float, nullable=True)
    promo_flag = Column(Integer, nullable=True)  # 0 or 1

    is_quarantined = Column(Boolean, default=False)

    upload = relationship("DataUpload", back_populates="raw_records")
    quarantine = relationship("QuarantineRecord", back_populates="raw_record", uselist=False)


# ─────────────────────────────────────────────────────────────────────────────
class CleanedDataRecord(Base):
    """Cleaned, type-enforced data after outlier removal — includes engineered features."""
    __tablename__ = "cleaned_data"

    id = Column(String(36), primary_key=True, default=_uuid)
    upload_id = Column(String(36), ForeignKey("data_uploads.id"), nullable=False)

    # Product identity
    description = Column(String(255), nullable=False, index=True)
    analyst_category = Column(String(100), nullable=True)
    group_name = Column(String(100), nullable=True)
    sub_group = Column(String(100), nullable=True)

    # Time dimensions
    fiscal_year = Column(Integer, nullable=False)
    fiscal_week_number = Column(Integer, nullable=False)
    day_of_week = Column(String(20), nullable=True)

    # Channel quantities (raw)
    nb_qty_total = Column(Float, nullable=False)
    nb_net_total = Column(Float, nullable=False)
    home_shopping_nb_qty = Column(Float, nullable=True)
    home_shop_nb_qty = Column(Float, nullable=True)
    nb_c_stores = Column(Float, nullable=True)
    nb_p_total = Column(Float, nullable=True)
    nb_pre_event = Column(Float, nullable=True)
    promo_flag = Column(Integer, nullable=True)

    # Engineered features
    implied_price = Column(Float, nullable=True)          # NB Net Total / NB Qty Total
    channel_mix_ratio = Column(Float, nullable=True)      # home shopping share
    fiscal_quarter = Column(Integer, nullable=True)
    lag_1 = Column(Float, nullable=True)
    lag_4 = Column(Float, nullable=True)
    rolling_mean_4 = Column(Float, nullable=True)

    upload = relationship("DataUpload", back_populates="cleaned_records")

    __table_args__ = (
        Index("ix_cleaned_desc_year_week", "description", "fiscal_year", "fiscal_week_number"),
    )


# ─────────────────────────────────────────────────────────────────────────────
class QuarantineRecord(Base):
    __tablename__ = "quarantine_records"

    id = Column(String(36), primary_key=True, default=_uuid)
    raw_record_id = Column(String(36), ForeignKey("raw_data.id"), nullable=False, unique=True)
    reason = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    raw_record = relationship("RawDataRecord", back_populates="quarantine")


# ─────────────────────────────────────────────────────────────────────────────
class ModelVersion(Base):
    __tablename__ = "model_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    algorithm = Column(String(50), nullable=False)  # LinearRegression|RandomForest|GradientBoosting
    train_r2 = Column(Float, nullable=True)
    val_r2 = Column(Float, nullable=True)
    rmse = Column(Float, nullable=True)
    feature_names = Column(JSON, nullable=True)   # list of feature names
    model_file_path = Column(String(500), nullable=False)
    upload_id = Column(String(36), ForeignKey("data_uploads.id"), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    trained_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    trained_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    recommendations = relationship("Recommendation", back_populates="model_version")


# ─────────────────────────────────────────────────────────────────────────────
class OptimisationRun(Base):
    __tablename__ = "optimisation_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    model_version_id = Column(String(36), ForeignKey("model_versions.id"), nullable=True)
    sku_count = Column(Integer, nullable=True)
    target_date = Column(String(20), nullable=True)
    run_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    recommendations = relationship("Recommendation", back_populates="optimisation_run")


# ─────────────────────────────────────────────────────────────────────────────
class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(String(36), primary_key=True, default=_uuid)
    optimisation_run_id = Column(String(36), ForeignKey("optimisation_runs.id"), nullable=True)
    model_version_id = Column(String(36), ForeignKey("model_versions.id"), nullable=True)

    # Product identity (replaces old 'sku' field)
    description = Column(String(255), nullable=False, index=True)
    analyst_category = Column(String(100), nullable=True)

    target_date = Column(String(20), nullable=False, index=True)
    current_price = Column(Float, nullable=False)         # ImpliedPrice at time of run
    recommended_price = Column(Float, nullable=False)
    price_change_pct = Column(Float, nullable=True)
    expected_demand = Column(Float, nullable=False)
    expected_revenue = Column(Float, nullable=False)
    expected_margin = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=True)
    elasticity = Column(Float, nullable=True)
    elasticity_class = Column(String(20), nullable=True)
    top_drivers = Column(JSON, nullable=True)
    constraint_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    model_version = relationship("ModelVersion", back_populates="recommendations")
    optimisation_run = relationship("OptimisationRun", back_populates="recommendations")

    __table_args__ = (
        Index("ix_rec_desc_date", "description", "target_date"),
        Index("ix_rec_category", "analyst_category"),
    )


# ─────────────────────────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    event_type = Column(String(50), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    role = Column(String(20), nullable=True)
    endpoint = Column(String(200), nullable=True)
    metadata_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_now, nullable=False, index=True)

    user = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_event_ts", "event_type", "timestamp"),
    )
