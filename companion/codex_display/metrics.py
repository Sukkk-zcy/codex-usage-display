import asyncio
import time
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class Snapshot:
    generated_at: int
    utc_offset_minutes: int
    remaining_percent: int
    limit_window_minutes: int
    quota_reset_seconds: int
    tokens_today: int
    tokens_7d: int
    errors_today: int
    calls_today: int
    success_permille: int
    average_ttft_ms: int
    latest_model: str
    latest_status: int
    latest_latency_ms: int
    latest_failed: bool
    session_count: int
    total_calls: int
    total_input: int
    total_output: int
    total_cache_read: int
    total_reasoning: int
    total_cost_micros: int
    cache_hit_permille: int
    top_model: str
    top_model_calls: int
    short_remaining_percent: int = -1
    short_reset_at: int = 0
    weekly_remaining_percent: int = -1
    weekly_reset_at: int = 0


def build_snapshot(
    quotas_result: Dict[str, Any],
    usage_result: Dict[str, Any],
    requests_result: Optional[Dict[str, Any]] = None,
    now: Optional[int] = None,
    utc_offset_minutes: Optional[int] = None,
) -> Snapshot:
    now = int(time.time()) if now is None else now
    if utc_offset_minutes is None:
        utc_offset_minutes = int(datetime_offset_seconds(now) // 60)

    quota = _most_constrained_window(quotas_result.get("data") or [])
    remaining_percent = _percent(quota.get("remaining") if quota else 100)
    quota_reset_seconds = _iso_seconds_until(
        quota.get("resetsAt") if quota else None, now
    )
    limit_window_minutes = _window_minutes(quota.get("name", "") if quota else "")
    short_window, weekly_window = _codex_windows(quotas_result.get("data") or [])

    series = usage_result.get("series") or []
    today = series[-1] if series else {}
    # A sparse series may end yesterday; don't relabel that bucket as today.
    if today.get("time"):
        try:
            bucket_date = datetime.fromisoformat(today["time"].replace("Z", "+00:00")).date()
            local_date = datetime.fromtimestamp(now + utc_offset_minutes * 60, timezone.utc).date()
            if bucket_date != local_date:
                today = {}
        except (TypeError, ValueError, OverflowError):
            today = {}
    recent = series[-7:]
    tokens_today = _tokens(today)
    tokens_7d = sum(_tokens(bucket) for bucket in recent)
    calls_today = max(0, int(today.get("calls") or 0))
    errors_today = min(calls_today, max(0, int(today.get("errors") or 0)))
    success_permille = (
        round((calls_today - errors_today) * 1000 / calls_today)
        if calls_today
        else 1000
    )
    timed_today = max(0, int(today.get("timed") or 0))
    average_ttft_ms = (
        max(0, int(today.get("ttft_ms") or 0)) // timed_today
        if timed_today
        else 0
    )
    latest = ((requests_result or {}).get("rows") or [{}])[0]
    latest_model = str(latest.get("served") or latest.get("model") or "")[:23]
    latest_status = max(0, int(latest.get("status") or 0))
    total_input = max(0, int(usage_result.get("input") or 0))
    total_output = max(0, int(usage_result.get("output") or 0))
    total_cache_read = max(0, int(usage_result.get("cache_read") or 0))
    total_reasoning = max(0, int(usage_result.get("reasoning") or 0))
    cache_base = total_input + total_cache_read
    cache_hit_permille = (
        round(total_cache_read * 1000 / cache_base) if cache_base else 0
    )
    models = usage_result.get("models") or []
    top_model_row = max(
        models,
        key=lambda item: max(0, int(item.get("calls") or 0)),
        default={},
    )

    return Snapshot(
        generated_at=now,
        utc_offset_minutes=utc_offset_minutes,
        remaining_percent=remaining_percent,
        limit_window_minutes=limit_window_minutes,
        quota_reset_seconds=quota_reset_seconds,
        tokens_today=tokens_today,
        tokens_7d=tokens_7d,
        errors_today=errors_today,
        calls_today=calls_today,
        success_permille=success_permille,
        average_ttft_ms=average_ttft_ms,
        latest_model=latest_model,
        latest_status=latest_status,
        latest_latency_ms=max(0, int(latest.get("ms") or 0)),
        latest_failed=bool(
            latest.get("err")
            or latest.get("error")
            or latest_status < 200
            or latest_status >= 400
        ),
        session_count=max(0, int(usage_result.get("sessionCount") or 0)),
        total_calls=max(0, int(usage_result.get("calls") or 0)),
        total_input=total_input,
        total_output=total_output,
        total_cache_read=total_cache_read,
        total_reasoning=total_reasoning,
        total_cost_micros=max(
            0, round(float(usage_result.get("cost") or 0) * 1_000_000)
        ),
        cache_hit_permille=cache_hit_permille,
        top_model=str(
            top_model_row.get("name") or top_model_row.get("model") or ""
        )[:23],
        top_model_calls=max(0, int(top_model_row.get("calls") or 0)),
        short_remaining_percent=_window_percent(short_window),
        short_reset_at=_reset_at(short_window),
        weekly_remaining_percent=_window_percent(weekly_window),
        weekly_reset_at=_reset_at(weekly_window),
    )


def _percent(value: Any) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError, OverflowError):
        return 100


def _tokens(bucket: Dict[str, Any]) -> int:
    return sum(
        max(0, int(bucket.get(key) or 0))
        for key in ("input", "output", "reasoning", "cache_read", "cache_write")
    )


def _most_constrained_window(
    providers: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    windows = [
        window
        for provider in providers
        for window in provider.get("windows") or []
        if not window.get("unlimited")
        and type(window.get("remaining")) in (int, float)
        and math.isfinite(window["remaining"])
    ]
    return min(windows, key=lambda item: item["remaining"], default=None)


def _codex_windows(providers):
    windows = [w for p in providers
               if str(p.get("provider") or p.get("name") or "").casefold() == "codex"
               for w in (p.get("windows") or []) if isinstance(w, dict) and not w.get("unlimited")]
    def find(minutes):
        candidates = [w for w in windows if _window_minutes(str(w.get("name") or "")) == minutes
                      and _window_percent(w) >= 0]
        return min(candidates, key=lambda w: w['remaining'], default=None)
    return find(300), find(10080)


def _window_percent(window):
    value = window.get("remaining") if window else None
    if type(value) not in (int, float) or not math.isfinite(value):
        return -1
    return _percent(value)


def _reset_at(window):
    value = window.get("resetsAt") if window else None
    if not isinstance(value, str):
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Reset strings without an explicit timezone are ambiguous.
        return max(0, int(parsed.timestamp())) if parsed.tzinfo else 0
    except (ValueError, OverflowError, OSError):
        return 0


def _iso_seconds_until(value: Optional[str], now: int) -> int:
    timestamp = _reset_at({"resetsAt": value})
    return max(0, timestamp - now) if timestamp else 0


def _window_minutes(name: str) -> int:
    parts = name.lower().split()
    aliases = {"daily": 1440, "weekly": 10080, "monthly": 43200}
    if name.lower() in aliases:
        return aliases[name.lower()]
    if len(parts) < 2:
        return 0
    try:
        amount = int(parts[0])
    except ValueError:
        return 0
    units = {
        "minute": 1,
        "minutes": 1,
        "hour": 60,
        "hours": 60,
        "day": 1440,
        "days": 1440,
        "week": 10080,
        "weeks": 10080,
    }
    return amount * units.get(parts[1], 0)


def datetime_offset_seconds(now: Optional[int] = None) -> int:
    now = int(time.time()) if now is None else now
    local = time.localtime(now)
    if local.tm_isdst > 0 and time.daylight:
        return -time.altzone
    return -time.timezone


async def collect_snapshot(client: Any) -> Snapshot:
    await client.health()
    quotas, usage, requests = await asyncio.gather(
        client.get("/v1/magpie/quotas"),
        client.get("/v1/magpie/usage"),
        client.get("/v1/magpie/usage/requests?limit=1"),
    )
    return build_snapshot(quotas, usage, requests)
