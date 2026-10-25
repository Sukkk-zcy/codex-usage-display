import json
import unittest

from companion.codex_display.metrics import Snapshot
from companion.codex_display.protocol import (
    decode_command,
    encode_result,
    encode_snapshot,
)


class ProtocolTests(unittest.TestCase):
    def test_snapshot_fits_single_negotiated_ble_packet(self):
        snapshot = Snapshot(
            generated_at=1_800_000_000,
            utc_offset_minutes=480,
            remaining_percent=96,
            limit_window_minutes=10080,
            quota_reset_seconds=604800,
            tokens_today=123456789,
            tokens_7d=987654321,
            errors_today=3,
            calls_today=12,
            success_permille=750,
            average_ttft_ms=12345,
            latest_model="remote-model-with-a-long-name",
            latest_status=503,
            latest_latency_ms=65432,
            latest_failed=True,
            session_count=40,
            total_calls=500,
            total_input=123456,
            total_output=23456,
            total_cache_read=987654,
            total_reasoning=34567,
            total_cost_micros=6110000,
            cache_hit_permille=889,
            top_model="gpt-5.6-sol",
            top_model_calls=450,
        )
        payload = encode_snapshot(snapshot, 42)
        decoded = json.loads(payload)
        self.assertLessEqual(len(payload), 250)
        self.assertEqual(decoded["r"], 96)
        self.assertEqual(decoded["v"], 4)
        self.assertEqual(decoded["f"], 12)
        self.assertEqual(decoded["z"], 3)
        self.assertEqual(decoded["y"], 750)
        self.assertEqual(decoded["m"], "remote-model-with-a-lon")
        self.assertEqual(decoded["b"], 1)
        self.assertEqual(decoded["x"][0], 40)
        self.assertEqual(decoded["x"][7], 889)
        self.assertEqual(decoded["x"][8], "gpt-5.6-sol")

    def test_accepts_allowlisted_command(self):
        command = decode_command(b'{"v":4,"sid":9,"id":7,"a":"refresh"}')
        self.assertEqual(command["id"], 7)
        self.assertEqual(command["a"], "refresh")

    def test_rejects_unknown_action(self):
        with self.assertRaisesRegex(ValueError, "不允许"):
            decode_command(b'{"v":4,"sid":9,"id":7,"a":"shell"}')

    def test_rejects_wrong_protocol(self):
        with self.assertRaisesRegex(ValueError, "协议版本"):
            decode_command(b'{"v":3,"sid":9,"id":7,"a":"refresh"}')

    def test_result_is_bounded(self):
        payload = encode_result(8, False, "x" * 100)
        decoded = json.loads(payload)
        self.assertEqual(decoded["ok"], 0)
        self.assertEqual(len(decoded["m"]), 48)


if __name__ == "__main__":
    unittest.main()
