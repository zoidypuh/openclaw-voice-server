# Switchboard v2 Threshold Recovery Audit

Date: 2026-05-09

## Result

This is Switchboard v2 branch/workline recovery work. The compact threshold-meter UI in `/home/gismar/coding/codex-worktrees/switchboard-v2-calibration` is the Switchboard v2 UI candidate, not a random side experiment.

Best threshold/meter UI candidate for the v2 workline: `/home/gismar/coding/codex-worktrees/switchboard-v2-calibration` on branch `feat/v2-threshold-meter-codex`.

Reason: this worktree contains the most complete uncommitted `voice.html` meter implementation, focused test updates, passing tests, and saved desktop/mobile screenshots:

- `/home/gismar/coding/codex-worktrees/switchboard-v2-calibration/switchboard-v2-calibration-desktop.png`
- `/home/gismar/coding/codex-worktrees/switchboard-v2-calibration/switchboard-v2-calibration-mobile.png`

The desktop screenshot shows the remembered compact two-row meter UI: top wait-after-speak countdown meter with a warm dot/value, bottom live input threshold meter with a blue dot/value.

## Branch And Worktree Matrix

| Path | Branch | HEAD | Dirty state | Notes |
| --- | --- | --- | --- | --- |
| `/home/gismar/coding/maras-switchboard` | `feat/stt-to-tmux-button` | `9a92ede` | dirty | Current main worktree. Contains committed tap-to-talk/STT/Kanban work plus uncommitted Tauri/STT and `voice.html` changes. It does not contain the recovered meter UI; its tuning panel still uses the plain `input type="range"` threshold slider. |
| `/home/gismar/coding/codex-worktrees/switchboard-v2-calibration` | `feat/v2-threshold-meter-codex` | `bd2b37e` | dirty | Best Switchboard v2 meter UI candidate. Uncommitted changes in `voice.html` and `tests/test_voice_page.py`; screenshots present. |
| `/home/gismar/coding/codex-worktrees/maras-switchboard-v2-threshold-meter` | `feat/v2-threshold-meter` | `bd2b37e` | dirty | Older meter candidate. Similar intent, fewer checks, no dedicated desktop/mobile screenshots beyond inherited repo images. |
| `/home/gismar/coding/codex-worktrees/switchboard-lola-palette` | `feat/lola-avatar-calibration-palette` | `bd2b37e` | dirty | Separate Lola palette/avatar slice. It does not include the meter UI; it still has the plain slider tuning panel. |
| branch only | `v2/switchboard-next` | `bd2b37e` | n/a | Same commit as `main` and `origin/main` at audit time. Use this branch name as the intended v2 base even though it is currently not divergent. |
| branch only | `main` | `bd2b37e` | n/a | Same commit as `v2/switchboard-next`. |

## Hygiene Diagnosis

There is not a clean committed separation between `main` and `v2/switchboard-next` right now: both point at `bd2b37e`.

The current main worktree branch `feat/stt-to-tmux-button` is four commits ahead of both `main` and `v2/switchboard-next`:

- `d376640 feat: add tap-to-talk voice control`
- `14c36e4 fix: keep Lola Kanban context active`
- `122590c fix: refine Lola voice turn handling`
- `9a92ede fix: ground Lola Kanban voice responses`

So the current main worktree is best described as STT/tmux/live-Kanban work on top of the same baseline used by v2, with additional dirty changes. The remembered v2 threshold meter is not mixed into that worktree. The risk is file-level collision in `src/maras_switchboard/static/voice.html`, not an already-merged branch history problem.

Keep the STT/tmux branch separate until reviewed. Do not use the messy current Windows app state as the source of truth for the v2 UI; recover and review the v2 threshold meters on the v2 workline first.

The v2 worktree branches also all point at the same base commit; their value is in uncommitted worktree diffs, not branch commits.

## Candidate Comparison

`switchboard-v2-calibration` vs older `maras-switchboard-v2-threshold-meter`:

- Calibration diff is larger and more complete.
- It includes explicit pointer, mouse fallback, touch fallback, keyboard handling, ARIA slider updates, persistence, and value mapping tests.
- It has desktop/mobile screenshots captured after simulated interaction.
- Focused and full tests pass now in this audit.

`switchboard-lola-palette`:

- Good separate styling/avatar candidate.
- Adds `/static/media/profile-lola-pixel.png` and Lola-scoped candy/cyan styling.
- Does not include the meter DOM/control implementation, so it should be layered after calibration, not used as the meter source.

Current main worktree:

- Contains STT/tmux button tests and `server_speak` handling checks.
- Still has `id="turn-end-threshold"` as a plain range slider.
- Has no `bindTuningMeterControl` / compact meter implementation from the calibration worktree.

## Preview Verification

Preview is currently running from the best candidate worktree:

```bash
setsid -f env MARAS_SWITCHBOARD_HTTP_HOST=127.0.0.1 MARAS_SWITCHBOARD_HTTP_PORT=8895 uv run python -m maras_switchboard.app > /tmp/switchboard-v2-calibration-8895.log 2>&1 < /dev/null
```

Live process:

```text
127.0.0.1:8895 users:(("python3",pid=1915236,fd=7))
```

Manual URL:

```text
http://127.0.0.1:8895/voice
```

`/voice` verification:

```bash
curl -sS -D /tmp/switchboard-v2-voice-8895.headers http://127.0.0.1:8895/voice -o /tmp/switchboard-v2-voice-8895.html
rg -n 'id="wait-after-speak"|id="turn-end-threshold"|class="tuning-meter"|renderSilenceCountdown|bindTuningMeterControl' /tmp/switchboard-v2-voice-8895.html
```

Result:

- HTTP `200 OK`
- `Content-Length: 112760`
- Served HTML includes `id="wait-after-speak"`, `id="turn-end-threshold"`, `class="tuning-meter"`, `renderSilenceCountdown`, and `bindTuningMeterControl`.

Runtime state:

```bash
curl -sS http://127.0.0.1:8895/api/runtime/state | python3 -m json.tool
```

Result:

- HTTP JSON returned successfully.
- Active profile: `lola`.
- `runtime_ready: false` because this was a static/UI preview, not a full voice-session smoke.

## Tests Run

In `/home/gismar/coding/codex-worktrees/switchboard-v2-calibration`:

```bash
uv run --extra dev python -m pytest tests/test_voice_page.py
```

Result: `14 passed in 0.28s`.

```bash
git diff --check
```

Result: passed with no output.

```bash
uv run --extra dev python -m pytest
```

Result: `175 passed, 10 warnings in 2.26s`.

Warnings were existing aiohttp `NotAppKeyWarning` warnings from `tests/test_app_routes.py`.

## Commands Run During Audit

```bash
pwd && git status --short --branch && git worktree list --porcelain
rg --files -g 'voice.html' -g 'HANDOFF.md' -g '*test*' -g 'package.json'
sed -n '347,365p' /home/gismar/.codex/memories/MEMORY.md
sed -n '1,220p' /home/gismar/.codex/memories/rollout_summaries/2026-05-07T03-22-16-cNWZ-v2_threshold_meter_voice_ui.md
git branch --all --contains bd2b37e6f3feace3d7893b663cd1c8f23f8c20ca
git branch --all --contains 9a92ede7000dea8ea124b72dc1d066807154195d
for d in /home/gismar/coding/maras-switchboard /home/gismar/coding/codex-worktrees/switchboard-v2-calibration /home/gismar/coding/codex-worktrees/maras-switchboard-v2-threshold-meter /home/gismar/coding/codex-worktrees/switchboard-lola-palette; do git -C "$d" status --short --branch; done
git merge-base --is-ancestor v2/switchboard-next feat/stt-to-tmux-button; echo stt_contains_v2=$?
git merge-base --is-ancestor main feat/stt-to-tmux-button; echo stt_contains_main=$?
git rev-list --left-right --count v2/switchboard-next...feat/stt-to-tmux-button
git rev-list --left-right --count main...v2/switchboard-next
for d in /home/gismar/coding/maras-switchboard /home/gismar/coding/codex-worktrees/switchboard-v2-calibration /home/gismar/coding/codex-worktrees/maras-switchboard-v2-threshold-meter /home/gismar/coding/codex-worktrees/switchboard-lola-palette; do git -C "$d" diff --name-status; git -C "$d" diff --stat; git -C "$d" ls-files --others --exclude-standard; done
find /home/gismar/coding/codex-worktrees/switchboard-v2-calibration /home/gismar/coding/codex-worktrees/switchboard-lola-palette /home/gismar/coding/codex-worktrees/maras-switchboard-v2-threshold-meter -maxdepth 1 -type f \( -name '*.png' -o -name 'HANDOFF.md' \) -printf '%p %s bytes\n'
for d in /home/gismar/coding/maras-switchboard /home/gismar/coding/codex-worktrees/switchboard-v2-calibration /home/gismar/coding/codex-worktrees/maras-switchboard-v2-threshold-meter /home/gismar/coding/codex-worktrees/switchboard-lola-palette; do sed -n '1,180p' "$d/HANDOFF.md" 2>/dev/null || true; done
git log --oneline --decorate --graph --max-count=18 --all --simplify-by-decoration
git log --oneline --decorate v2/switchboard-next..feat/stt-to-tmux-button
rg -n 'turn-end-threshold|wait-after-speak-meter|meter-shell|renderSilenceCountdown|threshold-meter|inputThresholdDb|waitAfterSpeakMs|server_speak|tmux|STT|stt' src/maras_switchboard/static/voice.html tests/test_voice_page.py
rg -n 'turn-end-threshold|wait-after-speak-meter|meter-shell|renderSilenceCountdown|threshold-meter|inputThresholdDb|waitAfterSpeakMs|pointer|touch|keydown|server_speak|tmux|STT|stt' src/maras_switchboard/static/voice.html tests/test_voice_page.py
rg -n 'turn-end-threshold|wait-after-speak-meter|meter-shell|renderSilenceCountdown|threshold-meter|inputThresholdDb|waitAfterSpeakMs|profile-lola-pixel|lola-avatar|candy|profile-btn\[data-profile="lola"\]' src/maras_switchboard/static/voice.html tests/test_voice_page.py
git diff --no-index --stat /home/gismar/coding/codex-worktrees/maras-switchboard-v2-threshold-meter/src/maras_switchboard/static/voice.html /home/gismar/coding/codex-worktrees/switchboard-v2-calibration/src/maras_switchboard/static/voice.html || true
git diff --no-index --stat /home/gismar/coding/codex-worktrees/switchboard-v2-calibration/src/maras_switchboard/static/voice.html /home/gismar/coding/codex-worktrees/switchboard-lola-palette/src/maras_switchboard/static/voice.html || true
file /home/gismar/coding/codex-worktrees/switchboard-v2-calibration/switchboard-v2-calibration-desktop.png /home/gismar/coding/codex-worktrees/switchboard-v2-calibration/switchboard-v2-calibration-mobile.png
uv run --extra dev python -m pytest tests/test_voice_page.py
git diff --check
uv run --extra dev python -m pytest
ss -ltnp 'sport = :8895'
curl -sS -D /tmp/switchboard-v2-voice-8895.headers http://127.0.0.1:8895/voice -o /tmp/switchboard-v2-voice-8895.html
curl -sS http://127.0.0.1:8895/api/runtime/state | python3 -m json.tool
```

## Changed Files From This Audit

- `/home/gismar/coding/maras-switchboard/AUDIT-v2-threshold-recovery-2026-05-09.md`

No branch was merged, no worktree was deleted, no dirty changes were reset, and no commit was made.

## Recommended Next Action

Stand by for Mara review before integration. When approved, create a clean integration worktree from the named v2 base, then apply only the v2 calibration patch first:

```bash
git -C /home/gismar/coding/maras-switchboard worktree add -b feat/v2-calibration-lola-integration /home/gismar/coding/codex-worktrees/switchboard-v2-integration v2/switchboard-next
git -C /home/gismar/coding/codex-worktrees/switchboard-v2-calibration diff --binary > /tmp/switchboard-v2-calibration.patch
git -C /home/gismar/coding/codex-worktrees/switchboard-v2-integration apply --index /tmp/switchboard-v2-calibration.patch
```

Then run:

```bash
uv run --extra dev python -m pytest tests/test_voice_page.py
uv run --extra dev python -m pytest
```

After that passes and Mara/Gismar approve the recovered meter UI, layer the Lola palette patch on top and resolve `voice.html` deliberately against the calibration version:

```bash
git -C /home/gismar/coding/codex-worktrees/switchboard-lola-palette diff --binary > /tmp/switchboard-lola-palette.patch
git -C /home/gismar/coding/codex-worktrees/switchboard-v2-integration apply --3way --index /tmp/switchboard-lola-palette.patch
```

Keep `/home/gismar/coding/maras-switchboard` on `feat/stt-to-tmux-button` separate until reviewed. The STT/tmux work touches the same `voice.html` surface and should be integrated only after the Switchboard v2 calibration + Lola visual baseline is stable and explicitly approved.
