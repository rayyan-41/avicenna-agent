"""Stdio bridge between the Python agent core and the TypeScript frontend."""

from __future__ import annotations

from avicenna.bridge.protocol import PROTOCOL_VERSION
from avicenna.bridge.server import Bridge, BridgeError, main

__all__ = ["PROTOCOL_VERSION", "Bridge", "BridgeError", "main"]
