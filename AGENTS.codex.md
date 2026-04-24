# Project Instructions

This `AGENTS.md` applies only to `/home/gismar/coding/agentic-switchboard`.

## Mara Ping Rule

When `[P]` appears anywhere in the input, send a short ping to the existing Hermes `mara` conversation after the task is completed so Mara can inspect tmux, summarize the latest Codex output, and relay it to the user.

Run:

```bash
curl -sS http://127.0.0.1:8642/v1/responses \
  -H 'Authorization: Bearer local-hermes-key' \
  -H 'Content-Type: application/json' \
  -d @- <<JSON
{
  "conversation": "mara",
  "store": true,
  "input": "Check tmux. Check tmux: ${TMUX:-unknown}. Read the latest Codex output from that tmux session, summarize it for the user, and tell them if input is needed."
}
JSON
```

This is an agent instruction / notification rule, not a Hermes UI config entry.

## Voice / TTS Runtime Speak Rule

When a task is about voice playback, TTS, spoken replies, or making the local Agentic Switchboard voice client speak, do not grep around the repo first.

Use the Agentic Switchboard runtime speak endpoint directly:

- endpoint: `POST http://127.0.0.1:8765/api/runtime/speak`
- required JSON field: `text`
- optional JSON fields: `preset_name`, `speaker_name`, `timeout_seconds`

Template:

```bash
curl -sS http://127.0.0.1:8765/api/runtime/speak \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Hello from Hermes.",
    "timeout_seconds": 15
  }'
```

Notes:
- The `/voice` client must already be connected or the request will fail with no active voice client.
- Prefer this endpoint over generic TTS tools when Gis means the local Agentic Switchboard.

## Direct Commands Rule

DO NEVER ASK THINGS LIKE THIS:

So the next concrete step is for me to launch the Windows Tauri shell from PowerShell and inspect what happens. If you want, I’ll do that now.

IF THAT'S THE NEXT CONCRETE STEP THEN YEAH DO IT. 

When the local user clearly wants concrete commands, steps, or copy-pasteable instructions, provide them directly in the same reply.

Do not end with a needless offer like "if you want, I can give you the exact commands" when that intent is already obvious from the user's request or context.

Prefer filling in realistic paths, shells, and command sequences instead of making the user ask twice.
