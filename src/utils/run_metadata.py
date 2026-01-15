"""
Run Metadata Manager - Tracks property counts at each pipeline stage.

This module provides stage-by-stage count reconciliation to ensure data integrity
throughout the analysis pipeline. It addresses the audit finding that different
pipeline stages were producing different totals.

KEY COUNTS TRACKED:
- raw_loaded_count: Records loaded from raw EPC data
- after_validation_count: Records passing validation rules
- after_geocoding_count: Records with valid coordinates
- scenario_input_count: Records entering scenario modeling
- final_modeled_count: Records with completed scenario results

Each stage logs its count, and the metadata can be used by reports to pull
the appropriate total for their specific context.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger
import numpy as np


class RunMetadataManager:
    """
    Tracks and persists property counts at each pipeline stage.

    This class ensures data integrity by:
    1. Recording counts at each processing stage
    2. Detecting and warning about unexpected count drops
    3. Providing stage-specific totals for reports
    4. Creating an audit trail for count reconciliation
    """

    # Maximum acceptable drop percentage between stages before warning
    DEFAULT_DROP_THRESHOLD_PCT = 0.1

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the run metadata manager.

        Args:
            output_dir: Directory to save run_metadata.json
        """
        if output_dir is None:
            from config.config import DATA_OUTPUTS_DIR
            output_dir = DATA_OUTPUTS_DIR

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.metadata_path = self.output_dir / "run_metadata.json"

        self._metadata: Dict[str, Any] = {
            "run_timestamp": datetime.now().isoformat(),
            "pipeline_version": "1.0.0",
            "stage_counts": {},
            "count_drops": [],
            "warnings": [],
            "notes": [],
        }

        self._stage_order = [
            "raw_loaded_count",
            "after_validation_count",
            "after_geocoding_count",
            "scenario_input_count",
            "final_modeled_count",
        ]

        self._last_stage: Optional[str] = None
        self._last_count: Optional[int] = None

    def record_stage_count(
        self,
        stage_name: str,
        count: int,
        description: str = "",
        dataframe_source: str = "",
        drop_threshold_pct: float = DEFAULT_DROP_THRESHOLD_PCT,
        allow_drop: bool = False,
    ) -> None:
        """
        Record the property count at a specific pipeline stage.

        Args:
            stage_name: Identifier for this stage (e.g., 'after_validation_count')
            count: Number of properties at this stage
            description: Human-readable description of what this stage represents
            dataframe_source: Name of the dataframe/file this count was derived from
            drop_threshold_pct: Maximum acceptable drop from previous stage (as decimal)
            allow_drop: If True, don't warn even if drop exceeds threshold

        Raises:
            ValueError: If count drop exceeds threshold and allow_drop is False
        """
        stage_data = {
            "count": int(count),
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "source": dataframe_source,
        }

        # Check for count drop from previous stage
        if self._last_count is not None and self._last_stage is not None:
            drop = self._last_count - count
            drop_pct = (drop / self._last_count * 100) if self._last_count > 0 else 0

            stage_data["records_dropped"] = drop
            stage_data["drop_percentage"] = round(drop_pct, 4)
            stage_data["previous_stage"] = self._last_stage

            if drop > 0:
                drop_info = {
                    "from_stage": self._last_stage,
                    "to_stage": stage_name,
                    "dropped": drop,
                    "drop_pct": round(drop_pct, 4),
                }
                self._metadata["count_drops"].append(drop_info)

                if drop_pct > drop_threshold_pct * 100:
                    warning_msg = (
                        f"Significant count drop: {self._last_stage} → {stage_name}: "
                        f"{self._last_count:,} → {count:,} "
                        f"({drop:,} records, {drop_pct:.2f}%)"
                    )

                    if not allow_drop:
                        self._metadata["warnings"].append({
                            "type": "count_drop_exceeded_threshold",
                            "message": warning_msg,
                            "threshold_pct": drop_threshold_pct * 100,
                            "actual_pct": drop_pct,
                        })
                        logger.warning(warning_msg)
                    else:
                        logger.info(f"Count drop (allowed): {warning_msg}")

        self._metadata["stage_counts"][stage_name] = stage_data
        self._last_stage = stage_name
        self._last_count = count

        logger.info(f"Stage count recorded: {stage_name} = {count:,}")

    def add_note(self, note: str) -> None:
        """Add an explanatory note to the metadata."""
        self._metadata["notes"].append({
            "timestamp": datetime.now().isoformat(),
            "note": note,
        })

    def add_warning(self, warning: str, warning_type: str = "general") -> None:
        """Add a warning to the metadata."""
        self._metadata["warnings"].append({
            "timestamp": datetime.now().isoformat(),
            "type": warning_type,
            "message": warning,
        })
        logger.warning(warning)

    def get_stage_count(self, stage_name: str) -> Optional[int]:
        """Get the count for a specific stage."""
        stage_data = self._metadata["stage_counts"].get(stage_name, {})
        return stage_data.get("count")

    def get_final_count(self) -> int:
        """Get the final modeled count (or last recorded count)."""
        # Try final_modeled_count first
        final = self.get_stage_count("final_modeled_count")
        if final is not None:
            return final

        # Fall back to scenario_input_count
        scenario = self.get_stage_count("scenario_input_count")
        if scenario is not None:
            return scenario

        # Fall back to after_validation_count
        validation = self.get_stage_count("after_validation_count")
        if validation is not None:
            return validation

        # Return last recorded count
        if self._metadata["stage_counts"]:
            last_stage = list(self._metadata["stage_counts"].keys())[-1]
            return self._metadata["stage_counts"][last_stage].get("count", 0)

        return 0

    def set_metadata(self, key: str, value: Any) -> None:
        """Set arbitrary metadata."""
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get arbitrary metadata."""
        return self._metadata.get(key, default)

    def generate_reconciliation_table(self) -> str:
        """
        Generate a markdown table showing count reconciliation across stages.

        Returns:
            Markdown-formatted table string
        """
        lines = [
            "## Analysis Universe Reconciliation",
            "",
            "| Stage | Count | Drop | Drop % | Notes |",
            "|-------|-------|------|--------|-------|",
        ]

        for stage_name in self._stage_order:
            if stage_name in self._metadata["stage_counts"]:
                stage_data = self._metadata["stage_counts"][stage_name]
                count = stage_data.get("count", 0)
                dropped = stage_data.get("records_dropped", 0)
                drop_pct = stage_data.get("drop_percentage", 0)
                desc = stage_data.get("description", "")

                lines.append(
                    f"| {stage_name.replace('_', ' ').title()} | "
                    f"{count:,} | "
                    f"{dropped:,} | "
                    f"{drop_pct:.2f}% | "
                    f"{desc} |"
                )

        # Add explanation for drops
        if self._metadata["count_drops"]:
            lines.extend([
                "",
                "### Count Drop Explanations",
                "",
            ])
            for drop in self._metadata["count_drops"]:
                lines.append(
                    f"- **{drop['from_stage']} → {drop['to_stage']}**: "
                    f"{drop['dropped']:,} records ({drop['drop_pct']:.2f}%)"
                )

        # Add warnings
        if self._metadata["warnings"]:
            lines.extend([
                "",
                "### Warnings",
                "",
            ])
            for warning in self._metadata["warnings"]:
                lines.append(f"- ⚠️ {warning['message']}")

        return "\n".join(lines)

    def save(self) -> Path:
        """
        Save the metadata to run_metadata.json.

        Returns:
            Path to the saved file
        """
        self._metadata["last_updated"] = datetime.now().isoformat()

        # Add summary
        self._metadata["summary"] = {
            "total_stages_recorded": len(self._metadata["stage_counts"]),
            "total_warnings": len(self._metadata["warnings"]),
            "total_drops": len(self._metadata["count_drops"]),
            "final_count": self.get_final_count(),
        }

        # Convert numpy types to native Python types
        metadata_clean = self._convert_to_serializable(self._metadata)

        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata_clean, f, indent=2)

        logger.info(f"Run metadata saved to: {self.metadata_path}")
        return self.metadata_path

    def _convert_to_serializable(self, obj: Any) -> Any:
        """Convert numpy types to JSON-serializable types."""
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: self._convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._convert_to_serializable(item) for item in obj]
        return obj

    @classmethod
    def load(cls, metadata_path: Path) -> "RunMetadataManager":
        """
        Load existing metadata from file.

        Args:
            metadata_path: Path to run_metadata.json

        Returns:
            RunMetadataManager instance with loaded data
        """
        manager = cls(output_dir=metadata_path.parent)

        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                manager._metadata = json.load(f)

            # Restore last stage/count tracking
            if manager._metadata["stage_counts"]:
                stages = list(manager._metadata["stage_counts"].keys())
                manager._last_stage = stages[-1]
                manager._last_count = manager._metadata["stage_counts"][stages[-1]].get("count")

            logger.info(f"Loaded run metadata from: {metadata_path}")

        return manager


def get_total_properties_from_metadata(metadata_path: Optional[Path] = None) -> int:
    """
    Utility function to get total properties from run_metadata.json.

    This should be used by reports and dashboard builders to get the
    appropriate property count instead of hard-coding values.

    Args:
        metadata_path: Optional path to run_metadata.json

    Returns:
        Total properties count (0 if not available)
    """
    if metadata_path is None:
        from config.config import DATA_OUTPUTS_DIR
        metadata_path = DATA_OUTPUTS_DIR / "run_metadata.json"

    if not metadata_path.exists():
        logger.warning(f"run_metadata.json not found at {metadata_path}")
        return 0

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # Prefer final_modeled_count, fall back to scenario_input_count, then after_validation_count
        stage_counts = metadata.get("stage_counts", {})

        for stage in ["final_modeled_count", "scenario_input_count", "after_validation_count"]:
            if stage in stage_counts:
                return stage_counts[stage].get("count", 0)

        return metadata.get("summary", {}).get("final_count", 0)

    except Exception as e:
        logger.warning(f"Error loading run_metadata.json: {e}")
        return 0
