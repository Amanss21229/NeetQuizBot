# AI NEET Quiz Arena

This is an isolated module. It uses its own `arena_*` PostgreSQL tables and does not reuse or alter the legacy quiz poll/score tables.

## Environment

- `BOT_TOKEN` — existing main bot token.
- `DATABASE_URL` — existing PostgreSQL URL.
- `GEMINI_API_KEY` — required for AI generation until a chapter/language bank reaches 1,000 questions.
- `GEMINI_MODEL` — optional model override; defaults to the existing Gemini provider default (`gemini-3.8-flash`).

The bot's inline mode must be enabled with BotFather (`/setinline`) for the **Invite groups / users** chat picker to work. The bot must be a member of every group in which it needs to publish quiz polls and must have permission to send polls.

## Commands

- `/quiz Chapter Name` — configure language, number of questions and seconds per question.
- `/accept SESSION_ID` — accept an inline invitation in the current private chat or group. In groups, only an administrator/creator can accept.
- `/stop` — remove the current private chat from the active quiz; in groups, only an administrator/creator can use it.

## Credit rule

One credit pays for five questions. The cost is `ceil(question_count / 5)`: 5=1, 10=2, ... 45=9. Credits are debited atomically only after generation and structural/audit checks pass.

## Question bank

Questions are saved per normalized chapter and language, with a maximum of 1,000 unique question records for each chapter/language pair. Once the bank reaches 1,000, sessions use a random database selection rather than calling Gemini. A session's question set is stored as JSON in PostgreSQL before the first poll is sent.

## Important Telegram constraints

Telegram inline-mode callback updates do not include the destination chat ID. Therefore, when an inline invitation is posted into a chat, the Accept button displays the `/accept SESSION_ID` instruction; the recipient must run that command in the target chat. Reject edits the inline invitation to a rejected notice because Telegram does not provide a delete-by-inline-message-ID method. This is a Bot API limitation, not an application setting.

Telegram does not report users who merely view a poll and never answer any question. The leaderboard therefore includes every user who answered at least one question; their unanswered count is computed as the selected quiz length minus their answered questions.

## Accuracy note

The generator validates the JSON schema, exactly four distinct options, a single answer index, uniqueness within a generated set, and runs a separate AI audit pass before accepting a set. This reduces errors but cannot mathematically guarantee that every AI-authored fact is correct. For strict exam publication, review generated question sets against the current NCERT text and official NEET-UG syllabus before relying on them as authoritative material.
