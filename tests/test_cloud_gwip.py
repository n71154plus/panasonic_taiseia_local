"""Unit tests for EMS UserGetGWIP payload parsing."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stub() -> None:
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
    pkg_name = "panasonic_taiseia_local"
    if pkg_name not in sys.modules:
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = [str(ROOT / "custom_components" / "panasonic_taiseia_local")]
        sys.modules[pkg_name] = pkg_mod


_stub()
sys.path.insert(0, str(ROOT / "custom_components"))

from panasonic_taiseia_local.cloud import parse_gw_ip_payload  # noqa: E402


class ParseGwIpTests(unittest.TestCase):
    def test_quoted_ipv4(self) -> None:
        self.assertEqual(parse_gw_ip_payload('"192.168.0.104"'), "192.168.0.104")

    def test_bare_ipv4(self) -> None:
        self.assertEqual(parse_gw_ip_payload("10.0.0.5"), "10.0.0.5")

    def test_json_object(self) -> None:
        self.assertEqual(parse_gw_ip_payload({"IP": "192.168.1.20"}), "192.168.1.20")

    def test_json_string_object(self) -> None:
        self.assertEqual(
            parse_gw_ip_payload('{"GwIP":"192.168.50.8"}'), "192.168.50.8"
        )

    def test_reject_garbage(self) -> None:
        self.assertIsNone(parse_gw_ip_payload(""))
        self.assertIsNone(parse_gw_ip_payload("EmptyGWID"))
        self.assertIsNone(parse_gw_ip_payload("999.1.1.1"))


if __name__ == "__main__":
    unittest.main()
