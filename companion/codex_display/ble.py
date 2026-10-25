import asyncio
import logging
import platform
from typing import Any, Awaitable, Callable, Optional

from .actions import perform_action
from .constants import (
    COMMAND_UUID,
    DEVICE_NAME,
    RESULT_UUID,
    SERVICE_UUID,
    STATUS_UUID,
)
from .protocol import decode_command, encode_result
from .errors import PairingRequiredError

logger = logging.getLogger(__name__)

BLE_OPERATION_TIMEOUT_SECONDS = 10
BLE_DISCONNECT_TIMEOUT_SECONDS = 5
BLE_CONNECT_TIMEOUT_SECONDS = 20
BLE_SCAN_SECONDS = 5
MAX_PREPARATION_FAILURES = 3
BLE_RECOVERY_COOLDOWN_SECONDS = 15


class BleCompanion:
    def __init__(
        self,
        get_status: Callable[[], Awaitable[bytes]],
        request_refresh: Callable[[], Awaitable[None]],
        device_name: str = DEVICE_NAME,
        heartbeat_seconds: float = 15,
        status_changed: Optional[asyncio.Event] = None,
        on_status: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._get_status = get_status
        self._request_refresh = request_refresh
        self._device_name = device_name
        self._heartbeat_seconds = heartbeat_seconds
        self._status_changed = status_changed
        self._commands: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._on_status = on_status
        self._recent_results = {}
        self.connected_event = asyncio.Event()
        self._known_device = None
        self._prefer_scan = False
        self._refresh_services = False
        self._last_error = ''
        self._attempt_synchronized = False
        self._has_synchronized = False
        self._connection_generation = 0

    def _report(self, phase: str, message: str) -> None:
        if phase == 'error':
            self._last_error = message
        elif phase == 'connected':
            self._last_error = ''
        elif self._last_error and phase in ('scanning', 'waiting', 'reconnecting', 'disconnected'):
            message = self._last_error + '；' + message
        if self._on_status:
            self._on_status(phase, message)

    def _matches_device(self, candidate, advertisement) -> bool:
        expected = self._device_name.strip().casefold()
        names = (candidate.name, advertisement.local_name)
        if any((name or '').strip().casefold() == expected for name in names):
            return True
        # The service UUID identifies the default display even if the name is
        # missing from the first packet or Windows still has an older name.
        return (expected == DEVICE_NAME.casefold() and
                SERVICE_UUID.lower() in {uuid.lower() for uuid in advertisement.service_uuids})

    async def _locate_device(self, scanner):
        if not self._prefer_scan:
            if self._known_device is not None:
                self._report('reconnecting', '正在重新连接上次的显示器')
                return self._known_device
            if platform.system() == 'Windows':
                from .windows_devices import find_known_device
                known = await find_known_device(self._device_name)
                if known is not None:
                    self._known_device = known
                    self._report('reconnecting', 'Windows 已识别显示器，正在恢复连接')
                    return known

        self._report('scanning', '正在搜索广播；设备重启后会自动重连')
        device = await scanner.find_device_by_filter(self._matches_device, timeout=BLE_SCAN_SECONDS)
        self._prefer_scan = False
        if device is not None:
            self._known_device = device
            return device
        # A connected peripheral normally stops advertising. Re-use its Windows
        # endpoint instead of waiting indefinitely for a packet that cannot come.
        return self._known_device

    async def run_forever(self) -> None:
        from bleak import BleakClient, BleakScanner

        if platform.system() == "Windows":
            logger.info("First use: pair Magpie Display in Windows Settings > Bluetooth > Add device; enter the code shown on the display")
        backoff = 1.0
        preparation_failures = 0
        while True:
            try:
                logger.info("Scanning for %s...", self._device_name)
                device = await self._locate_device(BleakScanner)
                if device is not None and platform.system() == 'Windows':
                    from .windows_devices import require_paired
                    await require_paired(device)
            except PairingRequiredError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.connected_event.clear()
                self._report("error", str(error))
                if "turned off" in str(error).lower():
                    logger.error(
                        "Bluetooth is unavailable or permission is missing; "
                        "enable Bluetooth in Windows Settings or macOS System Settings"
                    )
                else:
                    logger.warning("BLE scan failed: %s", error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5)
                continue
            if device is None:
                self._report('waiting', '暂未发现显示器；请确认已供电，客户端会继续重试')
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5)
                continue

            disconnected = asyncio.Event()
            self._connection_generation += 1
            connection_state = {'active': True}

            def on_disconnect(_: Any, event=disconnected, generation=self._connection_generation,
                              context=connection_state) -> None:
                event.set()
                # WinRT can deliver the old session's close event after a new
                # connection is live. It must not change the current UI/state.
                if generation != self._connection_generation or not context['active']:
                    return
                self.connected_event.clear()
                self._report("disconnected", "连接已断开，将自动重连")

            # Windows can fail fresh discovery while restoring an encrypted
            # link. Use its normal cache policy first, then force one fresh
            # discovery only if the required characteristics are missing.
            winrt_options = {"use_cached_services": False} if self._refresh_services else {}
            self._refresh_services = False
            client = BleakClient(
                device, disconnected_callback=on_disconnect,
                # Bleak 1.x WinRT custom pairing only supports Just Works.
                # Our passkey pairing must be completed in Windows Settings.
                pair=False, timeout=BLE_CONNECT_TIMEOUT_SECONDS,
                winrt=winrt_options,
            )
            linked = False
            recover_stack = False
            self._attempt_synchronized = False
            try:
                self._report("connecting", "正在连接显示器")
                await asyncio.wait_for(client.connect(), timeout=BLE_CONNECT_TIMEOUT_SECONDS)
                linked = True
                logger.info("Connected to %s", device.name or device.address)
                await self._run_connection(client, disconnected)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._prefer_scan = True
                message = str(error) or type(error).__name__
                logger.warning("BLE connection interrupted: %s", message)
                if self._attempt_synchronized:
                    preparation_failures = 0
                elif linked or 'gatt services' in message.lower() or 'start notify' in message.lower():
                    preparation_failures += 1
                authentication_failed = any(word in message.lower() for word in ('authentication', 'pairing'))
                # Keep first-time pairing protection, but a trusted session's
                # temporary Unreachable/missing-service errors after power loss
                # are not evidence that the user must pair again.
                if authentication_failed or (not self._has_synchronized and
                        ('access denied' in message.lower() or preparation_failures >= MAX_PREPARATION_FAILURES)):
                    raise PairingRequiredError('加密连接连续失败，自动连接已暂停。请点击“配对 / 蓝牙设置”处理配对，完成后手动开始同步。') from error
                recover_stack = self._has_synchronized and preparation_failures >= MAX_PREPARATION_FAILURES
                if 'unreachable' in message.lower():
                    message = ('设备暂时离线，正在等待重启恢复' if self._has_synchronized else
                               '设备未响应（Unreachable），请检查供电及蓝牙配对状态')
                elif isinstance(error, asyncio.TimeoutError):
                    message = '显示器连接超时'
                self._report('error', message + '；将自动恢复连接')
            finally:
                connection_state['active'] = False
                self.connected_event.clear()
                await self._disconnect(client)

            if self._attempt_synchronized:
                preparation_failures = 0
                backoff = 1.0
            if recover_stack:
                # Drop stale advertisement/backend metadata after disposing all
                # GATT services. Give Windows a quiet interval to settle, without
                # stopping the desktop worker or initiating any new pairing.
                self._known_device = None
                self._prefer_scan = False
                self._refresh_services = False
                preparation_failures = 0
                self._report('recovering', '设备重启后蓝牙暂未恢复，已释放旧连接；15 秒后自动重新连接')
                await asyncio.sleep(BLE_RECOVERY_COOLDOWN_SECONDS)
                continue
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 5)

    async def _disconnect(self, client: Any) -> None:
        try:
            has_services = bool(client.services)
        except Exception:
            has_services = False
        # WinRT marks the radio link CLOSED before releasing GattDeviceService
        # and notification objects. disconnect() still needs to dispose those.
        try:
            is_connected = client.is_connected
        except Exception:
            is_connected = False
        if not is_connected and not has_services:
            return
        try:
            await asyncio.wait_for(
                client.disconnect(),
                timeout=BLE_DISCONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("BLE disconnect timed out; resuming scan")
        except Exception as error:
            logger.warning("BLE disconnect failed: %s", error)

    async def _run_connection(
        self, client: Any, disconnected: asyncio.Event
    ) -> None:
        required = (STATUS_UUID, COMMAND_UUID, RESULT_UUID)
        missing = [uuid for uuid in required if client.services.get_characteristic(uuid) is None]
        if missing:
            self._refresh_services = True
            raise RuntimeError('Windows 的设备服务记录不完整，下次连接将重新读取')
        while not self._commands.empty():
            self._commands.get_nowait()
        def on_command(_: Any, data: bytearray) -> None:
            try:
                self._commands.put_nowait(bytes(data))
            except asyncio.QueueFull:
                logger.warning("Dropping command: device queue is full")

        await client.start_notify(COMMAND_UUID, on_command)
        await self._request_refresh()
        await self._send_status(client)
        if disconnected.is_set() or not client.is_connected:
            return
        self.connected_event.set()

        heartbeat = asyncio.create_task(self._heartbeat_loop(client))
        commands = asyncio.create_task(self._command_loop(client))
        wait_disconnect = asyncio.create_task(disconnected.wait())
        tasks = [heartbeat, commands, wait_disconnect]
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if task is not wait_disconnect:
                    task.result()
        finally:
            self.connected_event.clear()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _heartbeat_loop(self, client: Any) -> None:
        while client.is_connected:
            if self._status_changed is None:
                await asyncio.sleep(self._heartbeat_seconds)
            else:
                try:
                    await asyncio.wait_for(
                        self._status_changed.wait(),
                        timeout=self._heartbeat_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
                self._status_changed.clear()
            await self._send_status(client)

    async def _send_status(self, client: Any) -> None:
        payload = await self._get_status()
        await self._write_gatt_char(client, STATUS_UUID, payload)
        self._attempt_synchronized = True
        self._has_synchronized = True
        self._report("connected", "已连接，数据已发送")

    async def _write_gatt_char(
        self, client: Any, uuid: str, payload: bytes
    ) -> None:
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    uuid,
                    payload,
                    response=True,
                ),
                timeout=BLE_OPERATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as error:
            raise asyncio.TimeoutError("BLE GATT write timed out") from error

    async def _command_loop(self, client: Any) -> None:
        while client.is_connected:
            raw = await self._commands.get()
            request_id = 0
            try:
                command = decode_command(raw)
                request_id = command["id"]
                cache_key = (command["sid"], request_id)
                if cache_key in self._recent_results:
                    payload = self._recent_results[cache_key]
                    await self._write_gatt_char(
                        client, RESULT_UUID, payload
                    )
                    continue
                ok, message = await perform_action(command["a"], self._request_refresh)
            except ValueError as error:
                ok, message = False, str(error)
            except Exception as error:
                logger.exception("Device action failed: %s", error)
                ok, message = False, "ACTION FAILED"
            payload = encode_result(request_id, ok, message)
            if request_id > 0:
                self._recent_results[cache_key] = payload
                if len(self._recent_results) > 32:
                    oldest = next(iter(self._recent_results))
                    del self._recent_results[oldest]
            await self._write_gatt_char(client, RESULT_UUID, payload)
            if ok:
                await self._send_status(client)
