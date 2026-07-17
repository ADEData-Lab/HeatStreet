"""Shared analytical contracts for model routing and public reporting.

This module deliberately contains no pipeline orchestration.  It is the single
source of truth used by modeling, reporting, and semantic QA.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


PROPERTY_ID_COLUMN = "CERTIFICATE_NUMBER"
HN_READY_TIERS = frozenset({1, 2, 3})

READINESS_LABELS: Mapping[str, str] = {
    "ready": "Ready for low-temperature heat",
    "fabric_required": "Fabric improvements required",
    "not_ready": "Further technical assessment required",
}

READINESS_INTERPRETATIONS: Mapping[str, str] = {
    "ready": "Meets the modelled fabric and heat-demand criteria; no technology is prescribed.",
    "fabric_required": "Modelled fabric measures are required before low-temperature heat; no technology is prescribed.",
    "not_ready": "The available EPC evidence is insufficient for a modelled readiness conclusion; no technology is prescribed.",
}

TIER_READINESS_LABELS: Mapping[int, str] = {
    1: "Tier 1: Ready now",
    2: "Tier 2: Minor enabling work required",
    3: "Tier 3: Major enabling work required",
    4: "Tier 4: Technically challenging",
    5: "Tier 5: Further assessment required",
}

TIER_READINESS_INTERPRETATIONS: Mapping[int, str] = {
    tier: "Fabric and heat-demand readiness classification; this does not prescribe a heating technology."
    for tier in TIER_READINESS_LABELS
}


@dataclass(frozen=True)
class ModelFamilyContract:
    model_family: str
    model_purpose: str
    intended_reporting_use: str
    publication_scope: str
    headline_reporting_eligible: bool

    def metadata(self) -> dict[str, Any]:
        return asdict(self)


STOCK_SCENARIO = ModelFamilyContract(
    model_family="stock_scenario",
    model_purpose="public stock-wide scenario assessment",
    intended_reporting_use="public_scenario_reporting",
    publication_scope="client",
    headline_reporting_eligible=True,
)

DIAGNOSTIC_FULL_FABRIC_PATHWAY = ModelFamilyContract(
    model_family="diagnostic_full_fabric_pathway",
    model_purpose="diagnostic and distributional full-fabric pathway assessment",
    intended_reporting_use="diagnostic_distributional_only",
    publication_scope="internal",
    headline_reporting_eligible=False,
)

MODEL_FAMILIES: Mapping[str, ModelFamilyContract] = {
    STOCK_SCENARIO.model_family: STOCK_SCENARIO,
    DIAGNOSTIC_FULL_FABRIC_PATHWAY.model_family: DIAGNOSTIC_FULL_FABRIC_PATHWAY,
}

PAYBACK_DEFINITION = "upfront capital cost divided by annual bill savings"
PAYBACK_DENOMINATOR = "properties with finite capital cost and strictly positive annual bill savings"
PAYBACK_SERIALIZATION_POLICY = "non-finite values are serialized as null with an explicit status and counts"


def is_publication_eligible(model_family: str) -> bool:
    contract = MODEL_FAMILIES.get(model_family)
    return bool(contract and contract.headline_reporting_eligible)


def publication_scope(model_family: str) -> str:
    try:
        return MODEL_FAMILIES[model_family].publication_scope
    except KeyError as exc:
        raise ValueError(f"Unknown model family: {model_family!r}") from exc


def require_property_identifier(df: pd.DataFrame) -> pd.Series:
    """Return the authoritative property ID after enforcing uniqueness/null rules."""
    if PROPERTY_ID_COLUMN not in df.columns:
        raise ValueError(f"Missing authoritative property identifier: {PROPERTY_ID_COLUMN}")
    identifiers = df[PROPERTY_ID_COLUMN]
    if identifiers.isna().any() or identifiers.astype(str).str.strip().eq("").any():
        raise ValueError(f"{PROPERTY_ID_COLUMN} contains null or blank values")
    if identifiers.duplicated().any():
        duplicates = identifiers[identifiers.duplicated(keep=False)].astype(str).unique()[:5]
        raise ValueError(f"{PROPERTY_ID_COLUMN} must be unique; duplicates include {duplicates.tolist()}")
    return identifiers.astype(str)


def hn_ready_from_tier(tier: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(tier, errors="coerce")
    if numeric.isna().any():
        raise ValueError("tier_number contains missing or non-numeric classifications")
    return numeric.astype(int).isin(HN_READY_TIERS)


def validate_hn_readiness(df: pd.DataFrame, *, require_complete: bool = True) -> pd.DataFrame:
    """Validate that the stored HN flag is exactly the canonical tier rule."""
    required = {"tier_number", "hn_ready"}
    missing = required.difference(df.columns)
    if missing:
        if require_complete:
            raise ValueError(f"Spatial enrichment is incomplete; missing {sorted(missing)}")
        return df
    expected = hn_ready_from_tier(df["tier_number"])
    actual = df["hn_ready"]
    if actual.isna().any():
        raise ValueError("hn_ready contains null classifications")
    actual = actual.astype(bool)
    mismatch = actual.ne(expected)
    if mismatch.any():
        raise ValueError(f"hn_ready conflicts with canonical tiers for {int(mismatch.sum())} properties")
    return df


def join_spatial_enrichment(
    authoritative: pd.DataFrame,
    classified: pd.DataFrame,
    *,
    production: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Join classifications one-to-one while preserving authoritative row order."""
    authoritative_ids = require_property_identifier(authoritative)
    classified_ids = require_property_identifier(classified)
    spatial_columns = [
        column for column in ("tier_number", "hn_ready", "distance_to_network_m", "in_heat_zone", "heat_network_tier")
        if column in classified.columns
    ]
    if not {"tier_number", "hn_ready"}.issubset(spatial_columns):
        raise ValueError("Spatial classification must include tier_number and hn_ready")

    left = authoritative.drop(columns=[c for c in spatial_columns if c in authoritative.columns]).copy()
    left[PROPERTY_ID_COLUMN] = authoritative_ids.to_numpy()
    right = classified[[PROPERTY_ID_COLUMN, *spatial_columns]].copy()
    right[PROPERTY_ID_COLUMN] = classified_ids.to_numpy()
    merged = left.merge(
        right,
        on=PROPERTY_ID_COLUMN,
        how="left",
        sort=False,
        validate="one_to_one",
        indicator=True,
    )
    unmatched = int(merged["_merge"].ne("both").sum())
    merged = merged.drop(columns="_merge")
    if len(merged) != len(authoritative):
        raise RuntimeError("Spatial join changed the authoritative cohort size")
    if not merged[PROPERTY_ID_COLUMN].tolist() == authoritative_ids.tolist():
        raise RuntimeError("Spatial join changed authoritative property order")
    missing_required = int(merged[["tier_number", "hn_ready"]].isna().any(axis=1).sum())
    if production and (unmatched or missing_required):
        raise RuntimeError(
            f"Spatial enrichment lost required classifications: unmatched={unmatched}, incomplete={missing_required}"
        )
    validate_hn_readiness(merged, require_complete=production)
    summary = {
        "authoritative_rows": int(len(authoritative)),
        "classified_rows": int(len(classified)),
        "enriched_rows": int(len(merged)),
        "unmatched_properties": unmatched,
        "incomplete_required_classifications": missing_required,
        "hn_ready_properties": int(merged["hn_ready"].fillna(False).astype(bool).sum()),
        "property_identifier": PROPERTY_ID_COLUMN,
        "join_validation": "one_to_one",
        "authoritative_order_preserved": True,
    }
    return merged, summary


def payback_summary(capital_cost: pd.Series, annual_savings: pd.Series) -> dict[str, Any]:
    """Return explicit aggregate and property simple-payback statistics."""
    capex = pd.to_numeric(capital_cost, errors="coerce")
    savings = pd.to_numeric(annual_savings, errors="coerce")
    valid = capex.notna() & np.isfinite(capex) & savings.notna() & np.isfinite(savings) & savings.gt(0)
    property_payback = capex[valid] / savings[valid]
    aggregate_savings = float(savings.fillna(0).sum())
    aggregate_capex = float(capex.fillna(0).sum())
    aggregate = aggregate_capex / aggregate_savings if aggregate_savings > 0 else None
    return {
        "aggregate_simple_payback_years": float(aggregate) if aggregate is not None and np.isfinite(aggregate) else None,
        "aggregate_simple_payback_status": "valid" if aggregate is not None and np.isfinite(aggregate) else "non_positive_aggregate_savings",
        "property_simple_payback_mean_years": float(property_payback.mean()) if len(property_payback) else None,
        "property_simple_payback_median_years": float(property_payback.median()) if len(property_payback) else None,
        "payback_valid_denominator_count": int(valid.sum()),
        "payback_non_positive_savings_count": int((savings.notna() & savings.le(0)).sum()),
        "payback_infinite_count": int((capex.notna() & ~valid).sum()),
        "truncation_threshold_years": None,
        "excluded_by_truncation_count": 0,
        "payback_definition": PAYBACK_DEFINITION,
        "payback_denominator": PAYBACK_DENOMINATOR,
        "payback_serialization_policy": PAYBACK_SERIALIZATION_POLICY,
    }


def validate_hybrid_assignments(
    frame: pd.DataFrame,
    *,
    hn_column: str = "assigned_heat_network",
    ashp_column: str = "assigned_ashp",
) -> None:
    missing = {hn_column, ashp_column}.difference(frame.columns)
    if missing:
        raise ValueError(f"Hybrid assignment columns are missing: {sorted(missing)}")
    hn = frame[hn_column].fillna(False).astype(bool)
    hp = frame[ashp_column].fillna(False).astype(bool)
    if (hn & hp).any():
        raise ValueError("Hybrid pathway contains double technology assignments")
    if (~(hn | hp)).any():
        raise ValueError("Hybrid pathway contains unassigned properties")
    if "hn_ready" in frame.columns and frame["hn_ready"].astype(bool).any() and not hn.any():
        raise ValueError("Hybrid pathway assigned zero heat networks despite HN-ready properties")
