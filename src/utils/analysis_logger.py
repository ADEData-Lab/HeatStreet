"""
Analysis Logger - Tracks and logs all analysis phases and results
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import numpy as np
from loguru import logger


def convert_to_json_serializable(obj: Any) -> Any:
    """
    Recursively convert numpy types and other non-serializable types to JSON-serializable types.

    Args:
        obj: Object to convert

    Returns:
        JSON-serializable version of the object
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_to_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_to_json_serializable(item) for item in obj]
    else:
        return obj


class AnalysisLogger:
    """
    Tracks all analysis phases, their success/failure status, and key metrics.
    Generates a comprehensive analysis log for output.
    """

    def __init__(self, output_dir: Path = None):
        """
        Initialize the analysis logger.

        Args:
            output_dir: Directory where the analysis log will be saved
        """
        if output_dir is None:
            from config.config import DATA_OUTPUTS_DIR
            output_dir = DATA_OUTPUTS_DIR

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.start_time = datetime.now()
        self.phases: List[Dict[str, Any]] = []
        self.current_phase: Optional[Dict[str, Any]] = None
        self.metadata: Dict[str, Any] = {
            'analysis_start': self.start_time.isoformat(),
            'total_properties': 0,
            'data_source': 'EPC API',
            'analysis_type': 'Edwardian Terraced Housing - Heat Street Analysis'
        }

    def start_phase(self, phase_name: str, description: str = ""):
        """
        Start tracking a new analysis phase.

        Args:
            phase_name: Name of the phase (e.g., "Data Download", "Validation")
            description: Optional description of what this phase does
        """
        if self.current_phase is not None and self.current_phase['status'] == 'in_progress':
            # Auto-complete previous phase if forgotten
            self.complete_phase(success=True, message="Auto-completed")

        self.current_phase = {
            'phase_number': len(self.phases) + 1,
            'phase_name': phase_name,
            'description': description,
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'duration_seconds': None,
            'status': 'in_progress',
            'success': None,
            'message': "",
            'metrics': {},
            'outputs': []
        }

        logger.info(f"Starting analysis phase {self.current_phase['phase_number']}: {phase_name}")

    def add_metric(self, key: str, value: Any, description: str = ""):
        """
        Add a metric to the current phase.

        Args:
            key: Metric name (e.g., "records_downloaded", "validation_rate")
            value: Metric value
            description: Optional description of the metric
        """
        if self.current_phase is None:
            logger.warning(f"Cannot add metric '{key}' - no active phase")
            return

        self.current_phase['metrics'][key] = {
            'value': value,
            'description': description
        }

    def add_output(
        self,
        output_path: str,
        output_type: str = "file",
        description: str = "",
        calculation_steps: Optional[List[str]] = None,
    ):
        """
        Add an output file/artifact to the current phase and generate
        companion Markdown documentation explaining how it was produced.

        Args:
            output_path: Path to the output file
            output_type: Type of output (e.g., "csv", "png", "report")
            description: Description of the output
            calculation_steps: Optional step-by-step notes on how the result was calculated
        """
        if self.current_phase is None:
            logger.warning(f"Cannot add output '{output_path}' - no active phase")
            return

        markdown_path = self._create_output_markdown(
            output_path=output_path,
            output_type=output_type,
            description=description,
            calculation_steps=calculation_steps,
        )

        self.current_phase['outputs'].append({
            'path': str(output_path),
            'type': output_type,
            'description': description,
            'documentation': str(markdown_path) if markdown_path else None,
        })

    def complete_phase(self, success: bool = True, message: str = ""):
        """
        Mark the current phase as complete.

        Args:
            success: Whether the phase completed successfully
            message: Optional completion message or error description
        """
        if self.current_phase is None:
            logger.warning("Cannot complete phase - no active phase")
            return

        end_time = datetime.now()
        start_time = datetime.fromisoformat(self.current_phase['start_time'])
        duration = (end_time - start_time).total_seconds()

        self.current_phase['end_time'] = end_time.isoformat()
        self.current_phase['duration_seconds'] = duration
        self.current_phase['status'] = 'completed' if success else 'failed'
        self.current_phase['success'] = success
        self.current_phase['message'] = message

        self.phases.append(self.current_phase)

        status_emoji = "✓" if success else "✗"
        logger.info(f"{status_emoji} Phase {self.current_phase['phase_number']} completed: {self.current_phase['phase_name']} ({duration:.1f}s)")

        self.current_phase = None

    def _format_metric_value(self, value: Any) -> str:
        """
        Convert a metric value into a human-friendly string.

        Args:
            value: The metric value

        Returns:
            Formatted string representation
        """
        if isinstance(value, float):
            if abs(value) >= 1000:
                return f"{value:,.0f}"
            return f"{value:.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)

    def _create_output_markdown(
        self,
        output_path: str,
        output_type: str,
        description: str,
        calculation_steps: Optional[List[str]],
    ) -> Optional[Path]:
        """
        Build a Markdown companion file that explains how an output was created.

        Args:
            output_path: Path to the primary output
            output_type: Type of output (e.g., csv, png)
            description: Short explanation of the output content
            calculation_steps: Optional detailed steps to include

        Returns:
            Path to the created Markdown file, or None if creation failed
        """
        try:
            path_obj = Path(output_path)

            if path_obj.suffix:
                markdown_path = path_obj.with_name(f"{path_obj.stem}_calculation.md")
            else:
                markdown_path = path_obj / "calculation_notes.md"

            markdown_path.parent.mkdir(parents=True, exist_ok=True)

            phase_name = "Unknown phase"
            phase_description = ""
            metrics = {}

            if self.current_phase:
                phase_name = self.current_phase.get('phase_name', phase_name)
                phase_description = self.current_phase.get('description', "")
                metrics = self.current_phase.get('metrics', {})

            steps = list(calculation_steps) if calculation_steps else []

            if not steps:
                if phase_description:
                    steps.append(
                        f"Ran the '{phase_name}' phase: {phase_description}."
                    )
                else:
                    steps.append(
                        f"Ran the '{phase_name}' phase to prepare this output."
                    )

                if metrics:
                    steps.append(
                        "Checked the following key numbers to make sure the calculations looked right:"
                    )
                    for metric_key, metric_data in metrics.items():
                        metric_value = metric_data.get('value')
                        metric_desc = metric_data.get('description') or metric_key.replace('_', ' ')
                        formatted_value = self._format_metric_value(metric_value)
                        steps.append(f"- {metric_desc} ({metric_key}): {formatted_value}")

                steps.append(
                    "Saved the finished result so later steps in the pipeline can reuse it."
                )

            lines = [
                f"# Output Documentation: {path_obj.name}",
                "",
                f"**Output file:** {path_obj}",
                f"**Created:** {datetime.now().isoformat()}",
                f"**Phase:** {phase_name}",
                f"**Output type:** {output_type}",
                "",
                "**What this file contains**",
                description or "This file stores results from the analysis pipeline in an easy-to-reuse format.",
                "",
                "## How this result was calculated",
            ]

            lines.extend([f"- {step}" for step in steps])

            if metrics:
                lines.extend([
                    "",
                    "## Key checks and numbers",
                ])

                for metric_key, metric_data in metrics.items():
                    metric_value = metric_data.get('value')
                    metric_desc = metric_data.get('description') or metric_key.replace('_', ' ')
                    formatted_value = self._format_metric_value(metric_value)
                    lines.append(f"- {metric_desc} ({metric_key}): {formatted_value}")

            lines.extend([
                "",
                "This note is generated automatically so anyone opening the data file can understand, in plain language, how it was produced.",
            ])

            with open(markdown_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))

            logger.info(f"Documentation saved alongside output: {markdown_path}")
            return markdown_path

        except Exception as e:
            logger.warning(f"Could not create documentation for {output_path}: {e}")
            return None

    def skip_phase(self, phase_name: str, reason: str = ""):
        """
        Record a skipped phase.

        Args:
            phase_name: Name of the skipped phase
            reason: Reason for skipping
        """
        self.phases.append({
            'phase_number': len(self.phases) + 1,
            'phase_name': phase_name,
            'description': "",
            'start_time': datetime.now().isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_seconds': 0,
            'status': 'skipped',
            'success': None,
            'message': reason,
            'metrics': {},
            'outputs': []
        })

        logger.info(f"⊘ Phase skipped: {phase_name} - {reason}")

    def set_metadata(self, key: str, value: Any):
        """
        Set metadata for the entire analysis run.

        Args:
            key: Metadata key
            value: Metadata value
        """
        self.metadata[key] = value

    def generate_text_summary(self) -> str:
        """
        Generate a human-readable text summary of the analysis.

        Returns:
            Formatted text summary
        """
        lines = []
        lines.append("=" * 80)
        lines.append("ANALYSIS LOG - Heat Street EPC Analysis")
        lines.append("=" * 80)
        lines.append("")

        # Metadata
        lines.append("ANALYSIS METADATA")
        lines.append("-" * 80)
        for key, value in self.metadata.items():
            lines.append(f"{key}: {value}")
        lines.append("")

        # Calculate total duration
        if self.phases:
            total_duration = sum(p.get('duration_seconds', 0) for p in self.phases if p.get('duration_seconds'))
            lines.append(f"Total Analysis Duration: {total_duration/60:.1f} minutes ({total_duration:.0f} seconds)")
            lines.append("")

        # Phase Summary
        lines.append("PHASE SUMMARY")
        lines.append("-" * 80)

        successful = sum(1 for p in self.phases if p.get('success') is True)
        failed = sum(1 for p in self.phases if p.get('success') is False)
        skipped = sum(1 for p in self.phases if p.get('status') == 'skipped')

        lines.append(f"Total Phases: {len(self.phases)}")
        lines.append(f"  Successful: {successful}")
        lines.append(f"  Failed: {failed}")
        lines.append(f"  Skipped: {skipped}")
        lines.append("")

        # Detailed Phase Information
        lines.append("DETAILED PHASE INFORMATION")
        lines.append("=" * 80)

        for phase in self.phases:
            lines.append("")
            lines.append(f"Phase {phase['phase_number']}: {phase['phase_name']}")
            lines.append("-" * 80)

            if phase['description']:
                lines.append(f"Description: {phase['description']}")

            # Status
            status_symbol = {
                'completed': '✓ COMPLETED',
                'failed': '✗ FAILED',
                'skipped': '⊘ SKIPPED',
                'in_progress': '⋯ IN PROGRESS'
            }.get(phase['status'], phase['status'].upper())

            lines.append(f"Status: {status_symbol}")

            if phase.get('message'):
                lines.append(f"Message: {phase['message']}")

            # Timing
            if phase.get('duration_seconds') is not None:
                duration = phase['duration_seconds']
                if duration < 60:
                    lines.append(f"Duration: {duration:.1f} seconds")
                else:
                    lines.append(f"Duration: {duration/60:.1f} minutes ({duration:.0f} seconds)")

            # Metrics
            if phase.get('metrics'):
                lines.append("")
                lines.append("Metrics:")
                for metric_key, metric_data in phase['metrics'].items():
                    value = metric_data['value']
                    desc = metric_data.get('description', '')

                    # Format value
                    if isinstance(value, float):
                        if value > 1000:
                            value_str = f"{value:,.0f}"
                        else:
                            value_str = f"{value:.2f}"
                    elif isinstance(value, int):
                        value_str = f"{value:,}"
                    else:
                        value_str = str(value)

                    if desc:
                        lines.append(f"  • {metric_key}: {value_str} - {desc}")
                    else:
                        lines.append(f"  • {metric_key}: {value_str}")

            # Outputs
            if phase.get('outputs'):
                lines.append("")
                lines.append("Outputs Generated:")
                for output in phase['outputs']:
                    path = output['path']
                    output_type = output.get('type', 'file')
                    desc = output.get('description', '')

                    if desc:
                        lines.append(f"  • [{output_type}] {path}")
                        lines.append(f"    {desc}")
                    else:
                        lines.append(f"  • [{output_type}] {path}")

        lines.append("")
        lines.append("=" * 80)
        lines.append(f"Analysis Log Generated: {datetime.now().isoformat()}")
        lines.append("=" * 80)

        return "\n".join(lines)

    def save_log(self, filename: str = "analysis_log.txt"):
        """
        Save the analysis log to a text file.

        Args:
            filename: Name of the log file

        Returns:
            Path to the saved log file
        """
        # Update end time metadata
        self.metadata['analysis_end'] = datetime.now().isoformat()
        total_duration = (datetime.now() - self.start_time).total_seconds()
        self.metadata['total_duration_seconds'] = total_duration
        self.metadata['total_duration_minutes'] = total_duration / 60

        # Generate text summary
        summary = self.generate_text_summary()

        # Save text log
        log_path = self.output_dir / filename
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(summary)

        logger.info(f"Analysis log saved to: {log_path}")

        # Also save JSON version for programmatic access
        json_path = self.output_dir / filename.replace('.txt', '.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            # Convert numpy types to native Python types for JSON serialization
            serializable_data = convert_to_json_serializable({
                'metadata': self.metadata,
                'phases': self.phases
            })
            json.dump(serializable_data, f, indent=2)

        logger.info(f"Analysis log (JSON) saved to: {json_path}")

        return log_path

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics about the analysis.

        Returns:
            Dictionary of summary statistics
        """
        successful = sum(1 for p in self.phases if p.get('success') is True)
        failed = sum(1 for p in self.phases if p.get('success') is False)
        skipped = sum(1 for p in self.phases if p.get('status') == 'skipped')
        total_duration = sum(p.get('duration_seconds', 0) for p in self.phases if p.get('duration_seconds'))

        return {
            'total_phases': len(self.phases),
            'successful_phases': successful,
            'failed_phases': failed,
            'skipped_phases': skipped,
            'total_duration_seconds': total_duration,
            'total_duration_minutes': total_duration / 60,
            'overall_success': failed == 0 and successful > 0
        }
