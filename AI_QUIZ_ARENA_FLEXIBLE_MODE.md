# AI Quiz Arena — Flexible Question Validation

## Behavior
- Arena accepts a partially valid question batch when at least 80% of the requested total is available.
- Examples: 8/10, 12/15, 16/20, 4/5, and 36/45 can proceed.
- Below the 80% threshold, preparation fails safely and no credits are deducted.
- Invalid individual AI items are skipped and logged with item position and validation reason.
- One repair-generation call is made for the missing items. Valid questions from the first response are retained if repair fails or is incomplete.
- Duplicate generated questions already present in the chapter bank are skipped rather than causing the entire batch to fail.
- The session stores the actual question count. Credits are calculated from the actual number of questions that will run (one credit per five questions, rounded up).
- No SQL migration is required for this change.

## Deployment
Replace the existing project files with this ZIP and redeploy on Render. No environment-variable changes are required for this patch.

## Verification
`ai_quiz_arena.py` passes Python syntax compilation. The partial parser was tested with one valid item and one malformed item; the valid item was retained and the malformed item's reason was reported. Live Gemini, Telegram, and Neon integration tests have not been performed.
