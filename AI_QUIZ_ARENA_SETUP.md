AI NEET Quiz Arena — updated implementation
Commands
Arena-specific commands (five):
/quiz Chapter Name — configure and prepare a quiz.
/accept SESSION_ID — register a private chat/group or join a registered group's waiting room.
/reject SESSION_ID — reject the chat invitation or leave a group's waiting room.
/stop — only the session creator can stop the synchronized session.
/quizstatus — show the creator's latest pending/active session and destination counts.
Quiz generation and question bank
Gemini model is selected through GEMINI_MODEL; main.py defaults to gemini-3.8-flash.
The engine retrieves curated chapter source text from arena_chapter_sources, when present, then asks Gemini for four-option, single-correct NEET-style questions.
Supported formats include standard single-correct, assertion-reason, and statement-based MCQs. Each poll includes a Detailed Solution button; the poll's built-in explanation remains short.
Local validation checks JSON shape, exactly four distinct options, correct-option index, non-empty explanation, Telegram poll length limits, and duplicates. A second Gemini call is made only if this local validation rejects the first response, to repair the malformed/invalid structure.
No primary PYQ corpus is bundled. Therefore AI-generated questions are saved with pyq_year = NULL; the model is not allowed to invent a PYQ year.
Factual accuracy cannot be guaranteed by structural validation or model generation alone. Curated source rows should be inserted into arena_chapter_sources for real NCERT/latest-syllabus grounding, and exam-critical content should be reviewed against the original source.
Source context table
arena_chapter_sources accepts:
source_type: ncert, neet_syllabus, or pyq_pattern
chapter_key: normalized chapter name (lowercase, single spaces)
language: english, hindi, or all
source_title and source_text: source title and the relevant excerpt
The application automatically retrieves up to 12 matching source records (up to 24,000 characters total) for AI generation. The migration creates the table but does not invent or populate source content.
1,000-question bank rule
Bank capacity is 1,000 unique approved records per chapter-language pair.
Until that bank reaches 1,000, AI-generated sessions are limited to 5, 10, 15, or 20 questions.
Once it reaches 1,000, users can choose 5 through 45 questions in the existing increments.
Full banks are selected directly from PostgreSQL; Gemini is not called.
Only structurally valid, unique questions are saved. Database trigger enforces the 1,000-record cap.
Session and invitations
Creator sees three buttons after question preparation: START QUIZ, INVITE FRIENDS, INVITE GROUPS.
Session IDs use NQ-CHAPTER-########.
Invitations expire 15 minutes after questions are ready.
Maximum destinations: 5 groups and 10 private chats. The creator's own destination is included in the relevant cap.
A group admin registers the group. Members can send the Session ID individually (or /accept SESSION_ID) to join the waiting room.
A user is counted as a participant only after answering at least one quiz poll. Merely accepting an invite or joining the waiting room does not count.
A user is assigned to the first destination in which they answer; duplicate participation across group/private destinations is ignored.
Invitations close as soon as the creator starts the quiz.
A database-backed group lock prevents one group from being part of two active Arena sessions. Pending invitations may be accepted, but when a session starts it must atomically acquire every invited group's lock; a competing session cannot start in that group. Different groups may run independent sessions. One creator may have only one pending/active Arena session at a time.
Telegram platform constraints
Inline-mode invitation callbacks do not include the destination chat ID. Therefore tapping ACCEPT displays the Session ID; the user/admin must send that ID in the destination chat or use /accept SESSION_ID. This is a Telegram Bot API limitation.
Inline-mode messages cannot be deleted by inline message ID. REJECT edits the inline invitation to a rejected notice; normal bot messages can be deleted.
Private recipients must start the bot before the bot can message them.
To receive a plain Session ID in a group, the bot must be an administrator or have privacy mode disabled. /accept SESSION_ID is the reliable fallback when group privacy mode is enabled.
The bot must be present in every group and allowed to send polls.
Leaderboards
Individual leaderboard combines all eligible users in one session.
Group leaderboard ranks by average score: group average = total points of attended members / unique members who answered at least one quiz.
Waiting-room members who never answer are excluded from the denominator.
Group average is displayed to two decimal places.
Public groups with a known username are linked to https://t.me/<username>; private groups are plain text.
A participant is inserted into the attended-participant table only on their first actual poll answer.
Recovery and isolation
Started sessions are recovered from PostgreSQL after a Render restart.
Unstarted drafts are marked failed on restart because their creator configuration and generation task are in process memory.
Poll delivery failure in one destination does not stop other destinations; failed groups release their group lock.
Existing legacy quiz/scoring tables are not reused or modified by the Arena module.
Neon migration
Run NEON_ARENA_MIGRATION_SAFE.sql once in Neon SQL Editor before deploying the updated code. It is intentionally re-runnable and contains no DELETE, TRUNCATE, or DROP TABLE statements. It only creates missing objects, adds missing columns, and replaces obsolete index/constraint/trigger definitions; existing records are preserved.
