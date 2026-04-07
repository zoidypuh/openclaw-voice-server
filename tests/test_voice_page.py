from openclaw_voice_server.app import _static_dir


def test_voice_html_has_start_of_playback_barge_in_grace_window():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "const PLAYBACK_NO_BARGE_IN_MS = 800;" in voice_html
    assert "const APPLE_PLAYBACK_NO_BARGE_IN_MS = 1800;" in voice_html
    assert "let bargeInGraceUntil = 0;" in voice_html
    assert "startPlaybackSession();" in voice_html
    assert "if (now < bargeInGraceUntil) {" in voice_html
    assert "maybeCaptureBargeInProbe(pcm, displayedLevel, interruptSpeechLike, frameMs, now)" in voice_html


def test_voice_html_resumes_audio_before_fetching_runtime_state_for_safari():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "window.AudioContext || window.webkitAudioContext" in voice_html
    assert "if (isAppleVoiceClient()) {\n    await unlockPlaybackAudio();\n    await ensureAudio();\n  } else {\n    await ensureAudio();\n    await unlockPlaybackAudio();\n  }\n  await loadRuntimeState();\n  await connect();" in voice_html
    assert "await unlockPlaybackAudio();" in voice_html
    assert "playbackAudio = new Audio();" in voice_html
    assert "handleResumeFailure(error);" in voice_html
    assert "updateControlStates();\n    void ensurePlaybackReady().catch(() => {});\n    syncShellState({ force: true });" in voice_html


def test_voice_html_uses_echo_controls_and_apple_specific_barge_in_guard():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function isAppleVoiceClient()" in voice_html
    assert "const INTERRUPT_PROBE_MIN_SPEECH_MS = 220;" in voice_html
    assert "const INTERRUPT_COOLDOWN_MS = 300;" in voice_html
    assert "const PAUSED_COMMAND_MIN_SPEECH_MS = 220;" in voice_html
    assert "const APPLE_BARGE_IN_MIN_SPEECH_MS = 220;" in voice_html
    assert "function allowsFreeformBargeIn()" in voice_html
    assert "if (allowFreeformBargeIn) {\n      pausePlaybackForBargeIn();\n    }" in voice_html
    assert "if (result.action === 'hold' && !paused) {" in voice_html
    assert "armHeldTurn(result.content);" in voice_html
    assert "pendingBargeInPrefixText" in voice_html
    assert "if (data.action === 'hold' && !paused) {" in voice_html
    assert "armHeldTurn(String(data.content || data.heard || ''));" in voice_html
    assert "if (allowFreeformBargeIn && (result.action === 'send' || result.usableSpeech)) {" in voice_html
    assert "echoCancellation: true," in voice_html
    assert "noiseSuppression: true," in voice_html
    assert "autoGainControl: true," in voice_html
    assert "processor.connect(processorSink);" in voice_html


def test_voice_html_has_mute_button_and_mic_gate():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert '<a id="setup-link" href="./setup">setup</a>' in voice_html
    assert '<button id="interrupt-btn" class="mini-btn" type="button">interrupt</button>' in voice_html
    assert '<button id="mute-btn" class="mini-btn" type="button">mute</button>' in voice_html
    assert "let muted = false;" in voice_html
    assert "let interruptMode = 'barge-in';" in voice_html
    assert "const INTERRUPT_MODE_STORAGE_KEY = 'openclaw.voice.interrupt-mode.v1';" in voice_html
    assert "function voiceInterruptDisabled() {" in voice_html
    assert "function setInterruptMode(nextMode) {" in voice_html
    assert "function commitBufferedTurnNow() {" in voice_html
    assert "function setMutedState(nextMuted) {" in voice_html
    assert "if (!commitBufferedTurnNow()) {" in voice_html
    assert "track.enabled = !muted;" in voice_html
    assert "if (muted) {" in voice_html
    assert "document.getElementById('interrupt-btn').addEventListener('click', () => {" in voice_html
    assert "document.getElementById('mute-btn').addEventListener('click', () => {" in voice_html


def test_voice_html_uses_persistent_unlocked_playback_audio():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function ensurePlaybackAudioElement()" in voice_html
    assert "function unlockPlaybackAudio()" in voice_html
    assert "function resetPlaybackElement({ preserveUnlocked = false } = {}) {" in voice_html
    assert "currentAudio = ensurePlaybackAudioElement();" in voice_html
    assert "setStatusText('tap resume to enable audio');" in voice_html
    assert "setStatusText('audio playback failed');" in voice_html


def test_voice_html_preserves_unlocked_playback_audio_for_retry_paths():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "if (preserveUnlocked) {\n    return;\n  }\n  playbackAudio = null;\n  playbackUnlocked = false;" in voice_html
    assert "teardownAudioCapture();\n    resetPlaybackElement({ preserveUnlocked: playbackUnlocked });\n    await ensureAudio();" in voice_html
    assert "// Keep the original user-activated media element alive for the Safari retry." in voice_html
    assert "teardownAudioCapture();\n    // Keep the original user-activated media element alive for the Safari retry.\n    resetPlaybackElement({ preserveUnlocked: playbackUnlocked });\n    await new Promise((resolve) => setTimeout(resolve, 150));\n    await init();" in voice_html


def test_voice_html_has_audio_recovery_hooks_and_watchdog():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "const AUDIO_CAPTURE_STALL_MS = 2600;" in voice_html
    assert "function recoverAudioPipeline(reason) {" in voice_html
    assert "function bindAudioRecoveryHooks() {" in voice_html
    assert "function ensureCaptureWatchdog() {" in voice_html
    assert "navigator.mediaDevices?.addEventListener?.('devicechange'" in voice_html
    assert "audioCtx.onstatechange = () => {" in voice_html
    assert "track.onended = () => {" in voice_html
    assert "lastAudioProcessAt = performance.now();" in voice_html
    assert "await ensurePlaybackReady();" in voice_html


def test_voice_html_resamples_browser_capture_to_16khz_pcm():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "const TARGET_CAPTURE_SAMPLE_RATE = 16000;" in voice_html
    assert "function resampleFloatBuffer(buffer, inputSampleRate, outputSampleRate) {" in voice_html
    assert "function floatTo16BitPCM(floatBuffer) {" in voice_html
    assert "function inputBufferToPcm16(inputBuffer, inputSampleRate) {" in voice_html
    assert "audioCtx = new AudioContextClass({ sampleRate: TARGET_CAPTURE_SAMPLE_RATE });" in voice_html
    assert "const inputSampleRate = Math.max(Number(audioCtx?.sampleRate) || TARGET_CAPTURE_SAMPLE_RATE, 1);" in voice_html
    assert "const pcm = inputBufferToPcm16(input, inputSampleRate);" in voice_html
    assert "const frameMs = (pcm.length / TARGET_CAPTURE_SAMPLE_RATE) * 1000;" in voice_html


def test_voice_html_uses_db_threshold_and_wait_after_speak_slider():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert 'id="top-bar"' in voice_html
    assert '<button id="pause-btn" class="control-btn" type="button">pause</button>' in voice_html
    assert '#setup-link {' in voice_html
    assert '#pause-btn {' in voice_html
    assert 'id="status-hint"' in voice_html
    assert 'id="level-row"' in voice_html
    assert 'id="level-value"' in voice_html
    assert 'id="interrupt-panel"' in voice_html
    assert 'id="interrupt-mode-off"' in voice_html
    assert 'id="interrupt-mode-barge"' in voice_html
    assert 'id="interrupt-mode-keyword"' in voice_html
    assert '.panel-button-row {' in voice_html
    assert '#level-row {' in voice_html
    assert "#level-value.peak-held {" in voice_html
    assert "levelValue.textContent = formatDb(showPeak ? heldPeakLevelDb : currentLevelDb);" in voice_html
    assert "const LEVEL_PEAK_HOLD_MS = 5000;" in voice_html
    assert "function refreshLevelValue(now = performance.now()) {" in voice_html
    assert "if (heldPeakUntil <= now) {" in voice_html
    assert "heldPeakUntil = now + LEVEL_PEAK_HOLD_MS;" in voice_html
    assert "levelValue.classList.toggle('peak-held', showPeak);" in voice_html
    assert '<span>wait after speak</span>' in voice_html
    assert '<span>voice input threshold</span>' in voice_html
    assert 'id="wait-after-speak"' in voice_html
    assert 'id="turn-end-threshold"' in voice_html
    assert 'min="-60" max="0" step="1"' in voice_html
    assert "const LEVEL_DB_FLOOR = -60;" in voice_html
    assert "const WAIT_AFTER_SPEAK_MIN_MS = 250;" in voice_html
    assert "function formatDb(levelDb) {" in voice_html
    assert "function formatWaitAfterSpeak(ms) {" in voice_html
    assert "function setLevelDb(levelDb, { updatePeak = true } = {}) {" in voice_html
    assert "function sendBufferedTurn(audioBuffer, { prefixText = '' } = {}) {" in voice_html
    assert "function armHeldTurn(prefixText) {" in voice_html
    assert "function applyRuntimeShortcuts(windowsClientSettings) {" in voice_html
    assert "function updateStatusHint() {" in voice_html
    assert "function renderInterruptControls() {" in voice_html
    assert "applyRuntimeShortcuts(runtimeState.windows_client);" in voice_html
    assert "document.getElementById('interrupt-mode-off').classList.toggle('active', interruptMode === 'off');" in voice_html
    assert "document.getElementById('interrupt-mode-barge').classList.toggle('active', interruptMode === 'barge-in');" in voice_html
    assert "&& !voiceInterruptDisabled()" in voice_html
    assert "tuning.inputThresholdDb" in voice_html
    assert "tuning.waitAfterSpeakMs" in voice_html
    assert "applyRuntimeAudioSettings(runtimeState.audio);" in voice_html
    assert "const turnEndSilenceMs = resolveWaitAfterSpeakMs();" in voice_html
    assert "setLevelDb(LEVEL_DB_FLOOR);" in voice_html
    assert "live tuning" not in voice_html
    assert 'id="tuning-close"' not in voice_html
    assert '<span>voice threshold</span>' not in voice_html
