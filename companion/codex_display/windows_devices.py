"""Recover a Windows-known BLE endpoint when it is no longer advertising.

An existing Windows GATT session can reconnect an ESP32 before the scanner sees
its advertisement. Bleak's string-address constructor scans again, so pass a
BLEDevice with the address data obtained from Windows instead. In Bleak 1.x,
WinRT consumes only ``details.adv.bluetooth_address`` from this metadata.
"""
import asyncio
import logging
from types import SimpleNamespace
from .errors import PairingRequiredError

logger = logging.getLogger(__name__)


async def require_paired(device):
    """Read pairing state without opening a GATT session or initiating pairing."""
    from winrt.windows.devices.bluetooth import BluetoothLEDevice

    address = int(device.address.replace(':', '').replace('-', ''), 16)
    native = await asyncio.wait_for(BluetoothLEDevice.from_bluetooth_address_async(address), timeout=5)
    if native is None:
        raise RuntimeError('Windows 暂时无法访问显示器')
    try:
        if not native.device_information.pairing.is_paired:
            raise PairingRequiredError('尚未完成 Windows 配对，自动连接已暂停。请点击“配对 / 蓝牙设置”，输入屏幕验证码后再开始同步。')
    finally:
        native.close()


def device_from_address(address, name):
    from bleak.backends.device import BLEDevice
    from bleak.backends.winrt.scanner import RawAdvData

    display_address = ':'.join(f'{part:02X}' for part in address.to_bytes(6, 'big'))
    return BLEDevice(display_address, name, RawAdvData(SimpleNamespace(bluetooth_address=address), None))


async def find_known_device(name):
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation

    async def find():
        selector = BluetoothLEDevice.get_device_selector()
        devices = await DeviceInformation.find_all_async_aqs_filter(selector)
        for info in devices:
            if info.name.strip().casefold() != name.strip().casefold():
                continue
            native = await BluetoothLEDevice.from_id_async(info.id)
            if native is None:
                continue
            try:
                return device_from_address(native.bluetooth_address, info.name)
            finally:
                # Enumerating an endpoint must not leave a GATT handle open.
                native.close()
        return None

    try:
        return await asyncio.wait_for(find(), timeout=5)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning('Windows known-device lookup failed: %s', error)
        return None
