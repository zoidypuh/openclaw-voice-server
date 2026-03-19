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
    assert "await ensureAudio();\n  await loadRuntimeState();\n  await connect();" in voice_html
    assert "currentAudio.playsInline = true;" in voice_html
    assert "handleResumeFailure(error);" in voice_html


def test_voice_html_uses_echo_controls_and_apple_specific_barge_in_guard():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert "function isAppleVoiceClient()" in voice_html
    assert "function allowsFreeformBargeIn()" in voice_html
    assert "if (allowFreeformBargeIn) {\n      pausePlaybackForBargeIn();\n    }" in voice_html
    assert "if (allowFreeformBargeIn && (result.action === 'send' || result.usableSpeech)) {" in voice_html
    assert "echoCancellation: true," in voice_html
    assert "noiseSuppression: true," in voice_html
    assert "autoGainControl: true," in voice_html
    assert "processor.connect(processorSink);" in voice_html


def test_voice_html_has_mute_button_and_mic_gate():
    voice_html = (_static_dir() / "voice.html").read_text(encoding="utf-8")

    assert '<button id="mute-btn" class="mini-btn" type="button">mute</button>' in voice_html
    assert "let muted = false;" in voice_html
    assert "function setMutedState(nextMuted) {" in voice_html
    assert "track.enabled = !muted;" in voice_html
    assert "if (muted) {" in voice_html
    assert "document.getElementById('mute-btn').addEventListener('click', () => {" in voice_html
