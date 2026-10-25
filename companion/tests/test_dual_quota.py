import asyncio
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

from companion.codex_display.desktop import countdown
from companion.codex_display.desktop_worker import DesktopWorker
from companion.codex_display.main import SnapshotCache
from companion.codex_display.magpie_client import MagpieClient
from companion.codex_display.metrics import build_snapshot
from companion.codex_display.protocol import decode_command, encode_snapshot
from companion.codex_display.runtime import AlreadyRunningError, ServiceLock


class QuotaTests(unittest.TestCase):
    def snapshot(self, providers):
        return build_snapshot({"data": providers}, {}, now=1792828800, utc_offset_minutes=480)

    def test_only_codex_windows_feed_home_even_when_other_quota_is_lower(self):
        snapshot = self.snapshot([
            {"provider": "workbuddy", "windows": [{"name": "5 hours", "remaining": 1}]},
            {"provider": "codex", "windows": [
                {"name": "5 hours", "remaining": 51, "resetsAt": "2026-10-24T16:55:19+08:00"},
                {"name": "7 days", "remaining": 92, "resetsAt": "2026-10-31T11:55:19+08:00"}]}])
        self.assertEqual((snapshot.short_remaining_percent, snapshot.weekly_remaining_percent), (51, 92))
        self.assertEqual(snapshot.short_reset_at, int(datetime.fromisoformat("2026-10-24T08:55:19+00:00").timestamp()))
        self.assertEqual(snapshot.weekly_reset_at, int(datetime.fromisoformat("2026-10-31T03:55:19+00:00").timestamp()))

    def test_other_providers_are_never_used_as_codex_fallback(self):
        snapshot = self.snapshot([{"provider": "other", "windows": [{"name": "weekly", "remaining": 100}]}])
        self.assertEqual((snapshot.short_remaining_percent, snapshot.weekly_remaining_percent), (-1, -1))

    def test_partial_quota_does_not_invent_full_weekly_allowance(self):
        snapshot = self.snapshot([{"name": "Codex", "windows": [{"name": "5 hours", "remaining": 0}]}])
        self.assertEqual((snapshot.short_remaining_percent, snapshot.weekly_remaining_percent), (0, -1))

    def test_invalid_percent_is_unknown_and_ambiguous_reset_is_unknown(self):
        for value in (None, True, "80", float("nan"), float("inf")):
            with self.subTest(value=value):
                snapshot = self.snapshot([{"provider": "codex", "windows": [{"name": "5 hours", "remaining": value}]}])
                self.assertEqual(snapshot.short_remaining_percent, -1)
        for reset in ("bad", "2026-10-24T16:55:19", None):
            snapshot = self.snapshot([{"provider": "codex", "windows": [{"name": "weekly", "remaining": 85, "resetsAt": reset}]}])
            self.assertEqual(snapshot.weekly_reset_at, 0)

    def test_passed_reset_does_not_restore_percent_locally(self):
        snapshot = self.snapshot([{"provider": "codex", "windows": [{"name": "5 hours", "remaining": 0, "resetsAt": "2020-01-01T00:00:00Z"}]}])
        self.assertEqual(snapshot.short_remaining_percent, 0)
        self.assertIn("等待接口更新", countdown(snapshot.short_reset_at, now=1792828800))

    def test_sparse_yesterday_bucket_is_not_today(self):
        snapshot = build_snapshot({}, {"series": [{"time": "2026-10-23T00:00:00+08:00", "calls": 7, "input": 300}]}, now=1792828800, utc_offset_minutes=480)
        self.assertEqual((snapshot.calls_today, snapshot.tokens_today), (0, 0))

    def test_unicode_labels_shorten_but_quota_and_cost_remain_exact(self):
        snapshot = replace(self.snapshot([]), latest_model="模型"*30, top_model="模型"*30,
                           total_input=100000000000, total_cost_micros=10000000000,
                           short_remaining_percent=0, weekly_remaining_percent=100,
                           short_reset_at=1792828800, weekly_reset_at=1793433600)
        raw = encode_snapshot(snapshot, 123, sent_at=1792828810)
        payload = json.loads(raw)
        self.assertLessEqual(len(raw), 250)
        self.assertEqual(payload["q"], [0, 1792828800, 100, 1793433600])
        self.assertEqual(payload["x"][6], 10000000000)
        self.assertEqual(payload["t"], 1792828810)

    def test_unhashable_actions_fail_as_value_error(self):
        with self.assertRaises(ValueError):
            decode_command(b'{"v":4,"sid":1,"id":1,"a":[]}')

    def test_bad_endpoint_is_rejected_before_background_work(self):
        for url in ("", "localhost:3425", "file:///data", "http://host/#fragment"):
            with self.assertRaises(ValueError):
                MagpieClient(url)


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_invalidates_cached_data_and_does_not_mark_it_fresh(self):
        snapshot = build_snapshot({}, {}, now=1)
        cache = SnapshotCache(object(), 60)
        with patch("companion.codex_display.main.collect_snapshot", side_effect=[snapshot, RuntimeError("offline"), RuntimeError("offline")]):
            await cache.refresh()
            with self.assertRaises(RuntimeError):
                await cache.refresh()
            with self.assertRaises(RuntimeError):
                await cache.encoded()

    async def test_cached_snapshot_uses_send_clock_without_changing_reset(self):
        snapshot = replace(build_snapshot({}, {}, now=1), short_reset_at=1000)
        cache = SnapshotCache(object(), 60)
        with patch("companion.codex_display.main.collect_snapshot", return_value=snapshot), patch("companion.codex_display.main.time.time", return_value=30):
            await cache.refresh()
            payload = json.loads(await cache.encoded())
        self.assertEqual(payload["t"], 30)
        self.assertEqual(payload["q"][1], 1000)


class RuntimeTests(unittest.TestCase):
    def test_native_windows_lock_releases_and_excludes_second_instance(self):
        import os
        if os.name != 'nt':
            self.skipTest('Windows named mutex')
        name = 'Local\\MagpieDisplayTest' + str(os.getpid())
        with ServiceLock(name=name):
            with self.assertRaises(AlreadyRunningError):
                with ServiceLock(name=name):
                    self.fail('native mutex was not exclusive')
        with ServiceLock(name=name):
            pass

    def test_service_lock_exclusive_and_released_after_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sync.lock"
            with ServiceLock(path):
                with self.assertRaises(AlreadyRunningError):
                    with ServiceLock(path):
                        self.fail("lock was not exclusive")
            with ServiceLock(path):
                pass

    def test_worker_can_stop_and_restart_without_leaving_thread_alive(self):
        async def idle(*args):
            await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as directory, patch("companion.codex_display.desktop_worker.ServiceLock", lambda: ServiceLock(Path(directory)/"sync.lock")), patch.object(DesktopWorker, "_run", idle):
            worker = DesktopWorker(queue.Queue())
            for _ in range(3):
                worker.start("http://127.0.0.1:3425", "Magpie Display")
                worker.stop()
                worker.thread.join(timeout=3)
                self.assertFalse(worker.running)
                self.assertIsNone(worker.loop)

    def test_refresh_is_unavailable_when_stopped(self):
        self.assertFalse(DesktopWorker(queue.Queue()).refresh())


if __name__ == "__main__":
    unittest.main()
