"""Async BLE/API work stays off the Tk thread. Events contain no credentials."""
import asyncio
import logging
import threading

from .ble import BleCompanion
from .main import SnapshotCache
from .magpie_client import MagpieClient
from .metrics import collect_snapshot
from .runtime import ServiceLock
from .errors import PairingRequiredError


class DesktopWorker:
    def __init__(self, events):
        self.events = events
        self.thread = None
        self.loop = None
        self.task = None
        self.cache = None
        self._stop_requested = threading.Event()
        self._probe_lock = threading.Lock()
        self._generation = 0

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def emit(self, kind, value):
        self.events.put((kind, value))

    def start(self, url, device):
        if self.running:
            return
        MagpieClient(url)
        self._generation += 1
        self._stop_requested.clear()
        self.thread = threading.Thread(target=self._thread_main, args=(url, device), daemon=True)
        self.thread.start()

    def stop(self):
        self._stop_requested.set()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    def refresh(self):
        if not (self.running and self.loop and self.cache):
            return False
        async def force():
            try:
                await self.cache.refresh()
                self.emit("api", (True, "接口正常"))
                self.cache.status_changed.set()
            except Exception as error:
                self.emit("api", (False, str(error)))
        coroutine = force()
        try:
            asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            return True
        except RuntimeError:
            coroutine.close()
            return False

    def probe(self, url):
        if not self._probe_lock.acquire(blocking=False):
            return
        generation = self._generation
        def read():
            try:
                snapshot = asyncio.run(collect_snapshot(MagpieClient(url)))
                if generation == self._generation:
                    self.emit("snapshot", snapshot)
                    self.emit("api", (True, "接口正常"))
            except Exception as error:
                if generation == self._generation:
                    self.emit("api", (False, str(error)))
            finally:
                self._probe_lock.release()
        threading.Thread(target=read, daemon=True).start()

    async def _run(self, url, device):
        self.cache = SnapshotCache(MagpieClient(url), 15, lambda s: self.emit("snapshot", s))
        bridge = BleCompanion(self.cache.encoded, self.cache.refresh, device_name=device,
                              status_changed=self.cache.status_changed,
                              on_status=lambda phase, message: self.emit("ble", (phase, message)))
        async def poll():
            while True:
                try:
                    await self.cache.refresh()
                    self.emit("api", (True, "接口正常"))
                    self.cache.status_changed.set()
                except Exception as error:
                    logging.warning("Magpie refresh failed: %s", error)
                    self.emit("api", (False, str(error)))
                await asyncio.sleep(15)
        tasks = [asyncio.create_task(poll()), asyncio.create_task(bridge.run_forever())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _thread_main(self, url, device):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        try:
            with ServiceLock():
                self.emit("running", True)
                self.task = loop.create_task(self._run(url, device))
                if self._stop_requested.is_set():
                    self.task.cancel()
                loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except PairingRequiredError as error:
            logging.warning('BLE activity paused for pairing: %s', error)
            self.emit('pairing', str(error))
        except Exception as error:
            logging.exception("Desktop sync stopped")
            self.emit("error", str(error))
        finally:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self.loop = self.task = self.cache = None
            self.emit("running", False)
