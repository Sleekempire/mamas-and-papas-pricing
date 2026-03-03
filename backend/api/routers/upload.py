"""
api/routers/upload.py — POST /upload-data
Accepts CSV in Mamas & Papas retail channel format, runs full ingestion pipeline.
Requires: Admin or Analyst role.
"""
from __future__ import annotations

import io
import uuid
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database.connection import get_db
from database.models import (
    CleanedDataRecord, DataUpload, QuarantineRecord, RawDataRecord,
)
from data.cleaner import clean_dataframe
from data.feature_engineer import engineer_features
from data.outlier import detect_outliers
from data.validator import validate_schema
from security.audit import AuditEventType, write_audit_log
from security.csv_sanitizer import (
    CSVInjectionError, sanitise_dataframe,
    validate_file_extension, validate_file_size,
)
from security.rbac import RequireAnalystOrAbove
from security.auth import TokenData

router = APIRouter()


SAMPLE_CSV_CONTENT = """FiscalYear,FiscalWeekNumber,DayOfWeek,AnalystCategory,Group,SubGroup,Description,Home Shopping NB Qty,Home Shopping NB Nett Sales,Home Shopping NB Profit - Group,Stores NB Qty,Stores NB Nett Sales,Stores NB Profit - Group,Total NB Qty,Total NB Nett Sales,Total NB Profit - Group,Event,PromoFlag
2025,47,Monday,Equipment,1600-NURSERY EQUIPMENT,160010-Highchairs,11521D400-H/CHAIR SNAX - JUNGLE ALPHABET,5,287.5,142.3,2,105,46.95,7,392.5,189.25,No Promotion,0
2025,47,Monday,Equipment,1600-NURSERY EQUIPMENT,160010-Highchairs,11521FG00-H/CHAIR SNAX - FRUIT GARDEN,5,287.5,142.4,0,0,0,5,287.5,142.4,No Promotion,0
2025,47,Monday,Equipment,1600-NURSERY EQUIPMENT,160020-Baby Seating,41261CL00-BABY SNUG & ACT TRAY - CLAY,5,187.27,88.72,6,220.02,101.76,11,407.29,190.48,No Promotion,0
2025,47,Monday,Toys & Gifts,4200-TOYS,420020-Soft Toys,4855DA800-SOFT TOY - WTTW DUCKLING BEANIE,3,24,15.12,14,112,70.56,17,136,85.68,No Promotion,0
2025,47,Monday,Toys & Gifts,4200-TOYS,420050-Playmats,7736ZR101-WTTW PLAYMAT PINK,5,316.45,177.35,5,363.35,224.25,10,679.8,401.6,No Promotion,0
2025,46,Sunday,Equipment,1600-NURSERY EQUIPMENT,160010-Highchairs,11521D400-H/CHAIR SNAX - JUNGLE ALPHABET,9,510.89,249.8,2,115,56.97,11,625.89,306.77,No Promotion,0
2025,46,Sunday,Equipment,1600-NURSERY EQUIPMENT,160025-Cradles & Swings,5085A0100-ALTO SMART SWING - CASHMERE,6,945,551.06,6,937.12,541.96,12,1882.12,1093.02,No Promotion,0
2025,46,Sunday,Toys & Gifts,4200-TOYS,420020-Soft Toys,7580MD101-PINK BUNNY COMFORTER,6,47.96,32.72,27,220.2,151.62,33,268.16,184.34,No Promotion,0
2025,46,Saturday,Equipment,1600-NURSERY EQUIPMENT,160010-Highchairs,11521D400-H/CHAIR SNAX - JUNGLE ALPHABET,5,287.5,142.45,4,222.5,106.43,9,510,248.88,No Promotion,0
2025,46,Saturday,Toys & Gifts,4200-TOYS,420050-Playmats,7736RE400-PLAYMAT - WTTW DUCKLING,2,174.83,118.51,23,1971.69,1337.12,25,2146.52,1455.63,No Promotion,0
"""


class UploadResponse(BaseModel):
    upload_id: str
    original_row_count: int
    cleaned_row_count: int
    quarantine_count: int
    warnings: list
    status: str


@router.get("/upload-data/sample-csv")
async def download_sample_csv():
    """Return a sample CSV for users to fill in with their own data."""
    return StreamingResponse(
        io.StringIO(SAMPLE_CSV_CONTENT),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mamas_papas_sample_data.csv"},
    )


@router.post("/upload-data", response_model=UploadResponse)
def upload_data(
    request: Request,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(RequireAnalystOrAbove),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    upload_id = str(uuid.uuid4())

    # ── File validation ───────────────────────────────────────────────────────
    try:
        validate_file_extension(file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    raw_bytes = file.file.read()

    try:
        validate_file_size(len(raw_bytes))
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))

    # ── Read CSV ───────────────────────────────────────────────────────────────
    try:
        df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Cannot parse CSV: {e}")

    original_count = len(df)

    # ── CSV injection sanitisation ────────────────────────────────────────────
    try:
        df = sanitise_dataframe(df)
    except CSVInjectionError as e:
        write_audit_log(db, AuditEventType.SCHEMA_VIOLATION, current_user.user_id,
                        current_user.role, "/upload-data", {"reason": str(e)}, ip)
        raise HTTPException(status_code=422, detail=str(e))

    # ── Schema validation ─────────────────────────────────────────────────────
    try:
        df, schema_warnings = validate_schema(df)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ── Create upload record ──────────────────────────────────────────────────
    upload = DataUpload(
        id=upload_id,
        user_id=current_user.user_id,
        filename=file.filename or "unknown.csv",
        original_row_count=original_count,
        status="processing",
    )
    db.add(upload)
    db.flush()

    # ── Store raw records ─────────────────────────────────────────────────────
    def _safe_float(val):
        try:
            return float(val) if val and str(val).strip() not in ("", "nan", "None") else None
        except (ValueError, TypeError):
            return None

    def _safe_int(val):
        try:
            return int(float(val)) if val and str(val).strip() not in ("", "nan", "None") else None
        except (ValueError, TypeError):
            return None

    raw_records = []
    for _, row in df.iterrows():
        rec = RawDataRecord(
            upload_id=upload_id,
            description=str(row.get("Description", "")).strip().upper(),
            analyst_category=str(row.get("AnalystCategory", "")),
            group_name=str(row.get("Group", "")),
            sub_group=str(row.get("SubGroup", "")),
            fiscal_year=_safe_int(row.get("FiscalYear")),
            fiscal_week_number=_safe_int(row.get("FiscalWeekNumber")),
            day_of_week=str(row.get("DayOfWeek", "")),
            nb_qty_total=_safe_float(row.get("Total NB Qty")),
            nb_net_total=_safe_float(row.get("Total NB Nett Sales")),
            home_shopping_nb_qty=_safe_float(row.get("Home Shopping NB Qty")),
            home_shop_nb_qty=_safe_float(row.get("Stores NB Qty")),
            nb_c_stores=_safe_float(row.get("Stores NB Nett Sales")),
            nb_p_total=_safe_float(row.get("Total NB Profit - Group")),
            nb_pre_event=_safe_float(row.get("Home Shopping NB Profit - Group")),
            promo_flag=_safe_int(row.get("PromoFlag")),
        )
        raw_records.append(rec)
    db.bulk_save_objects(raw_records)

    # ── Data cleaning ─────────────────────────────────────────────────────────
    cleaned_df, clean_messages = clean_dataframe(df)

    # ── Outlier detection ─────────────────────────────────────────────────────
    clean_df, quarantine_df, _ = detect_outliers(cleaned_df)

    # ── Feature engineering ───────────────────────────────────────────────────
    engineered_df = engineer_features(clean_df)

    # ── Store cleaned records ─────────────────────────────────────────────────
    cleaned_records = []
    for _, row in engineered_df.iterrows():
        rec = CleanedDataRecord(
            upload_id=upload_id,
            description=str(row.get("Description", "")).strip().upper(),
            analyst_category=str(row.get("AnalystCategory", "")),
            group_name=str(row.get("Group", "")),
            sub_group=str(row.get("SubGroup", "")),
            fiscal_year=_safe_int(row.get("FiscalYear")),
            fiscal_week_number=_safe_int(row.get("FiscalWeekNumber")),
            day_of_week=str(row.get("DayOfWeek", "")),
            nb_qty_total=float(row["Total NB Qty"]) if pd.notna(row.get("Total NB Qty")) else 0.0,
            nb_net_total=float(row["Total NB Nett Sales"]) if pd.notna(row.get("Total NB Nett Sales")) else 0.0,
            home_shopping_nb_qty=_safe_float(row.get("Home Shopping NB Qty")),
            home_shop_nb_qty=_safe_float(row.get("Stores NB Qty")),
            nb_c_stores=_safe_float(row.get("Stores NB Nett Sales")),
            nb_p_total=_safe_float(row.get("Total NB Profit - Group")),
            nb_pre_event=_safe_float(row.get("Home Shopping NB Profit - Group")),
            promo_flag=_safe_int(row.get("PromoFlag")),
            implied_price=float(row.get("ImpliedPrice", 0.0)),
            channel_mix_ratio=float(row.get("channel_mix_ratio", 0.0)),
            fiscal_quarter=_safe_int(row.get("fiscal_quarter")),
            lag_1=float(row.get("Lag_1", 0.0)),
            lag_4=float(row.get("Lag_4", 0.0)),
            rolling_mean_4=float(row.get("Rolling_Mean_4", 0.0)),
        )
        cleaned_records.append(rec)
    db.bulk_save_objects(cleaned_records)

    # ── Update upload record ──────────────────────────────────────────────────
    upload.cleaned_row_count = len(engineered_df)
    upload.quarantine_count = len(quarantine_df)
    upload.status = "complete"
    db.commit()

    write_audit_log(db, AuditEventType.DATA_UPLOAD, current_user.user_id, current_user.role,
                    "/upload-data",
                    {"upload_id": upload_id, "rows": original_count, "quarantined": len(quarantine_df)},
                    ip)

    return UploadResponse(
        upload_id=upload_id,
        original_row_count=original_count,
        cleaned_row_count=len(engineered_df),
        quarantine_count=len(quarantine_df),
        warnings=schema_warnings + clean_messages,
        status="complete",
    )
