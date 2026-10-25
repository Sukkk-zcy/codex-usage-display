import unittest

from companion.codex_display.metrics import build_snapshot


class MetricsTests(unittest.TestCase):
    def test_builds_snapshot_from_magpie_shapes(self):
        now = 1_800_000_000
        quotas = {
            "data": [
                {"windows": [{"name": "7 days", "remaining": 80}]},
                {
                    "windows": [
                        {
                            "name": "5 hours",
                            "remaining": 42.4,
                            "resetsAt": "2027-01-15T10:00:00Z",
                        },
                        {"name": "Limit", "remaining": 100, "unlimited": True},
                    ]
                },
            ]
        }
        usage = {
            "series": [
                {"input": 10, "output": 2, "cache_read": 3},
                {
                    "input": 100,
                    "output": 20,
                    "reasoning": 5,
                    "cache_read": 30,
                    "calls": 7,
                    "errors": 2,
                    "timed": 5,
                    "ttft_ms": 6250,
                },
            ]
        }
        requests = {
            "rows": [
                {
                    "served": "gpt-5.6-sol",
                    "status": 200,
                    "ms": 9876,
                }
            ]
        }
        snapshot = build_snapshot(
            quotas,
            usage,
            requests,
            now=now,
            utc_offset_minutes=480,
        )

        self.assertEqual(snapshot.remaining_percent, 42)
        self.assertEqual(snapshot.limit_window_minutes, 300)
        self.assertGreater(snapshot.quota_reset_seconds, 0)
        self.assertEqual(snapshot.tokens_today, 155)
        self.assertEqual(snapshot.tokens_7d, 170)
        self.assertEqual(snapshot.calls_today, 7)
        self.assertEqual(snapshot.errors_today, 2)
        self.assertEqual(snapshot.success_permille, 714)
        self.assertEqual(snapshot.average_ttft_ms, 1250)
        self.assertEqual(snapshot.latest_model, "gpt-5.6-sol")
        self.assertEqual(snapshot.latest_status, 200)
        self.assertEqual(snapshot.latest_latency_ms, 9876)
        self.assertFalse(snapshot.latest_failed)

    def test_empty_responses_use_safe_defaults(self):
        snapshot = build_snapshot(
            {},
            {},
            now=1,
            utc_offset_minutes=0,
        )
        self.assertEqual(snapshot.remaining_percent, 100)
        self.assertEqual(snapshot.tokens_today, 0)
        self.assertEqual(snapshot.success_permille, 1000)
        self.assertEqual(snapshot.latest_model, "")


if __name__ == "__main__":
    unittest.main()
