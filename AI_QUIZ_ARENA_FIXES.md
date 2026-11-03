# AI Quiz Arena fixes (2026-11-03)

This build changes the Arena start/stop lifecycle.

- Questions are generated and saved in the background as soon as the invitation screen is created. The creator should wait for the `questions are ready` confirmation before pressing `Done — Start quiz`.
- Pressing Done while preparation is still running no longer blocks or starts a second generation attempt.
- The first poll is scheduled 3 seconds after Done. Poll delivery to accepted destinations is concurrent (up to 10 at a time).
- A per-session lock serializes start, stop, and question delivery.
- `/stop` cancels the complete synchronized session across every accepted destination, including draft/preparing/ready/active sessions, and removes queued Arena jobs. A creator can stop from private chat; a group admin can stop from a participating group.
- Cancelled sessions no longer occupy the global single-session database index, so a new `/quiz` can be created.
- The final leaderboard is delivered concurrently to every destination that remained joined when the quiz ended.

## Timing note

The first question is scheduled for 3 seconds after Done once preparation has completed. Telegram API/network latency can still affect actual delivery. Fresh AI question generation cannot be guaranteed to complete in under 5 seconds if the creator presses Done before the background preparation confirmation; the intended workflow is to share invitations while preparation runs, then press Done after the confirmation. The final leaderboard is sent immediately after the last poll's configured time window closes, subject to Telegram delivery latency.

No new Neon SQL migration is required; the module's existing `initialize()` method creates/updates the Arena tables and indexes.
