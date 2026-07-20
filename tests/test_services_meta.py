"""Lightweight tests for diagnostic service constants."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES_PY = ROOT / "custom_components" / "panasonic_taiseia_local" / "services.py"


class ServicesMetaTest(unittest.TestCase):
    def test_service_name_constants(self) -> None:
        tree = ast.parse(SERVICES_PY.read_text(encoding="utf-8"))
        assigns = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        self.assertEqual(assigns.get("SERVICE_PROBE_DEVICE"), "probe_device")
        self.assertEqual(assigns.get("SERVICE_READ_SERVICE"), "read_service")
        self.assertEqual(assigns.get("SERVICE_WRITE_SERVICE"), "write_service")
        self.assertEqual(assigns.get("SERVICE_SCAN_LAN"), "scan_lan")


if __name__ == "__main__":
    unittest.main()
