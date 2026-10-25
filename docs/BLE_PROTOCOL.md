# BLE protocol v4

ESP32/ST7789 port: the PC companion supports Windows and macOS. On Windows,
complete the initial six-digit passkey pairing through Windows Bluetooth
Settings before running the companion (Bleak 1.x custom pairing only supports
Just Works). The upstream UUIDs and version 4 are retained. This port adds the
optional dual-window `q` array described below.
Model display labels are shortened if necessary to fit the 250-byte budget;
numeric metrics are preserved.

This protocol describes the Magpie/ESP32 port. The original upstream
Codex app-server companion is not a drop-in replacement for this companion.

Device name: `Magpie Display`

Service UUID: `7d8b6c20-8f6d-4b44-a0f8-1b6570c0de01`

| Characteristic | UUID suffix | Direction | Properties |
|---|---:|---|---|
| Status | `02` | PC -> ESP32 | encrypted Write |
| Command | `03` | ESP32 -> PC | encrypted Read + Notify |
| Result | `04` | PC -> ESP32 | encrypted Write |
| Device info | `05` | ESP32 -> PC | Read |

Pairing uses BLE Secure Connections, bonding, MITM protection, and a random
six-digit display passkey. Bonded devices reconnect without showing a passkey.

## Status

The companion writes compact UTF-8 JSON immediately after connecting and every
15 seconds. Payloads are limited to 250 bytes for the negotiated 256-byte MTU.

```json
{"v":4,"s":42,"t":1792828800,"o":480,"r":51,"d":27233,"f":65,"z":4,"y":938,"l":1200,"m":"gpt-6.1-sol","h":200,"n":9684,"b":0,"x":[22,614,26356,5532,65728,3535,41974,714,"gpt-6.1-sol",571],"q":[51,1792832119,92,1793418919]}
```

The short scalar keys carry time, quota, today's request metrics, and the
latest route. The `x` array carries 30-day session count, calls, input/output/
cache/reasoning tokens, estimated cost in millionths of a dollar, cache-hit
rate in tenths of a percent, top model, and top-model calls.

`q = [five_hour_remaining_percent, five_hour_reset_epoch,
weekly_remaining_percent, weekly_reset_epoch]`. Only the Codex provider's
300-minute and 10080-minute windows supply these fields. Percent `-1` means
unknown; `0` means exhausted and `100` means full. Reset timestamps are absolute
Unix seconds; `0` means unknown. Dates use the PC's UTC offset `o` in minutes.
A passed reset displays `DUE` until the API supplies new data; quota is never
assumed to have refilled locally.

`t` is the PC clock at transmission, including cache heartbeats. `s` advances on
successful API collection; identical sequences are allowed for heartbeats. API
failure invalidates the cache and stops stale data being transmitted as fresh.
Token counters and estimated cost in `x` use 64-bit fields in the firmware.

### Field reference

| Key | Type / unit | Meaning |
| --- | --- | --- |
| `v` | integer, `4` | Protocol version |
| `s` | positive uint32 | Collection sequence; repeated values are heartbeats |
| `t` | Unix seconds | PC clock at transmission |
| `o` | signed minutes | PC UTC offset |
| `r` | integer percent | Legacy aggregate remaining quota; not used for the dual-ring home |
| `d` | token count | Today's API aggregate |
| `f`, `z` | request counts | Today's calls and errors |
| `y` | per mille | Today's success rate; 955 means 95.5% |
| `l` | milliseconds | Average time to first token |
| `m` | string | Latest request model label, shortened to fit |
| `h`, `n` | integer / milliseconds | Latest response status and latency |
| `b` | `0` or `1` | Latest request failed |
| `x` | 10-item array | Aggregate fields below |
| `q` | 4-item array | Independent Codex remaining quotas and reset epochs |

`x` positions are zero-based: `0` session count, `1` calls, `2` input tokens,
`3` output tokens, `4` cache-read tokens, `5` reasoning tokens,
`6` estimated cost in millionths of a US dollar, `7` cache-hit rate in per mille,
`8` top model label, `9` top-model calls. Numeric statistics come from the API;
they are not the current chat's context-window size. Firmware also accepts some
legacy fields omitted by the current encoder; these are not required fields.

Old companions omitting `q` (or sending the legacy scalar countdown) are accepted,
but both home-page quotas are unknown. New companions also work with the previous
firmware, which ignores the array. Update both for the new home page.

The header is `LINKING` until this connection receives a valid snapshot; retained
data from a previous connection cannot make a new connection `LIVE`. It shows
`OFFLINE` after BLE disconnect and `STALE` after 60 seconds without a snapshot.
The BLE watchdog disconnects after 45 seconds following the last status packet;
before the first packet, a 120-second grace period allows manual passkey pairing.
Retained data remain visible as reference.

## Commands

Allowed actions are `focus_magpie` and `refresh`. Arbitrary prompts and shell
commands are rejected.

```json
{"v":4,"sid":319028314,"id":7,"a":"focus_magpie"}
{"v":4,"id":7,"ok":1,"m":"FOCUSED"}
```
