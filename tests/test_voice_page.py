from maras_switchboard.app import _static_dir


def test_voice_html_has_start_of_playback_barge_in_grace_window():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "const PLAYBACK_NO_BARGE_IN_MS = 450;" in voice_html
    assert "const APPLE_PLAYBACK_NO_BARGE_IN_MS = 1000;" in voice_html
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
    assert "updateControlStates();\n    void ensurePlaybackReady().catch(() => {});\n    void refreshVoiceClientStatus();\n    syncShellState({ force: true });" in voice_html


def test_voice_html_uses_echo_controls_and_apple_specific_barge_in_guard():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function isAppleVoiceClient()" in voice_html
    assert "function isCriOSVoiceClient()" in voice_html
    assert "chrome needs mic access in ios settings" in voice_html
    assert "const INTERRUPT_COOLDOWN_MS = 300;" in voice_html
    assert "const APPLE_BARGE_IN_MIN_SPEECH_MS = 220;" in voice_html
    assert "const BARGE_IN_ARM_CONFIDENCE = 0.32;" in voice_html
    assert "const BARGE_IN_READY_CONFIDENCE = 0.78;" in voice_html
    assert "let bargeInConfidence = 0;" in voice_html
    assert "let bargeInConfidenceQualified = false;" in voice_html
    assert "function allowsFreeformBargeIn()" in voice_html
    assert "return interruptMode === 'hotkey-only';" in voice_html
    assert "&& allowsFreeformBargeIn()" in voice_html
    assert "function updateBargeInConfidence(displayedLevel, speechLike, thresholdDb, frameMs) {" in voice_html
    assert "bargeInConfidenceQualified = true;" in voice_html
    assert "if (!bargeInPending && confidence >= BARGE_IN_ARM_CONFIDENCE) {" in voice_html
    assert "if (!bargeInConfidenceQualified && totalMs >= allowedBargeInMaxMs) {" in voice_html
    assert "bargeInConfidenceQualified\n    && bargeInSpeechMs >= requiredBargeInSpeechMs" in voice_html
    assert "if (allowFreeformBargeIn) {\n      pausePlaybackForBargeIn();\n    }" in voice_html
    assert "function probeUsableSpeech(audioBuffer) {" in voice_html
    assert "api/runtime/speech-probe" in voice_html
    assert "if (result.usableSpeech) {" in voice_html
    assert "echoCancellation: true," in voice_html
    assert "noiseSuppression: true," in voice_html
    assert "autoGainControl: true," in voice_html
    assert "processor.connect(processorSink);" in voice_html


def test_voice_html_has_mute_button_and_mic_gate():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "<title>Mara's Switchboard</title>" in voice_html
    assert '<div id="ascii-title" aria-label="Mara\'s Switchboard">' in voice_html
    assert 'class="ascii-title-line ascii-title-mara"' in voice_html
    assert 'class="ascii-title-line ascii-title-switchboard"' in voice_html
    assert "margin-top: 38px;" in voice_html
    assert "transform: translateY(-18px);" not in voice_html
    assert "drop-shadow(0 12px 18px rgba(0,0,0,0.9))" in voice_html
    assert "drop-shadow(0 2px 2px rgba(0,0,0,0.72))" in voice_html
    assert "0 10px 22px rgba(74, 15, 2, 0.78);" in voice_html
    assert "0 10px 22px rgba(5, 32, 55, 0.8);" in voice_html
    assert "color: rgba(255, 152, 54, 0.66);" in voice_html
    assert "color: rgba(122, 216, 255, 0.58);" in voice_html
    assert "background-clip: text;" not in voice_html
    assert "|_|  |_|\\__,_|_|  \\__,_| |___/</pre>" in voice_html
    assert " ____          _ _       _     _                         _" in voice_html
    assert "/ ___|_      _(_) |_ ___| |__ | |__   ___   __ _ _ __ __| |" in voice_html
    assert "|____/ \\_/\\_/ |_|\\__\\___|_| |_|_.__/ \\___/ \\__,_|_|  \\__,_|</pre>" in voice_html
    assert '<a id="setup-link" href="./setup">setup</a>' in voice_html
    assert 'id="version"' not in voice_html
    assert 'id="shortcut-command"' not in voice_html
    assert "space / ctrl+alt+shift+a hold to talk" not in voice_html
    assert '<button id="interrupt-btn" class="mini-btn hidden" type="button" aria-hidden="true" tabindex="-1">interrupt</button>' in voice_html
    assert '<button id="talk-toggle-btn" class="mini-btn" type="button" aria-pressed="false">talk</button>' in voice_html
    assert '<select id="tmux-target-select" aria-label="tmux target"></select>' in voice_html
    assert '<button id="tmux-text-btn" class="mini-btn" type="button">text</button>' in voice_html
    assert '<button id="mute-btn" class="mini-btn" type="button">mute</button>' in voice_html
    assert "let muted = true;" in voice_html
    assert "let interruptMode = 'hotkey-only';" in voice_html
    assert "const INTERRUPT_MODE_STORAGE_KEY = 'maras-switchboard.voice.interrupt-mode.v1';" in voice_html
    assert "function defaultInterruptMode() {\n  return 'hotkey-only';\n}" in voice_html
    assert "if (mode === 'explicit') {\n    return 'hotkey-only';\n  }" in voice_html
    assert "function voiceInterruptDisabled() {" in voice_html
    assert "function setInterruptMode(nextMode) {" in voice_html
    assert "function pauseButtonLabel() {" not in voice_html
    assert "function commitBufferedTurnNow({ reason = 'manual-release' } = {}) {" in voice_html
    assert "async function beginHoldToTalk({ tmuxOnly = false } = {}) {" in voice_html
    assert "beginUserTurn({ tmuxOnly });" in voice_html
    assert "const shouldInterruptSpeech = Boolean(" not in voice_html
    assert "function manualInterrupt() {\n  if (paused || isUserTurnActive()) {\n    return;\n  }" in voice_html
    assert "setInterruptMode('barge-in');\n    requestInterrupt({ keepPaused: false });" not in voice_html
    assert "function endHoldToTalk() {" in voice_html
    assert "const allowAutomaticTurnCommit = !isHoldToTalkActive();" in voice_html
    assert "allowAutomaticTurnCommit\n      && speechDuration >= minSpeechDuration\n      && speechDuration >= MAX_BUFFERED_TURN_MS" in voice_html
    assert "allowAutomaticTurnCommit\n    && speechDuration >= minSpeechDuration\n    && (" in voice_html
    assert "function setMutedState(nextMuted, { commitOnMute = true, resetBuffer = true } = {}) {" in voice_html
    assert "if (resetBuffer && (!muted || !commitOnMute || !commitBufferedTurnNow())) {" in voice_html
    assert "waitAfterSpeakMs: 0," in voice_html
    assert "tmuxTarget: isTmuxTalkActive() ? selectedTmuxTarget : ''," in voice_html
    assert "setMutedState(true, { commitOnMute: false, resetBuffer: false });" in voice_html
    assert "const sent = commitBufferedTurnNow({ reason: tmuxTalkActive ? 'tmux-release' : 'hold-release' });" in voice_html
    assert "track.enabled = micEnabled;" in voice_html
    assert "if (muted) {" in voice_html
    assert "document.getElementById('interrupt-btn').addEventListener('click', () => {" in voice_html
    assert "window.__marasSwitchboardManualInterrupt = manualInterrupt;" in voice_html
    assert "document.getElementById('talk-toggle-btn').addEventListener('click', () => {" in voice_html
    assert "async function toggleHoldToTalk({ tmuxOnly = false } = {}) {" in voice_html
    assert "talkToggleBtn.textContent = holdToTalkActive ? 'send' : 'talk';" in voice_html
    assert "document.getElementById('mute-btn').addEventListener('click', () => {" in voice_html
    assert "muteBtn.textContent = 'mute';" in voice_html
    assert "window.__marasSwitchboardHoldToTalkStart = beginHoldToTalk;" in voice_html
    assert "window.__marasSwitchboardTmuxHoldToTalkStart = () => beginHoldToTalk({ tmuxOnly: true });" in voice_html
    assert "window.__marasSwitchboardTmuxHoldToTalkEnd = () => endHoldToTalk();" in voice_html
    assert "window.__marasSwitchboardTmuxHoldToTalkToggle = () => toggleHoldToTalk({ tmuxOnly: true });" in voice_html
    assert "window.__marasSwitchboardHoldToTalkEnd = endHoldToTalk;" in voice_html
    assert "function applyTmuxTargetState(runtimeState) {" in voice_html
    assert "applyTmuxTargetState(runtimeState);" in voice_html


def test_voice_html_removes_broken_browser_keyboard_shortcuts():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "browserHoldToTalkShortcut" not in voice_html
    assert "keyboardEventIsHoldToTalkShortcut" not in voice_html
    assert "event.code === 'Space'" not in voice_html
    assert "event.code === 'KeyA' && event.ctrlKey && event.altKey && event.shiftKey" not in voice_html
    assert "function bindBrowserKeyboardShortcuts() {" not in voice_html
    assert "document.addEventListener('keydown', handleBrowserShortcutKeyDown);" not in voice_html
    assert "document.addEventListener('keyup', handleBrowserShortcutKeyUp);" not in voice_html
    assert "if (event.code === 'KeyP') {" not in voice_html
    assert "if (event.code === 'KeyM') {" not in voice_html
    assert "if (event.code === 'Escape' || event.code === 'KeyI') {" not in voice_html
    assert "if (event.code === 'KeyB') {" not in voice_html


def test_voice_html_uses_root_app_base_so_trailing_slash_urls_do_not_404():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function resolveAppBase()" in voice_html
    assert "path === '/voice' || path.startsWith('/voice/')" in voice_html
    assert "return new URL('/voice/', window.location.href);" in voice_html
    assert "return new URL('/', window.location.href);" in voice_html


def test_voice_html_shows_voice_reachable_indicator():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert 'id="voice-reachable-status"' in voice_html
    assert "Voice reachable ${enabled ? 'ON' : 'OFF'}" in voice_html
    assert "function applyVoiceReachableState(runtimeState) {" in voice_html
    assert "applyVoiceReachableState(runtimeState);" in voice_html
    assert "if (data.type === 'voice-reachable') {" in voice_html
    assert "With headphones on, press the talk key to address Mara" in voice_html


def test_voice_html_keeps_server_speak_idle_from_finishing_agent_turn():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "if (data.source === 'server_speak') {" in voice_html
    assert "if (!busy) {\n          pendingIdle = !paused && !isUserTurnActive();\n          maybeReturnToListening();\n        }" in voice_html
    assert "updateControlStates();\n        syncShellState();\n        return;\n      }\n    }\n    if (data.status === 'thinking')" in voice_html


def test_voice_html_uses_pixel_meter_visual_instead_of_avatar_assets():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert '<div id="state-visual-shell" aria-label="voice state display">' in voice_html
    assert '<canvas id="state-visual" width="520" height="312"></canvas>' in voice_html
    assert 'id="state-visual-overlay"' in voice_html
    assert '<div id="state-visual-shell" aria-label="voice state display">\n    <canvas id="state-visual" width="520" height="312"></canvas>\n  </div>\n  <div id="state-visual-overlay">' in voice_html
    assert "position: absolute;\n    inset: auto 0 0 0;" not in voice_html
    assert 'id="transcript-caption"' in voice_html
    assert 'id="transcript-log"' in voice_html
    assert 'class="visual-caption-label">conversation</div>' in voice_html
    assert "grid-template-rows: auto 1fr;" in voice_html
    assert "height: clamp(5.6rem, 18dvh, 15rem);" in voice_html
    assert "overflow-y: hidden;" in voice_html
    assert "-webkit-line-clamp" not in voice_html
    assert '<form id="text-turn-form" class="text-turn-form" autocomplete="off">' in voice_html
    assert 'id="text-turn-input"' in voice_html
    assert "height: clamp(2.55rem, 8dvh, 7rem);" in voice_html
    assert "resize: none;" in voice_html
    assert "async function sendTypedTurn(text, { tmuxTarget = '' } = {}) {" in voice_html
    assert "type: 'text-input',\n    text: typedText,\n    tmux_target: String(tmuxTarget || '').trim()," in voice_html
    assert "function configureTextTurnInput() {" in voice_html
    assert "form.requestSubmit();" in voice_html
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
    assert "let transcriptScrollAnimationId = 0;" in voice_html
    assert "transcriptLogEntries = [entry];" in voice_html
    assert "cancelAnimationFrame(transcriptScrollAnimationId);" in voice_html
    assert "const maxScroll = Math.max(0, transcriptLog.scrollHeight - transcriptLog.clientHeight);" in voice_html
    assert "transcriptLog.scrollTop = maxScroll * eased;" in voice_html
    assert "transcriptCaption.classList.toggle('empty', transcriptLogEntries.length === 0);" in voice_html
    assert "pushTranscriptEntry('user - heard', heardTranscriptText);" in voice_html
    assert "const entry = pushTranscriptEntry('assistant', nextText);" in voice_html
    assert "const STATE_VISUAL_RENDER_SCALE = 0.58;" in voice_html
    assert "const STATE_VISUAL_BANDS = 22;" in voice_html
    assert "const ASCII_ART_URL = new URL('/media/ascii-art.txt', window.location.href).toString();" in voice_html
    assert "let visualFrequencyData = null;" in voice_html
    assert "let asciiArtLines = [];" in voice_html
    assert "function loadAsciiArtBackdrop() {" in voice_html
    assert "function drawStateVisualAsciiBackdrop(ctx, width, height, theme) {" in voice_html
    assert "function asciiGlyphWeight(char) {" in voice_html
    assert "function drawAsciiLineWithGlyphTones(ctx, line, x, y, tones) {" in voice_html
    assert "function drawAsciiLightForRect(ctx, layout, x, y, width, height, fill) {" in voice_html
    assert "function refreshVisualFrequencyData() {" in voice_html
    assert "function visualLiveFrequencySample(index, bandCount) {" in voice_html
    assert "function drawStateVisualPixelMeter(ctx, width, height, state, nowSeconds, energy, theme, asciiLayout) {" in voice_html
    assert "function drawStateVisualReadout(ctx, width, height, state, nowSeconds, energy, theme) {" in voice_html
    assert "ctx.fillText('Y+', 10, 34);" in voice_html
    assert "ctx.fillText('Y-', 10, height - 84);" in voice_html
    assert "drawAsciiLightForRect(ctx, asciiLayout" in voice_html
    assert "ctx.shadowBlur = 3;" in voice_html
    assert "ctx.fillStyle = asciiLayout ? 'rgba(255, 255, 255, 0.004)' : 'rgba(255, 255, 255, 0.075)';" in voice_html
    assert "drawPixelMeterSegment(ctx, x, yPositive, barWidth, blockHeight, segmentFill, segmentGlow, asciiLayout);" in voice_html
    assert "drawPixelMeterSegment(ctx, x, yNegative, barWidth, blockHeight, segmentFill, segmentGlow, asciiLayout);" in voice_html
    assert "loadAsciiArtBackdrop();" in voice_html
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


def test_voice_html_accepts_deferred_server_speak_after_browser_queues_it():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function sendClientReady() {" in voice_html
    assert "type: 'client-ready'," in voice_html
    assert "playback_accept: true," in voice_html
    assert "playback_unlocked: playbackUnlocked," in voice_html
    assert "page_visible: !document.hidden," in voice_html
    assert "sendClientReady();" in voice_html
    assert "const requestId = item && typeof item === 'object' && 'requestId' in item ? item.requestId : '';" in voice_html
    assert "const playbackAccepted = Boolean(item && typeof item === 'object' && item.playbackAccepted);" in voice_html
    assert "if (!playbackAccepted) {\n          sendPlaybackAcceptance(requestId);\n        }\n        startPlaybackSession();" in voice_html
    assert "if (!playbackAccepted) {\n      sendPlaybackAcceptance(requestId);\n    }\n    startPlaybackSession();" in voice_html
    assert "if (item?.requestId && !item?.playbackAccepted) {\n    sendPlaybackRejection(item.requestId, describePlaybackError(error));\n  }" in voice_html
    assert "requestId: playbackRequestId," in voice_html
    assert "pendingPlaybackRequestId = String(data.request_id || '');" in voice_html
    assert "const acceptQueuedServerSpeak = playbackSource === 'server_speak';" in voice_html
    assert "if (acceptQueuedServerSpeak && playbackRequestId) {\n        sendPlaybackAcceptance(playbackRequestId);\n      }" in voice_html
    assert "playbackAccepted: acceptQueuedServerSpeak," in voice_html


def test_voice_html_rechecks_voice_client_registration_after_reconnect():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert 'id="client-status" class="client-status reconnecting"' in voice_html
    assert "const VOICE_CLIENT_WATCHDOG_INTERVAL_MS = 2500;" in voice_html
    assert "async function refreshVoiceClientStatus() {" in voice_html
    assert "fetch(appUrl('api/runtime/state'), { cache: 'no-store' })" in voice_html
    assert "const voiceClient = runtimeState?.voice_client || {};" in voice_html
    assert "const clientStatus = String(voiceClient.client_status || '');" in voice_html
    assert "client: connected, playback ready" in voice_html
    assert "client: page connected, audio locked" in voice_html
    assert "client: playback acceptance pending" in voice_html
    assert "client: playback accept timed out; refocusing" in voice_html
    assert "client: registering playback acceptance" in voice_html
    assert "client: server lost browser registration" in voice_html
    assert "ws.close(4000, 'server lost voice client registration');" in voice_html
    assert "startVoiceClientWatchdog();" in voice_html


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
    assert '<button id="pause-btn" class="power-toggle" type="button"' in voice_html
    assert '<span class="power-label power-label-off">OFF</span>' in voice_html
    assert '<span class="power-label power-label-on">ON</span>' in voice_html
    assert 'id="corner-controls"' in voice_html
    assert 'class="profile-btn" type="button" data-profile="lola"' in voice_html
    assert 'class="profile-btn" type="button" data-profile="mara"' not in voice_html
    assert "/static/media/profile-nadia-pixel.png" in voice_html
    assert "/static/media/profile-mara-pixel.png" not in voice_html
    assert "api/runtime/profile" in voice_html
    assert "ws.close(1000, 'profile switch');" in voice_html
    assert "await setPausedState(false, { forceInterrupt: true });" in voice_html
    assert ".profile-btn.active.thinking {" in voice_html
    assert "animation: profileWorkingGlow 760ms ease-in-out infinite;" in voice_html
    assert ".profile-btn.active.thinking::before" in voice_html
    assert ".profile-btn.active img" in voice_html
    assert "drop-shadow(0 0 10px rgba(109,226,255,0.68));" in voice_html
    assert "@keyframes profileWorkingGlow" in voice_html
    assert "@keyframes profileThinkingBubbles" in voice_html
    assert ".profile-btn.active.speaking::after" in voice_html
    assert "button.classList.add(currentState);" in voice_html
    assert "const DEFAULT_VOICE_PROFILE = 'lola';" in voice_html
    assert 'id="thinking-timer"' not in voice_html
    assert "formatThinkingElapsed" not in voice_html
    assert "#state-visual-shell {\n    display: none;" in voice_html
    assert 'id="client-status"' in voice_html
    assert 'id="status-hint"' in voice_html
    assert 'id="version"' not in voice_html
    assert "#pause-btn {\n    position: fixed;" in voice_html
    assert "right: 18px;" in voice_html
    assert "pauseButtonLabel" not in voice_html
    assert '<div id="status">listening</div>' not in voice_html
    assert '#status {' not in voice_html
    assert '#setup-link {' in voice_html
    assert '#pause-btn {' in voice_html
    assert 'id="level-row"' in voice_html
    assert 'id="level-value"' in voice_html
    assert 'id="interrupt-panel"' not in voice_html
    assert 'id="interrupt-mode-off"' not in voice_html
    assert 'id="interrupt-mode-barge"' not in voice_html
    assert 'id="interrupt-mode-keyword"' not in voice_html
    assert '.panel-button-row {' not in voice_html
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
    assert 'min="500" max="2500" step="25"' in voice_html
    assert 'id="turn-end-threshold"' in voice_html
    assert 'min="-60" max="0" step="1"' in voice_html
    assert "const LEVEL_DB_FLOOR = -60;" in voice_html
    assert "const WAIT_AFTER_SPEAK_MIN_MS = 500;" in voice_html
    assert "function formatDb(levelDb) {" in voice_html
    assert "function formatWaitAfterSpeak(ms) {" in voice_html
    assert "function setLevelDb(levelDb, { updatePeak = true } = {}) {" in voice_html
    assert "function sendBufferedTurn(audioBuffer, { commitMeta = null } = {}) {" in voice_html
    assert "function isHoldToTalkActive() {" in voice_html
    assert "function isUserTurnActive() {" in voice_html
    assert "return userTurnActive || userInputPending || holdToTalkActive;" in voice_html
    assert "function clearStatusHint() {" in voice_html
    assert "function applyRuntimeShortcuts" not in voice_html
    assert "function formatShortcutHint" not in voice_html
    assert "windowsClientShortcuts" not in voice_html
    assert "pauseBtn.classList.toggle('active', !paused);" in voice_html
    assert "pauseBtn.setAttribute('aria-label', paused ? 'voice off' : 'voice on');" in voice_html
    assert "pushToTalk" not in voice_html
    assert "function renderInterruptControls() {" in voice_html
    assert "applyRuntimeShortcuts(runtimeState.windows_client);" not in voice_html
    assert "interruptBtn.textContent = 'hotkey only';" in voice_html
    assert "interruptBtn.setAttribute('aria-label', 'Barge-in: hotkey only');" in voice_html
    assert "interruptBtn.textContent = 'normal';" in voice_html
    assert "interruptBtn.classList.toggle('active', interruptMode === 'barge-in');" in voice_html
    assert "function shouldListenForBargeInWhileMuted() {" in voice_html
    assert "const micEnabled = !muted || shouldListenForBargeInWhileMuted();" in voice_html
    assert "const mutedBargeIn = shouldListenForBargeInWhileMuted();" in voice_html
    assert "requestInterrupt({ keepPaused: false, preservePendingInput: true });" in voice_html
    assert "if (isInterruptibleAudioState() || currentState === 'thinking' || busy) {" in voice_html
    assert "setInterruptMode(nextInterruptMode(interruptMode));" in voice_html
    assert "function nextInterruptMode(mode) {" in voice_html
    assert "return 'hotkey-only';" in voice_html
    assert "&& !voiceInterruptDisabled()\n    && allowsFreeformBargeIn()" in voice_html
    assert "tuning.inputThresholdDb" in voice_html
    assert "tuning.waitAfterSpeakMs" in voice_html
    assert "manualFinish" not in voice_html
    assert "type: 'turn-commit'" in voice_html
    assert "const HOLD_TO_TALK_INPUT_THRESHOLD_DB = -58;" in voice_html
    assert "const HOLD_TO_TALK_WAIT_AFTER_SPEAK_MS = MAX_BUFFERED_TURN_MS;" in voice_html
    assert "function resolveTurnInputThresholdDb() {" in voice_html
    assert "return HOLD_TO_TALK_INPUT_THRESHOLD_DB;" in voice_html
    assert "return HOLD_TO_TALK_WAIT_AFTER_SPEAK_MS;" in voice_html
    assert "const turnThresholdDb = resolveTurnInputThresholdDb();" in voice_html
    assert "const turnAboveThreshold = baseLevel > turnThresholdDb;" in voice_html
    assert "const WAIT_AFTER_SPEAK_STORAGE_LOCK_KEY = 'waitAfterSpeakMsLocked';" in voice_html
    assert "const waitAfterSpeakLocked = parsed[WAIT_AFTER_SPEAK_STORAGE_LOCK_KEY] === true;" in voice_html
    assert "if (waitAfterSpeakLocked) {" in voice_html
    assert "[WAIT_AFTER_SPEAK_STORAGE_LOCK_KEY]: tuningStorageState.waitAfterSpeakMs" in voice_html
    assert "applyRuntimeAudioSettings(runtimeState.audio);" in voice_html
    assert "const turnEndSilenceMs = resolveWaitAfterSpeakMs();" in voice_html
    assert "if (speechLike) {\n    if (audioChunks.length > 0) {\n      audioChunks.push(pcm);\n    }\n    silenceStart = null;\n    return;\n  }\n  if (!hasSpeech) return;" in voice_html
    assert "setLevelDb(LEVEL_DB_FLOOR);" in voice_html
    assert "live tuning" not in voice_html
    assert 'id="tuning-close"' not in voice_html
    assert '<span>voice threshold</span>' not in voice_html


def test_voice_html_has_stt_only_tmux_button():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert '<button id="tmux-talk-btn" class="mini-btn" type="button" aria-pressed="false">tmux</button>' in voice_html
    assert "let tmuxTalkActive = false;" in voice_html
    assert "function isTmuxTalkActive() {" in voice_html
    assert "tmux_only: meta.tmuxOnly === true," in voice_html
    assert "tmuxOnly: isTmuxTalkActive()," in voice_html
    assert "void toggleHoldToTalk({ tmuxOnly: true });" in voice_html
    assert "if (event.code === 'KeyA') {" in voice_html
    assert "void beginHoldToTalk({ tmuxOnly: true });" in voice_html
    assert "if (event.code === 'KeyW') {" in voice_html
    assert "document.addEventListener('keyup', (event) => {" in voice_html
    assert "event.code === 'KeyA' && !event.ctrlKey && !event.metaKey" in voice_html
    assert "if (data.type === 'tmux-sent') {" in voice_html


def test_voice_html_gates_ptt_interrupts_and_defers_playback_until_user_turn_finishes():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "let userTurnActive = false;" in voice_html
    assert "let userInputPending = false;" in voice_html
    assert "let userInputPendingTmuxOnly = false;" in voice_html
    assert "function pausePlaybackForUserTurn() {" in voice_html
    assert "currentAudio.pause();" in voice_html
    assert "function finishUserTurn({ sent = false, reason = '' } = {}) {" in voice_html
    assert "userInputPending = Boolean(sent);" in voice_html
    assert "function clearUserInputPending(reason = '') {" in voice_html
    assert "if (!userInputPendingTmuxOnly) {\n        clearUserInputPending('transcript');\n      }" in voice_html
    assert "clearUserInputPending('tmux-sent');" in voice_html
    assert "playNextAudio();" in voice_html
    assert "if (isUserTurnActive()) {\n    if (currentAudio || audioQueue.length > 0) {" in voice_html
    assert "requestInterrupt({ keepPaused: false });\n  }\n\nasync function beginHoldToTalk" not in voice_html


def test_voice_html_tracks_playback_lifecycle_before_showing_speaking():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "let playbackLifecycleState = 'idle';" in voice_html
    assert "function setPlaybackLifecycleState(nextState, item = null, reason = '') {" in voice_html
    assert "setPlaybackLifecycleState('queued', { requestId: playbackRequestId, source: playbackSource }, 'audio-received');" in voice_html
    assert "setPlaybackLifecycleState('accepted', item, manual ? 'manual-play' : 'dequeued');" in voice_html
    assert "setPlaybackLifecycleState('playing', item, 'audio-play');" in voice_html
    assert "setPlaybackLifecycleState('ended', null, 'playback-ended');" in voice_html
    assert "setPlaybackLifecycleState('failed', item, describePlaybackError(error));" in voice_html
    assert "if (!playbackSoftPaused) {\n        setState('speaking');\n      }" not in voice_html
