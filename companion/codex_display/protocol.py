import json
from typing import Any, Dict

from .constants import PROTOCOL_VERSION
from .metrics import Snapshot


ALLOWED_ACTIONS = {"focus_magpie", "refresh"}


def encode_snapshot(snapshot: Snapshot, sequence: int, sent_at: int = None) -> bytes:
    payload = {
        "v": PROTOCOL_VERSION,
        "s": sequence,
        "t": snapshot.generated_at if sent_at is None else sent_at,
        "o": snapshot.utc_offset_minutes,
        "r": snapshot.remaining_percent,
        "d": snapshot.tokens_today,
        "f": snapshot.calls_today,
        "z": snapshot.errors_today,
        "y": snapshot.success_permille,
        "l": snapshot.average_ttft_ms,
        "m": snapshot.latest_model[:23],
        "h": snapshot.latest_status,
        "n": snapshot.latest_latency_ms,
        "b": 1 if snapshot.latest_failed else 0,
        "x": [
            snapshot.session_count,
            snapshot.total_calls,
            snapshot.total_input,
            snapshot.total_output,
            snapshot.total_cache_read,
            snapshot.total_reasoning,
            snapshot.total_cost_micros,
            snapshot.cache_hit_permille,
            snapshot.top_model[:23],
            snapshot.top_model_calls,
        ],
    }
    payload["q"] = [snapshot.short_remaining_percent, snapshot.short_reset_at,
                    snapshot.weekly_remaining_percent, snapshot.weekly_reset_at]
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    # Large real accounts and non-ASCII model names can exceed the v4 budget.
    # Shorten display labels only; keep all numerical metrics exact.
    while len(encoded) > 250 and (payload["m"] or payload["x"][8]):
        if len(json.dumps(payload["m"])) >= len(json.dumps(payload["x"][8])):
            payload["m"] = payload["m"][:-1]
        else:
            payload["x"][8] = payload["x"][8][:-1]
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 250:
        raise ValueError("状态消息超过 250 字节 BLE 预算")
    return encoded


def decode_command(data: bytes) -> Dict[str, Any]:
    try:
        command = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("无效的命令 JSON") from error

    if not isinstance(command, dict):
        raise ValueError("无效的命令 JSON")
    if command.get("v") != PROTOCOL_VERSION:
        raise ValueError("不支持的协议版本")
    if type(command.get("sid")) is not int or command["sid"] < 1:
        raise ValueError("无效的 session id")
    if type(command.get("id")) is not int or command["id"] < 1:
        raise ValueError("无效的 request id")
    if not isinstance(command.get("a"), str) or command["a"] not in ALLOWED_ACTIONS:
        raise ValueError("不允许的动作")
    return command


def encode_result(request_id: int, ok: bool, message: str) -> bytes:
    payload = {
        "v": PROTOCOL_VERSION,
        "id": request_id,
        "ok": 1 if ok else 0,
        "m": message[:48],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")
