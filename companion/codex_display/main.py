import argparse
import asyncio
import logging
import os
import platform
import time
from typing import Callable
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

from .ble import BleCompanion
from .magpie_client import MagpieClient
from .metrics import Snapshot, collect_snapshot
from .protocol import encode_snapshot
from .runtime import ServiceLock


class SnapshotCache:
    def __init__(self, client: MagpieClient, refresh_seconds: float, on_snapshot: Optional[Callable] = None) -> None:
        self._client = client
        self._refresh_seconds = refresh_seconds
        self._snapshot: Optional[Snapshot] = None
        self._updated_at = 0.0
        self._sequence = 0
        self._lock = asyncio.Lock()
        self.status_changed = asyncio.Event()
        self._on_snapshot = on_snapshot

    async def encoded(self) -> bytes:
        loop = asyncio.get_running_loop()
        if self._snapshot is None or loop.time() - self._updated_at >= self._refresh_seconds:
            await self.refresh()
        assert self._snapshot is not None
        return encode_snapshot(self._snapshot, self._sequence, sent_at=int(time.time()))

    async def refresh(self) -> None:
        async with self._lock:
            try:
                self._snapshot = await collect_snapshot(self._client)
            except Exception:
                self._snapshot = None
                raise
            self._updated_at = asyncio.get_running_loop().time()
            self._sequence += 1
            if self._on_snapshot:
                self._on_snapshot(self._snapshot)
            logging.info(
                "Magpie updated: remaining %d%%, today %d tokens, 7d %d tokens, calls %d, errors %d",
                self._snapshot.remaining_percent,
                self._snapshot.tokens_today,
                self._snapshot.tokens_7d,
                self._snapshot.calls_today,
                self._snapshot.errors_today,
            )


async def run(args: argparse.Namespace) -> None:
    cache = SnapshotCache(MagpieClient(args.magpie_url), args.refresh_seconds)
    if args.once:
        print((await cache.encoded()).decode("utf-8"))
        return

    companion = BleCompanion(
        cache.encoded,
        cache.refresh,
        device_name=args.device,
        heartbeat_seconds=args.heartbeat_seconds,
        status_changed=cache.status_changed,
    )
    await companion.run_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Magpie Usage Display BLE Companion")
    parser.add_argument("--device", default="Magpie Display")
    parser.add_argument(
        "--magpie-url",
        default=os.environ.get("MAGPIE_URL", "http://127.0.0.1:3425"),
    )
    parser.add_argument("--refresh-seconds", type=positive_seconds, default=15)
    parser.add_argument("--heartbeat-seconds", type=heartbeat_seconds, default=15)
    parser.add_argument(
        "--once", action="store_true", help="读取一次本机 Magpie 数据并打印，不连接 BLE"
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def positive_seconds(value: str) -> float:
    import math
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("seconds must be positive and finite")
    return seconds


def heartbeat_seconds(value: str) -> float:
    seconds = positive_seconds(value)
    if seconds > 30:
        raise argparse.ArgumentTypeError("heartbeat must be <= 30 seconds (firmware watchdog)")
    return seconds


def main() -> None:
    args = build_parser().parse_args()
    log_path = os.environ.get("MAGPIE_DISPLAY_LOG")
    if not log_path and platform.system() == "Windows":
        log_path = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) /
                       "MagpieUsageDisplay" / "companion.log")
    handlers = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handlers = [
            logging.StreamHandler(),
            RotatingFileHandler(
                log_path, maxBytes=1024 * 1024, backupCount=1, encoding="utf-8"
            )
        ]
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    try:
        if args.once:
            asyncio.run(run(args))
        else:
            with ServiceLock():
                asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("Companion exited unexpectedly")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
