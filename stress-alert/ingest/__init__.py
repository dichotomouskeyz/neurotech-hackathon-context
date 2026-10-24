"""Open-Motion ingest: a gated live station scan. The dashboard streams live data itself."""

from .omotion_source import start_live_scan

__all__ = ["start_live_scan"]
