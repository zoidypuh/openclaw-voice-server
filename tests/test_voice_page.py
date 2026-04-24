from agentic_switchboard.app import _static_dir


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
    assert "function microphoneRequiresSecureContext()" in voice_html
    assert "window.isSecureContext === false" in voice_html
    assert "microphone requires https on iphone" in voice_html
    assert "Microphone requires a secure browser context. Use HTTPS for iPhone/iPad remote access." in voice_html
    assert "async function tryUnlockPlaybackAudio()" in voice_html
    assert "playback unlock failed; continuing with microphone capture" in voice_html
    assert "preferred microphone constraints failed; retrying with basic audio constraints" in voice_html
    assert "stream = await getUserMedia({ audio: true });" in voice_html
    assert "if (isAppleVoiceClient()) {\n    const playbackReady = tryUnlockPlaybackAudio();\n    await ensureAudio();\n    await playbackReady;\n  } else {\n    await ensureAudio();\n    await unlockPlaybackAudio();\n  }\n  await loadRuntimeState();\n  await connect();" in voice_html
    assert "await unlockPlaybackAudio();" in voice_html
    assert "playbackAudio = new Audio();" in voice_html
    assert "handleResumeFailure(error);" in voice_html
    assert "updateControlStates();\n    void ensurePlaybackReady().catch(() => {});\n    syncShellState({ force: true });" in voice_html


def test_voice_html_uses_echo_controls_and_apple_specific_barge_in_guard():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function isAppleVoiceClient()" in voice_html
    assert "function isCriOSVoiceClient()" in voice_html
    assert "chrome needs mic access in ios settings" in voice_html
    assert "const INTERRUPT_PROBE_MIN_SPEECH_MS = 220;" in voice_html
    assert "const INTERRUPT_COOLDOWN_MS = 300;" in voice_html
    assert "const PAUSED_COMMAND_MIN_SPEECH_MS = 220;" in voice_html
    assert "const APPLE_BARGE_IN_MIN_SPEECH_MS = 220;" in voice_html
    assert "const BARGE_IN_ARM_CONFIDENCE = 0.32;" in voice_html
    assert "const BARGE_IN_READY_CONFIDENCE = 0.78;" in voice_html
    assert "let bargeInConfidence = 0;" in voice_html
    assert "let bargeInConfidenceQualified = false;" in voice_html
    assert "function allowsFreeformBargeIn()" in voice_html
    assert "function updateBargeInConfidence(displayedLevel, speechLike, thresholdDb, frameMs) {" in voice_html
    assert "bargeInConfidenceQualified = true;" in voice_html
    assert "if (!bargeInPending && confidence >= BARGE_IN_ARM_CONFIDENCE) {" in voice_html
    assert "if (!bargeInConfidenceQualified && totalMs >= allowedBargeInMaxMs) {" in voice_html
    assert "bargeInConfidenceQualified\n    && bargeInSpeechMs >= requiredBargeInSpeechMs" in voice_html
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
    assert '<button id="push-to-talk-btn" class="mini-btn" type="button">talk on</button>' in voice_html
    assert '<button id="interrupt-btn" class="mini-btn" type="button">interrupt</button>' in voice_html
    assert '<button id="mute-btn" class="mini-btn" type="button">mute</button>' in voice_html
    assert "let muted = false;" in voice_html
    assert "let interruptMode = 'barge-in';" in voice_html
    assert "const INTERRUPT_MODE_STORAGE_KEY = 'agentic-switchboard.voice.interrupt-mode.v1';" in voice_html
    assert "const PUSH_TO_TALK_STORAGE_KEY = 'agentic-switchboard.voice.push-to-talk.v1';" in voice_html
    assert "function voiceInterruptDisabled() {" in voice_html
    assert "function setInterruptMode(nextMode) {" in voice_html
    assert "function commitBufferedTurnNow() {" in voice_html
    assert "function loadPushToTalkEnabled() {" in voice_html
    assert "function setPushToTalkEnabled(nextEnabled) {" in voice_html
    assert "async function beginPushToTalk() {" in voice_html
    assert "function endPushToTalk() {" in voice_html
    assert "function setMutedState(nextMuted) {" in voice_html
    assert "if (!commitBufferedTurnNow()) {" in voice_html
    assert "track.enabled = !muted;" in voice_html
    assert "if (muted) {" in voice_html
    assert "document.getElementById('push-to-talk-btn').addEventListener('click', () => {" in voice_html
    assert "document.getElementById('interrupt-btn').addEventListener('click', () => {" in voice_html
    assert "document.getElementById('mute-btn').addEventListener('click', () => {" in voice_html
    assert "window.__agenticSwitchboardPushToTalkStart = beginPushToTalk;" in voice_html
    assert "window.__agenticSwitchboardPushToTalkEnd = endPushToTalk;" in voice_html


def test_voice_html_uses_root_app_base_so_trailing_slash_urls_do_not_404():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function resolveAppBase()" in voice_html
    assert "path === '/voice' || path.startsWith('/voice/')" in voice_html
    assert "return new URL('/voice/', window.location.href);" in voice_html
    assert "return new URL('/', window.location.href);" in voice_html


def test_voice_html_uses_state_wave_visual_instead_of_avatar_assets():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert '<div id="state-visual-shell" aria-label="voice state display">' in voice_html
    assert '<canvas id="state-visual" width="520" height="312"></canvas>' in voice_html
    assert 'id="state-visual-overlay"' in voice_html
    assert 'id="transcript-caption"' in voice_html
    assert 'id="transcript-log"' in voice_html
    assert 'class="visual-caption-label">conversation</div>' in voice_html
    assert "overflow-y: auto;" in voice_html
    assert "-webkit-line-clamp" not in voice_html
    assert "const STATE_VISUAL_WIDTH = 520;" in voice_html
    assert "const STATE_VISUAL_HEIGHT = 312;" in voice_html
    assert "const MAX_BUFFERED_TURN_MS = 12000;" in voice_html
    assert "function visualStateFor(state) {" in voice_html
    assert "function resizeStateVisual() {" in voice_html
    assert "function scrollTranscriptOverlayToBottom() {" in voice_html
    assert "function renderTranscriptOverlay() {" in voice_html
    assert "function pushTranscriptEntry(role, text) {" in voice_html
    assert "function setHeardTranscript(text) {" in voice_html
    assert "function appendSpokenReply(text) {" in voice_html
    assert "function replaceSpokenReply(text) {" in voice_html
    assert "let transcriptLogEntries = [];" in voice_html
    assert "let activeReplyEntryId = '';" in voice_html
    assert "transcriptLog.scrollTop = transcriptLog.scrollHeight;" in voice_html
    assert "transcriptCaption.classList.toggle('empty', transcriptLogEntries.length === 0);" in voice_html
    assert "pushTranscriptEntry('heard', heardTranscriptText);" in voice_html
    assert "const entry = pushTranscriptEntry('reply', nextText);" in voice_html
    assert "function drawStateVisualRings(ctx, width, height, state, nowSeconds, energy, theme) {" in voice_html
    assert "function drawStateVisualListeningSweep(ctx, width, height, nowSeconds, energy, theme) {" in voice_html
    assert "function drawStateVisualThinkingOrbit(ctx, width, height, nowSeconds, theme) {" in voice_html
    assert "function drawStateVisualSpeakingWave(ctx, width, height, nowSeconds, energy, theme) {" in voice_html
    assert "function animateStateVisual(nowMs) {" in voice_html
    assert "requestAnimationFrame(animateStateVisual);" in voice_html
    assert "if (data.type === 'transcript') {" in voice_html
    assert "if (data.type === 'reply-text') {" in voice_html
    assert "|| speechDuration >= MAX_BUFFERED_TURN_MS" in voice_html
    assert "static/media/listening_transparent.png" not in voice_html
    assert "static/media/thinking_transparent.png" not in voice_html
    assert "static/media/speaking1_transparent.png" not in voice_html


def test_voice_html_uses_persistent_unlocked_playback_audio():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function ensurePlaybackAudioElement()" in voice_html
    assert "function unlockPlaybackAudio()" in voice_html
    assert "function resetPlaybackElement({ preserveUnlocked = false } = {}) {" in voice_html
    assert "currentAudio = ensurePlaybackAudioElement();" in voice_html
    assert "setStatusText('tap resume to enable audio');" in voice_html
    assert "tap play reply" in voice_html
    assert "document.getElementById('play-reply-btn').addEventListener('click'" in voice_html


def test_voice_html_preserves_unlocked_playback_audio_for_retry_paths():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "const APPLE_AUDIO_STARTUP_RETRY_DELAYS_MS = [150, 350, 700];" in voice_html
    assert "const SILENT_UNLOCK_WAV_DATA_URL = 'data:audio/wav;base64," in voice_html
    assert "let audioStartupPromise = null;" in voice_html
    assert "let webAudioUnlocked = false;" in voice_html
    assert "let currentAudioSourceNode = null;" in voice_html
    assert "async function unlockWebAudioPlayback() {" in voice_html
    assert "await unlockWebAudioPlayback();" in voice_html
    assert "audio.muted = false;" in voice_html
    assert "audio.volume = 1;" in voice_html
    assert "async function playAudioBufferWithWebAudio(arrayBuffer, { onStart = null } = {})" in voice_html
    assert "audioCtx.decodeAudioData(arrayBuffer.slice(0))" in voice_html
    assert "if (isAppleVoiceClient()) {\n    currentAudio = ensurePlaybackAudioElement();" in voice_html
    assert "if (preserveUnlocked) {\n    return;\n  }\n  playbackAudio = null;\n  playbackUnlocked = false;" in voice_html
    assert "teardownAudioCapture();\n    resetPlaybackElement({ preserveUnlocked: playbackUnlocked });\n    await ensureAudio();" in voice_html
    assert "if (audioStartupPromise) {\n    return audioStartupPromise;\n  }" in voice_html
    assert "// Keep the original user-activated media element alive for Safari retries." in voice_html
    assert "teardownAudioCapture();\n      // Keep the original user-activated media element alive for Safari retries.\n      resetPlaybackElement({ preserveUnlocked: playbackUnlocked });\n      await delay(retryDelays[attempt]);\n      attempt += 1;" in voice_html
    assert "audio startup was interrupted, tap resume again" in voice_html


def test_voice_html_only_accepts_server_playback_after_browser_play_starts():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function sendClientReady() {" in voice_html
    assert "type: 'client-ready'," in voice_html
    assert "playback_accept: true," in voice_html
    assert "sendClientReady();" in voice_html
    assert "const requestId = item && typeof item === 'object' && 'requestId' in item ? item.requestId : '';" in voice_html
    assert "playAudioBufferWithWebAudio(nextBuffer.slice(0), {\n      onStart: () => sendPlaybackAcceptance(requestId)," in voice_html
    assert "currentAudio.play().then(() => {\n    sendPlaybackAcceptance(requestId);" in voice_html
    assert "if (item?.requestId) {\n    sendPlaybackRejection(item.requestId, describePlaybackError(error));\n  }" in voice_html
    assert "requestId: serverSpeakRequestId," in voice_html
    assert "if (serverSpeakRequestId) {\n        sendPlaybackAcceptance(serverSpeakRequestId);\n      }" not in voice_html


def test_voice_html_has_audio_recovery_hooks_and_watchdog():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "const AUDIO_CAPTURE_STALL_MS = 2600;" in voice_html
    assert "function describeWebSocketClose(event) {" in voice_html
    assert "reconnecting: websocket closed abnormally" in voice_html
    assert "ws.onerror = (event) => {" in voice_html
    assert "ws.onclose = (event) => {" in voice_html
    assert "setStatusText(describeWebSocketClose(event));" in voice_html
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
    assert 'min="1500" max="4000" step="50"' in voice_html
    assert 'id="turn-end-threshold"' in voice_html
    assert 'min="-60" max="0" step="1"' in voice_html
    assert "const LEVEL_DB_FLOOR = -60;" in voice_html
    assert "const WAIT_AFTER_SPEAK_MIN_MS = 1500;" in voice_html
    assert "function formatDb(levelDb) {" in voice_html
    assert "function formatWaitAfterSpeak(ms) {" in voice_html
    assert "function setLevelDb(levelDb, { updatePeak = true } = {}) {" in voice_html
    assert "function sendBufferedTurn(audioBuffer, { prefixText = '', commitMeta = null } = {}) {" in voice_html
    assert "function armHeldTurn(prefixText) {" in voice_html
    assert "function applyRuntimeShortcuts(windowsClientSettings) {" in voice_html
    assert "function updateStatusHint() {" in voice_html
    assert "talk Ctrl+Shift+S" in voice_html
    assert "push-to-talk live · release to send" in voice_html
    assert "talk off" in voice_html
    assert "if (pushToTalkEnabled && !pushToTalkActive) {" in voice_html
    assert "function renderInterruptControls() {" in voice_html
    assert "applyRuntimeShortcuts(runtimeState.windows_client);" in voice_html
    assert "document.getElementById('interrupt-mode-off').classList.toggle('active', interruptMode === 'off');" in voice_html
    assert "document.getElementById('interrupt-mode-barge').classList.toggle('active', interruptMode === 'barge-in');" in voice_html
    assert "&& !voiceInterruptDisabled()" in voice_html
    assert "tuning.inputThresholdDb" in voice_html
    assert "tuning.waitAfterSpeakMs" in voice_html
    assert "const manualFinishEnabled = false;" in voice_html
    assert "type: 'turn-commit'" in voice_html
    assert "const turnThresholdDb = tuning.inputThresholdDb;" in voice_html
    assert "const turnAboveThreshold = baseLevel > turnThresholdDb;" in voice_html
    assert "const WAIT_AFTER_SPEAK_STORAGE_LOCK_KEY = 'waitAfterSpeakMsLocked';" in voice_html
    assert "const waitAfterSpeakLocked = parsed[WAIT_AFTER_SPEAK_STORAGE_LOCK_KEY] === true;" in voice_html
    assert "if (waitAfterSpeakLocked) {" in voice_html
    assert "[WAIT_AFTER_SPEAK_STORAGE_LOCK_KEY]: tuningStorageState.waitAfterSpeakMs" in voice_html
    assert "applyRuntimeAudioSettings(runtimeState.audio);" in voice_html
    assert "const turnEndSilenceMs = resolveWaitAfterSpeakMs();" in voice_html
    assert "setLevelDb(LEVEL_DB_FLOOR);" in voice_html
    assert "live tuning" not in voice_html
    assert 'id="tuning-close"' not in voice_html
    assert '<span>voice threshold</span>' not in voice_html
