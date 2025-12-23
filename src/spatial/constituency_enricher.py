"""
UK Postcode to Westminster Constituency Enrichment.

Uses the public postcodes.io API to map postcodes to Westminster
parliamentary constituencies and stores the result in a standard
CONSTITUENCY column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
import time

import pandas as pd
import requests
from loguru import logger


class ConstituencyEnricher:
    """Enrich EPC data with Westminster constituency names."""

    POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"

    def __init__(
        self,
        cache_file: Optional[Path] = None,
        batch_size: int = 100,
        pause_seconds: float = 0.05,
    ):
        self.cache_file = Path(cache_file) if cache_file else None
        self.batch_size = batch_size
        self.pause_seconds = pause_seconds
        self.cache: Dict[str, str] = {}

        if self.cache_file and self.cache_file.exists():
            try:
                cache_df = pd.read_csv(self.cache_file)
                self.cache = dict(zip(cache_df["postcode"], cache_df["constituency"]))
                logger.info(f"Loaded {len(self.cache):,} cached constituency lookups")
            except Exception as exc:
                logger.warning(f"Failed to load constituency cache: {exc}")

    @staticmethod
    def clean_postcode(postcode: Optional[str]) -> Optional[str]:
        """Standardize postcode format for lookups."""
        if pd.isna(postcode):
            return None

        cleaned = str(postcode).strip().upper().replace(" ", "")
        if len(cleaned) >= 5:
            cleaned = f"{cleaned[:-3]} {cleaned[-3:]}"
        return cleaned

    def _fetch_batch(self, postcodes: Iterable[str]) -> Dict[str, str]:
        """Fetch constituency names for a batch of postcodes."""
        response = requests.post(
            self.POSTCODES_IO_URL,
            json={"postcodes": list(postcodes)},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        results: Dict[str, str] = {}
        for item in payload.get("result", []):
            if not item or not item.get("result"):
                continue
            postcode = item.get("query")
            constituency = item["result"].get("parliamentary_constituency")
            if postcode and constituency:
                results[postcode] = constituency
        return results

    def _yield_batches(self, items: Iterable[str]) -> Iterable[Tuple[str, ...]]:
        items = list(items)
        for i in range(0, len(items), self.batch_size):
            yield tuple(items[i : i + self.batch_size])

    def enrich_dataframe(
        self,
        df: pd.DataFrame,
        postcode_column: str = "POSTCODE",
        constituency_column: str = "CONSTITUENCY",
    ) -> Tuple[pd.DataFrame, Dict[str, int]]:
        """Add Westminster constituency data based on postcode.

        Returns:
            Tuple of (enriched DataFrame, summary stats dict).
        """
        if postcode_column not in df.columns:
            logger.warning(f"Postcode column '{postcode_column}' not found; skipping constituency enrichment")
            return df, {"total": len(df), "filled": 0, "missing": len(df)}

        df = df.copy()
        cleaned_postcodes = df[postcode_column].apply(self.clean_postcode)
        df[postcode_column] = cleaned_postcodes

        constituency_series = df[constituency_column] if constituency_column in df.columns else pd.Series(pd.NA, index=df.index)
        for candidate in [
            "CONSTITUENCY_NAME",
            "WESTMINSTER_PARLIAMENTARY_CONSTITUENCY",
            "PCON_NAME",
        ]:
            if candidate in df.columns:
                constituency_series = constituency_series.fillna(df[candidate])
        df[constituency_column] = constituency_series

        missing_mask = df[constituency_column].isna() | (df[constituency_column].astype(str).str.strip() == "")
        lookup_postcodes = cleaned_postcodes[missing_mask].dropna().unique().tolist()

        # Fill from cache
        if lookup_postcodes:
            cached_series = cleaned_postcodes.map(self.cache)
            df.loc[missing_mask, constituency_column] = df.loc[missing_mask, constituency_column].fillna(cached_series)

        missing_mask = df[constituency_column].isna() | (df[constituency_column].astype(str).str.strip() == "")
        lookup_postcodes = cleaned_postcodes[missing_mask].dropna().unique().tolist()

        new_lookups = 0
        if lookup_postcodes:
            logger.info(f"Fetching constituencies for {len(lookup_postcodes):,} postcodes...")
            for batch in self._yield_batches(lookup_postcodes):
                try:
                    batch_results = self._fetch_batch(batch)
                except Exception as exc:
                    logger.warning(f"Failed constituency lookup for batch ({len(batch)} postcodes): {exc}")
                    continue

                if batch_results:
                    self.cache.update(batch_results)
                    new_lookups += len(batch_results)

                time.sleep(self.pause_seconds)

            if new_lookups:
                df.loc[missing_mask, constituency_column] = df.loc[missing_mask, constituency_column].fillna(
                    cleaned_postcodes.map(self.cache)
                )

        if self.cache_file:
            try:
                cache_df = pd.DataFrame(
                    sorted(self.cache.items()),
                    columns=["postcode", "constituency"],
                )
                cache_df.to_csv(self.cache_file, index=False)
            except Exception as exc:
                logger.warning(f"Failed to write constituency cache: {exc}")

        total = len(df)
        filled = df[constituency_column].notna().sum()
        missing = total - filled
        logger.info(
            "Constituency enrichment complete: "
            f"{filled:,}/{total:,} records populated ({(filled / total * 100) if total else 0:.1f}%)"
        )

        return df, {"total": int(total), "filled": int(filled), "missing": int(missing), "new_lookups": int(new_lookups)}
