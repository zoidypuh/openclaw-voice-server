# HANDOFF

## 2026-05-11 Speech Endpoint Acceptance Hardening

Goal: make `/api/runtime/speak` stop trusting stale browser readiness and make runtime state show the real playback-client condition.

Changed files in this pass:

- `src/maras_switchboard/runtime.py`
  - Added playback readiness freshness tracking with `client_status`, `websocket_status`, `websocket_connected`, `client_last_seen_*`, and last accept-timeout fields.
  - Treats stale websockets, missing playback-accept registration, locked browser audio, and paused voice pages as not playback-ready.
  - `/api/runtime/speak` now fails fast for stale/not-ready clients instead of waiting for the full 504 path with state still claiming ready.
  - Timeout responses include the current `voice_client` snapshot and mark `client_status: "accept_timed_out"`.
- `src/maras_switchboard/static/voice.html`
  - Browser `client-ready` now includes `playback_unlocked`, `web_audio_unlocked`, visibility/focus, paused state, and playback lifecycle.
  - The page re-sends readiness on watchdog ticks, reconnect/open, focus, visibility return, user activation, playback unlock, pause/resume, and audio teardown.
  - The visible client status distinguishes ready, stale/re-registering, audio locked, pending playback acceptance, and accept timeout.
- `scripts/voice_reliability_smoke.py`
  - Takes runtime state before and after the speak attempt.
  - Detects the bad shape where state claimed ready before a playback-accept timeout.
  - Distinguishes stale client and paused client from no-client failures.
- `tests/test_runtime.py`
  - Added coverage for stale active clients, audio-locked clients, and truthful accept-timeout state.
- `tests/test_app_routes.py`
  - Updated `/api/runtime/state["voice_client"]` expectations for the richer state.
- `tests/test_voice_page.py`
  - Updated assertions for browser readiness registration/status behavior.
- `tests/test_voice_reliability_smoke.py`
  - Added smoke-classification coverage for stale, paused, and state-truthfulness failures.

Verification run:

```bash
python3 -m py_compile src/maras_switchboard/runtime.py src/maras_switchboard/app.py scripts/voice_reliability_smoke.py
python3 - <<'PY'
from pathlib import Path
html=Path('src/maras_switchboard/static/voice.html').read_text()
start=html.index('<script>')+len('<script>')
end=html.rindex('</script>')
Path('/tmp/voice-script.js').write_text(html[start:end])
PY
node --check /tmp/voice-script.js
pytest -q
git diff --check
```

Result:

```text
py_compile passed
node --check passed
214 passed, 11 warnings in 2.76s
git diff --check passed
```

Live service:

```bash
timeout 20 systemctl --user restart maras-switchboard.service || (systemctl --user kill maras-switchboard.service && sleep 1 && systemctl --user start maras-switchboard.service)
systemctl --user is-active maras-switchboard.service
ss -ltnp | rg ':8765'
```

Result:

```text
active
0.0.0.0:8765 users:(("maras-switchboa",pid=3962420,fd=7))
```

Live smoke:

```bash
python3 scripts/voice_reliability_smoke.py \
  --base-url http://127.0.0.1:8765 \
  --timeout 8 \
  --text 'Codex playback acceptance hardening smoke.'
```

Result:

```text
service.maras-switchboard.service=active
runtime_ready=True
profile.active=lola
Speak Test: status=400
body={"error":"Active voice client is stale; focus or refresh /voice to re-register playback.","ok":false}
Diagnosis: stale_client
action: Focus or refresh the existing /voice tab so it sends a fresh playback-ready heartbeat.
```

Interpretation: the live endpoint no longer hangs or lies ready on the stale `/voice` client. It rejects the stale browser registration immediately and the smoke reports the recovery action.

Manual acceptance path:

1. Open or hard-refresh `http://127.0.0.1:8765/voice`.
2. Focus that page and turn voice ON so browser audio unlocks.
3. Confirm the in-page client status says playback ready.
4. Run:

```bash
python3 scripts/voice_reliability_smoke.py \
  --base-url http://127.0.0.1:8765 \
  --timeout 8 \
  --text 'Codex playback acceptance hardening smoke after browser refresh.'
```

Expected after the refreshed page is active: `Diagnosis: ok` and `/api/runtime/state["voice_client"]["client_status"] == "ready"` before/after the speak.

## Task

Kanban: `t_04be3d15` - Switchboard: restore reliable voice speak playback.

Repo: `/home/gismar/coding/maras-switchboard`

Branch/worktree: `feat/stt-to-tmux-button` in the shared dirty worktree.

## Diagnosis

Observed live failures before the fix:

- `POST /api/runtime/speak` returned HTTP 504:
  - `{"ok": false, "error": "Timed out waiting for the active voice client to accept playback.", "timeout_seconds": 8.0}`
- After cleaning up the service, `POST /api/runtime/speak` returned HTTP 400 when no browser client was connected:
  - `{"ok": false, "error": "No active voice client is connected."}`
- Logs showed the concrete browser-side playback failure:
  - `playback rejected: server_speak: ... bytes (AbortError: The play() request was interrupted by a call to pause().)`
- Service state was also bad:
  - a manually launched `python -m maras_switchboard.app` owned `0.0.0.0:8765`
  - `maras-switchboard.service` was crash-looping with `OSError: [Errno 98] ... address already in use`

Root cause found:

- `/api/runtime/speak` sends `server_speak` audio to the active browser and waits for a browser `playback-accepted` message.
- The browser only accepted after actual playback start.
- If Gismar started/held PTT while the `server_speak` audio was queued or starting, the client paused/deferred playback and could either never accept before the HTTP timeout or reject with the browser `AbortError`.
- That made a valid speak request look failed even though the browser had already received the audio.

Not the primary cause:

- TTS worker did synthesize audio; live responses included nonzero `audio_bytes`.
- Runtime lock was already released before waiting for playback acceptance.
- The immediate live service outage was a port-owner/service hygiene problem, not a code-only playback bug.

## Fix

Changed `src/maras_switchboard/static/voice.html`:

- For `server_speak` audio, the browser now sends `playback-accepted` once it has received and queued the audio bytes.
- The queued audio item is marked `playbackAccepted` so later playback start does not double-accept.
- If the audio later fails locally after being accepted, the client does not send a stale `playback-rejected` for that already accepted request.
- Normal assistant voice replies still use the existing playback lifecycle and can remain tied to playback start.

Changed `src/maras_switchboard/runtime.py`:

- Added playback/client visibility via `playback_status()`.
- Tracks active websocket connection time, client-ready time, playback-accept capability, features, and pending playback labels.
- Logs when the backend waits for playback acceptance.
- Logs playback status on speak timeout so the next failure identifies whether the issue is no client, unsupported playback acceptance, or pending playback.
- Re-checks the active voice websocket after TTS synthesis before pushing audio, so a browser reload/reconnect during synthesis does not send playback to a stale disconnected websocket.
- Adds a playback-only push lock so concurrent `/api/runtime/speak` calls cannot interleave `speaking` metadata and binary audio frames. This lock is separate from the voice turn lock, so STT/user input can still process while a playback request waits for browser acceptance.

Changed `src/maras_switchboard/app.py`:

- Adds `voice_client` to `/api/runtime/state`.

Changed tests:

- `tests/test_voice_page.py`
  - Covers queued `server_speak` acceptance and no double accept/reject for accepted items.
- `tests/test_app_routes.py`
  - Covers `/api/runtime/state["voice_client"]`.
- `tests/test_runtime.py`
  - Covers reconnect during TTS synthesis using the fresh voice client.
  - Covers stale websocket disconnects not rejecting a newer active client request.
  - Covers serialized metadata/audio frame ordering for concurrent speak calls.

## Verification

Focused tests from this pass:

```bash
python3 -m py_compile src/maras_switchboard/runtime.py src/maras_switchboard/app.py
pytest -q \
  tests/test_runtime.py::test_speak_text_uses_reconnected_voice_client_after_tts_synthesis \
  tests/test_runtime.py::test_speak_text_ignores_stale_client_disconnect_during_new_playback \
  tests/test_runtime.py::test_speak_text_serializes_concurrent_playback_pushes \
  tests/test_runtime.py::test_speak_text_playback_wait_does_not_block_user_turn_processing \
  tests/test_runtime.py::test_handle_speak_request_sends_idle_when_playback_accept_times_out
pytest -q \
  tests/test_voice_page.py::test_voice_html_accepts_deferred_server_speak_after_browser_queues_it \
  tests/test_voice_page.py::test_voice_html_rechecks_voice_client_registration_after_reconnect \
  tests/test_voice_page.py::test_voice_html_tracks_playback_lifecycle_before_showing_speaking \
  tests/test_voice_page.py::test_voice_html_keeps_server_speak_idle_from_finishing_agent_turn
perl -0777 -ne 'print $1 if m{<script>(.*)</script>}s' src/maras_switchboard/static/voice.html | node --check -
pytest -q tests/test_runtime.py
git diff --check
```

Result:

```text
py_compile passed
5 passed in 0.28s
4 passed in 0.27s
node --check passed
32 passed in 0.35s
git diff --check passed
```

Earlier focused tests:

```bash
PYTHONPATH=src uv run --extra dev pytest \
  tests/test_voice_page.py::test_voice_html_accepts_deferred_server_speak_after_browser_queues_it \
  tests/test_voice_page.py::test_voice_html_gates_ptt_interrupts_and_defers_playback_until_user_turn_finishes \
  tests/test_app_routes.py::test_runtime_state_exposes_voice_client_playback_status \
  tests/test_runtime.py::test_speak_text_playback_wait_does_not_block_user_turn_processing \
  tests/test_runtime.py::test_handle_speak_request_times_out_when_speak_stalls \
  tests/test_runtime.py::test_handle_speak_request_sends_idle_when_playback_accept_times_out
```

Result:

```text
6 passed, 1 warning in 0.80s
```

Syntax/check:

```bash
python3 -m py_compile src/maras_switchboard/runtime.py src/maras_switchboard/app.py
git diff --check
```

Result: both passed.

Broader attempted test:

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_voice_page.py tests/test_app_routes.py tests/test_runtime.py
```

Result:

```text
56 passed, 1 failed, 11 warnings
```

The failure is an existing/stale UI assertion unrelated to this playback fix:

```text
tests/test_voice_page.py::test_voice_html_uses_db_threshold_and_wait_after_speak_slider
assert 'id="status-hint"' not in voice_html
```

Current `voice.html` already contains `id="status-hint"` from prior dirty work.

Live service normalization:

```bash
systemctl --user stop maras-switchboard.service
lsof -ti TCP:8765 -sTCP:LISTEN
kill 3860991
systemctl --user start maras-switchboard.service
ss -ltnp 'sport = :8765'
```

Result:

```text
maras-switchboard.service active (running)
0.0.0.0:8765 owned by maras-switchboard service PID 3905650
```

Live runtime state after browser reconnect:

```bash
curl -sS -m 5 http://127.0.0.1:8765/api/runtime/state | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("voice_client"), indent=2))'
```

Result:

```json
{
  "active_voice_client": true,
  "playback_accept": true,
  "features": {
    "playback_accept": true
  },
  "pending_playback_accepts": 0,
  "pending_playback_labels": []
}
```

Live speak check:

```bash
curl -sS -m 20 -w '\nHTTP_STATUS:%{http_code}\nTOTAL:%{time_total}\n' \
  -H 'Content-Type: application/json' \
  -d '{"text":"Codex live playback check after queue acceptance fix.","timeout_seconds":12}' \
  http://127.0.0.1:8765/api/runtime/speak
```

Result:

```text
{"ok": true, "speaker_name": "", "spoken_text": "Codex live playback check after queue acceptance fix.", "preset_name": "", "audio_bytes": 350252}
HTTP_STATUS:200
TOTAL:0.540543
```

Latest live smoke after reconnect/stale-client/playback-lock changes:

```bash
curl -sS -m 25 -X POST http://127.0.0.1:8765/api/runtime/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Codex playback smoke after serialization fix.","timeout_seconds":12}' \
  -w '\nHTTP %{http_code}\n'
```

Result:

```text
{"ok": true, "speaker_name": "", "spoken_text": "Codex playback smoke after serialization fix.", "preset_name": "", "audio_bytes": 325676}
HTTP 200
```

Forced overlap smoke without hard-refreshing the already-open browser clients:

```bash
for text in "Codex overlap one." "Codex overlap two."; do
  curl -sS -m 30 -X POST http://127.0.0.1:8765/api/runtime/speak \
    -H 'Content-Type: application/json' \
    -d "{\"text\":\"$text\",\"timeout_seconds\":20}" \
    -w "\nHTTP %{http_code} $text\n" &
done
wait
```

Result:

```text
HTTP 504 for both overlap requests
```

Interpretation: the single live `/speak` path is verified fixed on the managed service. The overlap smoke was run against browser clients that had reconnected their websocket but had not hard-reloaded the latest `voice.html`; logs showed no pending server labels at timeout and simultaneous user speech. Hard-refresh the browser client before using this as an acceptance failure for the updated client code.

## Manual Recovery Path

If speak fails:

1. Check client status:

```bash
curl -sS http://127.0.0.1:8765/api/runtime/state | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["voice_client"], indent=2))'
```

2. If `active_voice_client` is `false`, refresh/open `http://127.0.0.1:8765/voice` in the Windows/browser client and turn voice ON/resume if needed.

3. If `playback_accept` is `false`, hard-refresh the voice page so the current JS reconnects and sends `client-ready`.

4. If `:8765` is down, `systemctl restart` hangs in `deactivating`, or the port is owned by the wrong process:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
systemctl --user kill --signal=KILL --kill-who=main maras-switchboard.service
systemctl --user reset-failed maras-switchboard.service
systemctl --user start maras-switchboard.service
ss -ltnp 'sport = :8765'
```

If a stray manual process owns `:8765`, stop that stray process first, then restart the user service.

## Remaining Manual Check

HTTP-level single live speak is verified as fixed. Gismar/Mara should still do the human audible check in the actual daily client after a hard refresh:

1. Open/refresh `http://127.0.0.1:8765/voice`.
2. Make sure the voice UI is ON.
3. Trigger a Mara `/api/runtime/speak`.
4. While/after the speak arrives, press/release PTT.
5. Confirm Mara playback is not killed by ending Gismar's own input.
