AI Quiz Arena implementation changes
This version updates only the independent Arena module and its main-bot command/message routing. Legacy quiz polling, scoring, Auto Quiz, clone management, and Private AI modules are not intentionally changed.
Implemented
Creator setup now presents START QUIZ, INVITE FRIENDS, and INVITE GROUPS after question preparation.
Invitations have ACCEPT and REJECT buttons and a readable NQ-CHAPTER-######## Session ID.
Private chats and groups register through /accept SESSION_ID or the Session ID message handler.
Group members can join a registered group's waiting room with /accept SESSION_ID or the plain Session ID.
Only people who answer at least one actual quiz poll are counted as attended participants.
Capacity is enforced transactionally: up to 5 group destinations and 10 private destinations, including the creator's own destination when applicable.
A database-backed group lock prevents one group from being part of two active Arena sessions. Locks are acquired atomically when a session starts and released on finish, stop, or failure. One creator may have only one pending/active session at a time.
Invitations expire 15 minutes after the prepared quiz is ready. Invitations close when the creator starts the session.
/stop is creator-only. /reject and /quizstatus are added; the Arena command set is /quiz, /accept, /reject, /stop, /quizstatus.
The former global one-session index is removed so independent groups can run sessions concurrently.
Group leaderboard ranks by average points per unique member who answered at least one poll. Waiting-room members who never answer are excluded. Public group usernames link to their Telegram page.
Question bank supports pyq_year, question_type, and detailed_solution; AI-generated questions are not assigned an unverified PYQ year. Every poll has a button to retrieve the detailed solution.
A curated source-context table is added. If verified NCERT/syllabus/PYQ excerpts are stored there, the generator retrieves them before generation.
Questions are locally checked for JSON structure, four distinct options, valid correct index, non-empty explanation, Telegram poll length limits, and duplicate question hashes. A repair call is used only if local validation rejects the first response.
Started sessions can recover after a Render restart. Unstarted drafts cannot safely resume because the creator configuration and generation task are held in memory; those drafts are marked failed rather than left stuck.
Telegram constraints that remain
Inline-mode callback updates do not contain the destination chat ID. Tapping ACCEPT therefore displays the Session ID; the recipient/admin must send /accept SESSION_ID in that destination chat. The Bot API does not allow the inline callback to register the destination directly.
Telegram cannot delete an inline-mode message using only its inline message ID. REJECT edits the inline invitation to a rejected notice. A normal bot message can be deleted.
A private recipient must start the bot before the bot can message that recipient.
Group members can send a plain Session ID only if the bot can receive ordinary group messages (typically bot admin or privacy mode disabled). /accept SESSION_ID works as a command when group privacy mode is enabled.
Verification performed
Python syntax compilation passed for all .py files in the project.
No live Telegram Bot API, Render deployment, or Neon database integration test was possible in this environment. Therefore this package is not represented as guaranteed 100% live-working; it must be deployed and tested in your bot's actual Telegram chats and Neon database.


## 2026-11-07 — Flexible Arena generation

See `AI_QUIZ_ARENA_FLEXIBLE_MODE.md`. Invalid individual questions are skipped; one repair request attempts to fill the gaps; sessions proceed with at least 80% valid questions. Actual question count and credit cost are used. No SQL migration is required.
