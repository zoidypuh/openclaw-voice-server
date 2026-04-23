# TODO

- [x] Improve barge-in with an internal-only interrupt confidence score instead of a user-facing slider.
- [x] While the agent is speaking, accumulate confidence from consecutive high-energy and VAD-positive input windows, decay it quickly on silence, and trigger interruption only after the score crosses threshold.
- [x] Keep this as an implementation detail in our existing barge-in path rather than adding more UI controls.
- [ ] Tune the internal confidence thresholds against real usage, especially on Apple browsers.
- [ ] Recheck whether separate internal thresholds for speaking-time interruption vs normal listening improve reliability without needing keyword mode as often.
