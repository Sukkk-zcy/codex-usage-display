import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from companion.codex_display.ble import BleCompanion
from companion.codex_display.constants import SERVICE_UUID
from companion.codex_display.errors import PairingRequiredError


class FakeBleClient:
    def __init__(self, expected_writes):
        self.is_connected = True
        self.expected_writes = expected_writes
        self.writes = []
        self.services = SimpleNamespace(get_characteristic=lambda uuid: object())

    async def write_gatt_char(self, uuid, payload, response):
        self.writes.append((uuid, payload, response))
        if len(self.writes) >= self.expected_writes:
            self.is_connected = False


class HangingBleClient:
    is_connected = True

    async def write_gatt_char(self, uuid, payload, response):
        await asyncio.Event().wait()

    async def disconnect(self):
        await asyncio.Event().wait()


class BleTests(unittest.IsolatedAsyncioTestCase):
    async def test_power_loss_then_three_transient_errors_recovers_after_prior_success(self):
        reports = []
        bridge = BleCompanion(AsyncMock(return_value=b'{}'), AsyncMock(),
                              on_status=lambda phase,message: reports.append((phase,message)))
        bridge._locate_device = AsyncMock(return_value=SimpleNamespace(name='Magpie Display', address='00:00:00:00:00:00'))
        bridge._disconnect = AsyncMock()
        attempts = 0
        clients = []
        def factory(*args, **kwargs):
            client = SimpleNamespace(connect=AsyncMock(), write_gatt_char=AsyncMock())
            clients.append(client)
            return client
        async def connection(client, disconnected):
            nonlocal attempts
            attempts += 1
            if attempts in (1, 5):
                await bridge._send_status(client)
                if attempts == 5:
                    raise asyncio.CancelledError()
                return  # First healthy session ends when the peripheral loses power.
            raise RuntimeError('Could not start notify: Unreachable')
        bridge._run_connection = connection
        with patch('companion.codex_display.ble.platform.system', return_value='Linux'), \
             patch('bleak.BleakClient', side_effect=factory), \
             patch('companion.codex_display.ble.asyncio.sleep', new=AsyncMock()) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await bridge.run_forever()
        self.assertEqual(attempts, 5)
        self.assertEqual(bridge._disconnect.await_count, 5)
        self.assertEqual(len({id(c) for c in clients}), 5)
        self.assertIn(15, [call.args[0] for call in sleep.await_args_list])
        self.assertIn('recovering', [phase for phase,message in reports])
        self.assertEqual(reports[-1][0], 'connected')

    async def test_remote_disconnect_still_disposes_retained_gatt_services(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        client = SimpleNamespace(is_connected=False, services=object(), disconnect=AsyncMock())
        await bridge._disconnect(client)
        client.disconnect.assert_awaited_once()

    @unittest.skipUnless(__import__('sys').platform == 'win32', 'WinRT SDK disposal')
    async def test_winrt_sdk_closes_native_service_even_after_radio_link_is_closed(self):
        from bleak import BleakClient
        from companion.codex_display.windows_devices import device_from_address
        client = BleakClient(device_from_address(1, 'Test endpoint'))
        service = SimpleNamespace(obj=Mock())
        requester = Mock()
        client._backend.services = [service]
        client._backend._requester = requester
        self.assertFalse(client.is_connected)
        await BleCompanion(AsyncMock(), AsyncMock())._disconnect(client)
        service.obj.close.assert_called_once()
        requester.close.assert_called_once()
        self.assertIsNone(client._backend.services)

    async def test_failed_connection_without_services_needs_no_disposal(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        client = SimpleNamespace(is_connected=False, services=None, disconnect=AsyncMock())
        await bridge._disconnect(client)
        client.disconnect.assert_not_awaited()

    async def test_explicit_authentication_failure_still_pauses_after_prior_success(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        bridge._has_synchronized = True
        bridge._locate_device = AsyncMock(return_value=SimpleNamespace(name='Magpie Display', address='00:00:00:00:00:00'))
        bridge._disconnect = AsyncMock()
        client = SimpleNamespace(connect=AsyncMock(side_effect=RuntimeError('Authentication failed')))
        with patch('companion.codex_display.ble.platform.system', return_value='Linux'), \
             patch('bleak.BleakClient', return_value=client) as factory:
            with self.assertRaises(PairingRequiredError):
                await bridge.run_forever()
        self.assertEqual(factory.call_count, 1)
        bridge._disconnect.assert_awaited_once()

    async def test_late_old_disconnect_callback_cannot_clear_new_connection(self):
        bridge = BleCompanion(AsyncMock(return_value=b'{}'), AsyncMock())
        bridge._locate_device = AsyncMock(return_value=SimpleNamespace(name='Magpie Display', address='00:00:00:00:00:00'))
        bridge._disconnect = AsyncMock()
        callbacks = []
        def factory(*args, **kwargs):
            callbacks.append(kwargs['disconnected_callback'])
            return SimpleNamespace(connect=AsyncMock(), write_gatt_char=AsyncMock())
        async def connection(client, disconnected):
            await bridge._send_status(client)
            bridge.connected_event.set()
            if len(callbacks) == 1:
                callbacks[0](client)
                self.assertFalse(bridge.connected_event.is_set())
                return
            callbacks[0](client)
            self.assertTrue(bridge.connected_event.is_set())
            self.assertFalse(disconnected.is_set())
            raise asyncio.CancelledError()
        bridge._run_connection = connection
        with patch('companion.codex_display.ble.platform.system', return_value='Linux'), \
             patch('bleak.BleakClient', side_effect=factory), \
             patch('companion.codex_display.ble.asyncio.sleep', new=AsyncMock()):
            with self.assertRaises(asyncio.CancelledError):
                await bridge.run_forever()

    async def test_unpaired_device_never_starts_a_connection(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        bridge._locate_device = AsyncMock(return_value=object())
        with patch('companion.codex_display.ble.platform.system', return_value='Windows'), \
             patch('companion.codex_display.windows_devices.require_paired', new=AsyncMock(side_effect=PairingRequiredError('请配对'))), \
             patch('bleak.BleakClient') as factory:
            with self.assertRaises(PairingRequiredError):
                await bridge.run_forever()
        factory.assert_not_called()

    async def test_repeated_encrypted_setup_failure_stops_instead_of_retrying_forever(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        bridge._locate_device = AsyncMock(return_value=SimpleNamespace(name='Magpie Display', address='00:00:00:00:00:00'))
        bridge._run_connection = AsyncMock(side_effect=RuntimeError('Could not start notify: Unreachable'))
        bridge._disconnect = AsyncMock()
        client = SimpleNamespace(connect=AsyncMock())
        with patch('companion.codex_display.ble.platform.system', return_value='Linux'), \
             patch('bleak.BleakClient', return_value=client) as factory, \
             patch('companion.codex_display.ble.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(PairingRequiredError, '自动连接已暂停'):
                await bridge.run_forever()
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(bridge._disconnect.await_count, 3)

    async def test_repeated_gatt_discovery_failure_also_pauses_before_connection_finishes(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        bridge._locate_device = AsyncMock(return_value=SimpleNamespace(name='Magpie Display', address='00:00:00:00:00:00'))
        bridge._disconnect = AsyncMock()
        client = SimpleNamespace(connect=AsyncMock(side_effect=RuntimeError('Could not get GATT services: Unreachable')))
        with patch('companion.codex_display.ble.platform.system', return_value='Linux'), \
             patch('bleak.BleakClient', return_value=client) as factory, \
             patch('companion.codex_display.ble.asyncio.sleep', new=AsyncMock()):
            with self.assertRaises(PairingRequiredError):
                await bridge.run_forever()
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(bridge._disconnect.await_count, 3)

    async def test_pairing_probe_closes_native_handle_without_initiating_gatt(self):
        import sys
        from companion.codex_display.windows_devices import require_paired
        native = SimpleNamespace(device_information=SimpleNamespace(pairing=SimpleNamespace(is_paired=False)), close=Mock())
        module = SimpleNamespace(BluetoothLEDevice=SimpleNamespace(from_bluetooth_address_async=AsyncMock(return_value=native)))
        with patch.dict(sys.modules, {'winrt.windows.devices.bluetooth': module}):
            with self.assertRaises(PairingRequiredError):
                await require_paired(SimpleNamespace(address='20:9B:A9:6D:7C:12'))
        native.close.assert_called_once()

    def test_pairing_button_waits_for_worker_shutdown_before_opening_settings(self):
        from companion.codex_display.desktop import DesktopApp
        app = object.__new__(DesktopApp)
        app.worker = SimpleNamespace(running=True)
        app.stop = Mock()
        app.enter_pairing_mode = Mock()
        app.status = Mock()
        app.detail = Mock()
        app.bluetooth()
        app.stop.assert_called_once()
        app.enter_pairing_mode.assert_not_called()
        app.worker.running = False
        app.bluetooth()
        app.enter_pairing_mode.assert_called_once()

    async def test_new_scan_keeps_last_connection_failure_visible(self):
        reports = []
        bridge = BleCompanion(AsyncMock(), AsyncMock(), on_status=lambda phase,message: reports.append((phase,message)))
        bridge._report('error', '设备配对失败')
        bridge._prefer_scan = True
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=None))
        await bridge._locate_device(scanner)
        self.assertEqual(reports[-1][0], 'scanning')
        self.assertIn('设备配对失败', reports[-1][1])
        bridge._report('connected', '已发送')
        bridge._report('scanning', '重新扫描')
        self.assertNotIn('设备配对失败', reports[-1][1])

    async def test_missing_gatt_characteristic_requests_fresh_discovery(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        client = FakeBleClient(expected_writes=1)
        client.services = SimpleNamespace(get_characteristic=lambda uuid: None)
        client.start_notify = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, '设备服务记录不完整'):
            await bridge._run_connection(client, asyncio.Event())
        self.assertTrue(bridge._refresh_services)
        client.start_notify.assert_not_awaited()

    def test_missing_name_still_matches_display_service(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        self.assertTrue(bridge._matches_device(SimpleNamespace(name=None),
            SimpleNamespace(local_name=None, service_uuids=[SERVICE_UUID.upper()])))

    def test_stale_windows_name_does_not_hide_live_scan_name(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        self.assertTrue(bridge._matches_device(SimpleNamespace(name='Old cached name'),
            SimpleNamespace(local_name='Magpie Display', service_uuids=[])))

    def test_custom_name_does_not_match_another_display_by_uuid_alone(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock(), device_name='My second display')
        self.assertFalse(bridge._matches_device(SimpleNamespace(name='Magpie Display'),
            SimpleNamespace(local_name='Magpie Display', service_uuids=[SERVICE_UUID])))

    async def test_restart_reuses_endpoint_without_waiting_for_advertisement(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        known = object()
        bridge._known_device = known
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=None))
        self.assertIs(await bridge._locate_device(scanner), known)
        scanner.find_device_by_filter.assert_not_awaited()

    async def test_failed_connection_scans_then_falls_back_when_device_is_already_linked(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        known = object()
        bridge._known_device = known
        bridge._prefer_scan = True
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=None))
        self.assertIs(await bridge._locate_device(scanner), known)
        scanner.find_device_by_filter.assert_awaited_once()
        self.assertFalse(bridge._prefer_scan)

    async def test_cold_start_recovers_windows_endpoint_without_advertisement(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=None))
        known = object()
        with patch('companion.codex_display.ble.platform.system', return_value='Windows'), \
             patch('companion.codex_display.windows_devices.find_known_device', new=AsyncMock(return_value=known)):
            self.assertIs(await bridge._locate_device(scanner), known)
        scanner.find_device_by_filter.assert_not_awaited()

    async def test_new_advertisement_replaces_outdated_endpoint(self):
        bridge = BleCompanion(AsyncMock(), AsyncMock())
        bridge._known_device = object()
        bridge._prefer_scan = True
        fresh = object()
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=fresh))
        self.assertIs(await bridge._locate_device(scanner), fresh)
        self.assertIs(bridge._known_device, fresh)

    @unittest.skipUnless(__import__('sys').platform == 'win32', 'WinRT endpoint adapter')
    def test_windows_endpoint_adapter_bypasses_bleaks_implicit_scan(self):
        from bleak import BleakClient
        from companion.codex_display.windows_devices import device_from_address
        device = device_from_address(0x209BA96D7C12, 'Magpie Display')
        client = BleakClient(device, winrt={'use_cached_services':False})
        self.assertEqual(client.address, '20:9B:A9:6D:7C:12')
        self.assertEqual(client._backend._device_info, 0x209BA96D7C12)
        self.assertFalse(client._backend._use_cached_services)

    async def test_connection_refreshes_before_first_status(self):
        order = []

        async def status():
            order.append("status")
            return b"{}"

        async def refresh():
            order.append("refresh")

        companion = BleCompanion(status, refresh)
        client = FakeBleClient(expected_writes=1)
        client.start_notify = AsyncMock()
        disconnected = asyncio.Event()
        disconnected.set()

        await companion._run_connection(client, disconnected)

        self.assertEqual(order, ["refresh", "status"])
        self.assertFalse(companion.connected_event.is_set())

    async def test_status_change_sends_without_waiting_for_heartbeat(self):
        async def status():
            return b'{"a":1}'

        async def refresh():
            return None

        changed = asyncio.Event()
        companion = BleCompanion(
            status,
            refresh,
            heartbeat_seconds=999,
            status_changed=changed,
        )
        client = FakeBleClient(expected_writes=1)
        changed.set()

        await companion._heartbeat_loop(client)

        self.assertEqual(client.writes[0][1], b'{"a":1}')

    async def test_duplicate_request_is_not_executed_twice(self):
        async def status():
            return b"{}"

        async def refresh():
            return None

        companion = BleCompanion(status, refresh)
        command = b'{"v":4,"sid":55,"id":7,"a":"focus_magpie"}'
        companion._commands.put_nowait(command)
        companion._commands.put_nowait(command)
        client = FakeBleClient(expected_writes=3)

        action = AsyncMock(return_value=(True, "FOCUSED"))
        with patch("companion.codex_display.ble.perform_action", action):
            await companion._command_loop(client)

        action.assert_awaited_once()
        self.assertEqual(len(client.writes), 3)
        self.assertEqual(client.writes[0][1], client.writes[2][1])

    async def test_status_write_times_out(self):
        async def status():
            return b"{}"

        async def refresh():
            return None

        companion = BleCompanion(status, refresh)
        client = HangingBleClient()

        with patch(
            "companion.codex_display.ble.BLE_OPERATION_TIMEOUT_SECONDS",
            0.01,
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await companion._send_status(client)

    async def test_disconnect_timeout_does_not_block_reconnect(self):
        async def status():
            return b"{}"

        async def refresh():
            return None

        companion = BleCompanion(status, refresh)
        client = HangingBleClient()

        with patch(
            "companion.codex_display.ble.BLE_DISCONNECT_TIMEOUT_SECONDS",
            0.01,
        ):
            await companion._disconnect(client)


if __name__ == "__main__":
    unittest.main()
