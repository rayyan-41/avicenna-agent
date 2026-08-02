"""Console entry point.

Interim shim: delegates to the legacy typer app in avicenna.main until the
Textual harness CLI lands in Phase 8. Replaced wholesale at that point.
"""
from avicenna.main import app as _legacy_app


def main() -> None:
    _legacy_app()