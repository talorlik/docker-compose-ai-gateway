from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import requests

from app.redis_client import publish_event


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class OllamaInstance:
    url: str
    healthy: bool = False
    inflight: int = 0
    last_error: str | None = None
    last_checked_ts: str | None = None


class OllamaPool:
    """Select an Ollama instance with basic health + inflight tracking.

    The goal is to route requests to an available instance and avoid sending
    work to unhealthy instances. This is intentionally simple: selection is
    least-inflight among healthy instances with an inflight cap.
    """

    def __init__(
        self,
        urls: list[str],
        *,
        model: str,
        timeout_seconds: int,
        max_inflight_per_instance: int,
        num_ctx: int,
        num_predict: int,
        status_channel: str = "ollama:status",
        probe_interval_seconds: float = 2.0,
    ) -> None:
        self._lock = threading.Lock()
        self._instances: dict[str, OllamaInstance] = {
            u: OllamaInstance(url=u) for u in urls
        }
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_inflight = max_inflight_per_instance
        self._num_ctx = num_ctx
        self._num_predict = num_predict
        self._status_channel = status_channel
        self._probe_interval_seconds = probe_interval_seconds
        self._stop = threading.Event()
        self._probe_thread: threading.Thread | None = None

    def start_probes(self) -> None:
        if self._probe_thread is not None:
            return
        t = threading.Thread(target=self._probe_loop, daemon=True)
        self._probe_thread = t
        t.start()

    def stop_probes(self) -> None:
        self._stop.set()
        if self._probe_thread is not None:
            self._probe_thread.join(timeout=2.0)

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {
                url: {
                    "healthy": inst.healthy,
                    "inflight": inst.inflight,
                    "last_error": inst.last_error,
                    "last_checked_ts": inst.last_checked_ts,
                }
                for url, inst in self._instances.items()
            }

    def acquire(self) -> str:
        """Pick an instance and increment its inflight counter."""
        with self._lock:
            candidates = [
                inst
                for inst in self._instances.values()
                if inst.healthy and inst.inflight < self._max_inflight
            ]
            if not candidates:
                # Fall back to "least inflight" even if unhealthy - callers may
                # retry or fail fast with a clearer error.
                candidates = list(self._instances.values())
            chosen = min(candidates, key=lambda i: (i.inflight, i.url))
            chosen.inflight += 1
            return chosen.url

    def release(self, url: str) -> None:
        with self._lock:
            inst = self._instances.get(url)
            if not inst:
                return
            inst.inflight = max(0, inst.inflight - 1)

    def generate(self, *, prompt: str, system: str | None = None) -> str:
        """Call Ollama /api/generate via the pool selection."""
        url = self.acquire()
        try:
            endpoint = f"{url.rstrip('/')}/api/generate"
            payload: dict = {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_ctx": self._num_ctx,
                    "num_predict": self._num_predict,
                },
            }
            if system is not None:
                payload["system"] = system
            r = requests.post(endpoint, json=payload, timeout=self._timeout_seconds)
            r.raise_for_status()
            return r.json()["response"]
        finally:
            self.release(url)

    def _probe_loop(self) -> None:
        last_published: dict[str, bool] = {}
        while not self._stop.is_set():
            for url in list(self._instances.keys()):
                healthy, err = self._probe_one(url)
                now = _utc_ts()
                with self._lock:
                    inst = self._instances[url]
                    inst.last_checked_ts = now
                    inst.last_error = err
                    inst.healthy = healthy

                prev = last_published.get(url)
                if prev is None or prev != healthy:
                    last_published[url] = healthy
                    publish_event(
                        self._status_channel,
                        {
                            "ts": now,
                            "url": url,
                            "healthy": healthy,
                            "error": err,
                        },
                    )
            self._stop.wait(self._probe_interval_seconds)

    def _probe_one(self, url: str) -> tuple[bool, str | None]:
        try:
            # /api/tags is lightweight and indicates the server is alive.
            endpoint = f"{url.rstrip('/')}/api/tags"
            r = requests.get(endpoint, timeout=3)
            r.raise_for_status()
            _ = json.loads(r.text)
            return True, None
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            return False, str(e)


_singleton_lock = threading.Lock()
_singleton: OllamaPool | None = None


def get_ollama_pool(factory: Callable[[], OllamaPool]) -> OllamaPool:
    """Lazy singleton to share probes across requests within training-api."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = factory()
            _singleton.start_probes()
        return _singleton
