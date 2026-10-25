import asyncio
import dataclasses
import json
import unittest
from unittest.mock import AsyncMock, patch

from companion.codex_display.actions import perform_action
from companion.codex_display.main import build_parser
from companion.codex_display.metrics import build_snapshot
from companion.codex_display.protocol import decode_command, encode_snapshot


class WindowsPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_focus_uses_windows_api_instead_of_macos_open(self):
        with patch('companion.codex_display.actions.platform.system', return_value='Windows'), \
             patch('companion.codex_display.actions._run', new_callable=AsyncMock) as run:
            run.return_value = (True, '')
            self.assertEqual(await perform_action('focus_magpie', AsyncMock()), (True, 'FOCUSED'))
            args = run.call_args.args
            self.assertTrue(args[0].endswith('powershell.exe'))
            self.assertIn('SetForegroundWindow', args[-1])

    async def test_unavailable_window_is_reported(self):
        with patch('companion.codex_display.actions.platform.system', return_value='Windows'), \
             patch('companion.codex_display.actions._run', new_callable=AsyncMock) as run:
            run.return_value = (False, '')
            self.assertEqual(await perform_action('focus_magpie', AsyncMock()),
                             (False, 'OPEN MAGPIE ON PC'))


class BudgetTests(unittest.TestCase):
    def test_large_account_and_unicode_names_fit_without_changing_numbers(self):
        snapshot = dataclasses.replace(
            build_snapshot({}, {}, now=1_800_000_000, utc_offset_minutes=480),
            latest_model='模型名称很长' * 4, top_model='另一个很长的模型名字' * 3,
            total_input=28447766, total_output=4239513, total_cache_read=937433965,
            total_reasoning=1323105, total_cost_micros=35028505,
            session_count=118, total_calls=5543, tokens_today=20567633,
        )
        payload = encode_snapshot(snapshot, 999999)
        self.assertLessEqual(len(payload), 250)
        parsed = json.loads(payload)
        self.assertEqual(parsed['d'], 20567633)
        self.assertEqual(parsed['x'][4], 937433965)
        self.assertEqual(parsed['x'][6], 35028505)

    def test_invalid_commands_are_rejected(self):
        for raw in [b'[]', b'null', b'3', b'{"v":4,"sid":true,"id":1,"a":"refresh"}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_command(raw)

    def test_watchdog_incompatible_intervals_are_rejected(self):
        for args in [['--heartbeat-seconds', '45'], ['--heartbeat-seconds', 'nan'],
                     ['--refresh-seconds', '0']]:
            with self.subTest(args=args), patch('sys.stderr'), self.assertRaises(SystemExit):
                build_parser().parse_args(args)


if __name__ == '__main__':
    unittest.main()
