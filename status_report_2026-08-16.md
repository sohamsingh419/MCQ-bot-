# Telegram Study MCQ Bot — Current Status Audit

**Audit date:** 16 August 2026  
**Database audited:** `runtime_test.db`  
**Current process:** PID `57350`, verified alive  
**Regression suite:** 107 tests passed

## Executive verdict

The bot’s core quiz, state-wise settings, XP, leaderboard, source indexing, OCR health checks, mock-test lifecycle, targeted delivery, and multilingual data paths are implemented and currently running. However, it would not be accurate to call every feature completely perfect. The most important current limitations are AI-provider quota errors, the absence of a live-news key for Current Affairs, the need to complete metadata for one uploaded PDF, and the Telegram limitation around reading the correct answer from a forwarded quiz poll.

The active question pool is functioning, but it is not evenly populated across every state–subject–language combination. Some scopes have dozens of questions, while some have only one or two. This is why a group configured for a sparse scope may fall back to an existing stored question or report that no unseen question is available.

## Runtime health

| Area | Current result |
|---|---|
| Bot process | Alive, PID `57350` |
| Database | SQLite runtime database available and readable |
| OCR | Ready; Tesseract detected with `eng`, `hin`, and `osd` |
| PDF tools | Poppler tools detected |
| Minimum group interval | 10 minutes |
| Configured PDF source group | `-1004342424852` |
| Configured forwarded-MCQ group | `-1003974533700` |
| Automated tests | 107 passed |
| Active mock tests at audit time | None; historical records only |

The runtime log also shows provider cooldown and fallback events. These are handled without crashing the bot, but they slow or prevent new AI-generated questions while the providers are rate-limited.

## Question inventory

The database currently contains **557 questions**, of which **446 are active** and **111 are inactive historical records**. Active retrieval uses only the unified `Exam` metadata value. The old difficulty values remain only in inactive historical records for backward compatibility.

| Question source | Total | Active | Meaning |
|---|---:|---:|---|
| AI-generated | 501 | 394 | Generated through the provider rotation and validation pipeline |
| PDF/source-grounded | 56 | 52 | Generated or stored with a source-document reference |
| **Total** | **557** | **446** | Active delivery uses the active column only |

At the time of this audit, the database contains **no successfully imported forwarded-poll batch** from the new bulk group. The bulk workflow is configured, but forwarded Telegram quiz polls are currently rejected when the bot cannot obtain the hidden correct-option metadata. The question shown in the Telegram client may visibly display a result, but the forwarded Bot API payload does not reliably expose that answer to this importer.

### Active question types

| Question type | Total records | Active |
|---|---:|---:|
| Conceptual | 82 | 82 |
| Analytical | 71 | 71 |
| Case-based | 69 | 69 |
| Chronology/order | 67 | 67 |
| Match-the-following | 59 | 59 |
| Statement-based | 53 | 53 |
| Multiple-statement | 44 | 44 |
| Assertion–Reason | 47 | 1 |
| Application-based | 65 | 0 |

The active policy checks are clean: **zero active Application-based questions** and **zero active non-Reasoning Assertion–Reason questions**. The one active Assertion–Reason record belongs to the permitted Reasoning scope. Historical Application-based and retired non-Reasoning Assertion–Reason rows remain inactive, not deliverable.

### Language distribution

| Language | Total | Active |
|---|---:|---:|
| Hindi | 552 | 442 |
| English | 5 | 4 |

Hindi is therefore the effective default and dominant pool language. English support exists, but the English pool is currently very small.

### State distribution

| State/scope | Total | Active |
|---|---:|---:|
| Rajasthan | 319 | 253 |
| All India | 91 | 70 |
| General | 67 | 56 |
| Haryana | 43 | 34 |
| Bihar | 36 | 32 |
| Chhattisgarh | 1 | 1 |

The internal topic master covers all 28 Indian states plus India GK, but the question database is not yet equally populated for all of them. The topic master is a generation-coverage system; it does not mean that every state and subject already has a large stored question bank.

### Subject distribution

| Subject | Total | Active |
|---|---:|---:|
| General Science | 88 | 67 |
| Geography | 85 | 63 |
| History | 81 | 63 |
| Indian Polity | 76 | 63 |
| State GK | 70 | 56 |
| State Geography | 50 | 42 |
| State History | 29 | 28 |
| State History & Culture | 25 | 20 |
| State Polity & Administration | 14 | 11 |
| Economics | 11 | 10 |
| Reasoning | 6 | 6 |
| Computer | 6 | 5 |
| Indian Culture | 5 | 5 |
| State Current Affairs | 4 | 2 |
| State Art & Culture | 4 | 3 |
| Environment | 3 | 2 |

The largest active subject pools are General Science, Geography, History, Indian Polity, and State GK. Economics, Reasoning, Computer, Environment, and Current Affairs are currently much smaller.

## Question generation and validation process

For an AI-generated question, the bot chooses a state, subject, language, hidden topic, and question type. It then asks the configured provider rotation to produce one structured MCQ, applies schema and content checks, and sends the item through the independent validator chain. The active standard is one unified factual Exam level; public Easy, Medium, Hard, Advanced, and Expert selectors have been removed.

The configured provider order is Gemini, Groq, Mistral, and an OpenAI-compatible fallback. Runtime logs show Gemini and Groq returning rate-limit responses during the audit, while Mistral and the OpenAI-compatible fallback also had connection/unavailability events. The fallback logic and cooldowns work, but fallback cannot create a question when every provider is unavailable. Validator disagreement or malformed short questions are rejected rather than delivered.

The bot deliberately does not invent Current Affairs when no live-news source is configured. The audit log showed Current Affairs scopes falling back to stored questions or reporting that no unseen question is available. This is correct safety behavior, but it means Current Affairs coverage is presently limited.

## PDF/source system

The configured PDF group is `-1004342424852`. OCR is ready for Hindi scanned PDFs. The database contains four source-document records:

| Source document | State | Subject | Status | Pages | Chunks |
|---|---|---|---|---:|---:|
| First uploaded PDF | Rajasthan | State History & Culture | Ready | 14 | 4 |
| `Raj_geo.pdf` pending record | Not selected | Not selected | Awaiting metadata | 0 | 0 |
| `Raj_geo.pdf` processed record | Rajasthan | State Geography | Ready | 1 | 1 |
| Rajasthan History PDF | Rajasthan | State History | Ready | 314 | 128 |
| **Totals** |  |  | **3 ready, 1 pending** |  | **133 chunks** |

The existing PDF pipeline extracts text or OCR, indexes source chunks, maps them to the selected state and subject, and grounds later generation. For a clearly structured MCQ PDF containing question, four options, and an answer key, the new exact-MCQ parser stores the question without AI rewriting. That exact-MCQ path has been implemented and tested synthetically, but no successfully imported MCQ PDF batch is yet visible in this runtime database; the current 56 source-linked records predate or represent source-grounded storage rather than a completed new exact-MCQ import batch.

The scanned Rajasthan History document contains OCR noise in some chunks. OCR being operational means text can be extracted; it does not guarantee that every scanned page will be perfectly recognized. Questions from unclear extraction should not be treated as automatically verified.

## Group and user features

The database currently has **12 group-settings records**. Eight groups are actively sending scheduled quizzes, while four are inactive or used for source/admin purposes. All recorded group intervals are 10 minutes. Group settings show Hindi as the language in the audited records.

The implemented group-side features include group welcome handling, state selection, state-aware subject selection, inline settings, interval control, quiz start/stop, explanation control, subject rotation, mock-test commands, and admin-only controls. DM settings and private quizzes are implemented separately from group settings.

There are **5 known users** in the runtime database. Two records have completed onboarding. User scores, attempts, correct/wrong counts, XP, streaks, and leaderboard fields are being recorded; the largest recorded user has 60 attempts and 44 correct answers.

## Mock tests

The database contains 19 historical mock tests: **15 completed** and **4 cancelled**, with no active mock test at audit time. The recent mock-test changes include a dedicated question-type sequence, requested-type filtering for cached questions, controlled fallback when a requested type is unavailable, structural checks for Statement-based and Multiple-statement stems, and full-card rendering before the answer poll for structured questions.

These changes address the reported problem of repeated Statement-based questions and incomplete stems. Nevertheless, a fresh live mock test should be used for final Telegram UI verification because historical mock rows were created before the latest delivery changes.

## Delivery, XP, and administration

Three delivery campaigns are recorded, all completed successfully: two targeted text campaigns and one targeted poll campaign. The delivery system supports targeted state-based delivery, broadcast audience selection, text, quiz polls, and video workflows, with durable campaign and receipt records.

The public difficulty selector has been removed. Active questions all use `Exam`; historical inactive questions retain old difficulty values. Some persisted group `xp_map` JSON values still contain legacy level keys because the database column was retained for compatibility, but active scoring and generation use the unified Exam policy. This is a cosmetic/historical storage detail rather than an active difficulty selector.

Admin commands include group configuration, question testing, mock-test control, delivery/broadcast controls, source inspection, manual question management, and the new `/bulksend` entry point. The PDF source group and bulk forwarded-MCQ group are now separate and configured.

## What is working versus what is not yet perfect

| Area | Status | Honest assessment |
|---|---|---|
| Bot process and Telegram polling | Working | Current process is alive and started normally |
| Hindi default and onboarding | Working | Hindi dominates the active pool; onboarding records exist |
| State-wise subjects | Working | State-aware settings and scopes are active |
| 10-minute minimum interval | Working | All audited group settings show 10 minutes |
| AI question generation | Working with limitations | Provider rotation works, but current quotas/rate limits slow or block fresh generation |
| Independent validator | Working | Rejects malformed, unsupported, or disputed MCQs |
| Question-type rotation | Working in code/tests | Fresh mock test should be used for final live confirmation |
| No-repeat history | Working in code | Permanent quiz history is stored; sparse scopes can still run out of unseen questions |
| PDF OCR/indexing | Working | OCR health is ready; extraction quality depends on the PDF |
| Exact structured-MCQ PDF import | Implemented, not yet proven on a real batch | No completed exact-MCQ PDF batch appears in the current DB |
| Forwarded-poll bulk import | Partially working | Group and command are configured, but hidden answer metadata blocks automatic import |
| Current Affairs | Limited | No live-news key; bot correctly avoids fabricating facts |
| Mock-test results and lobby | Working in historical records | No active mock at audit time; fresh live test needed for UI confirmation |
| Broadcast/targeted delivery | Working | Three completed campaigns are recorded |
| English pool | Available but sparse | Only 4 active English questions currently exist |

## Final conclusion

The bot is operational and the majority of its core architecture is working. It is **not yet a perfectly self-sufficient question system for every state and every subject**. At present, the strongest coverage is Hindi Rajasthan, All India, Haryana, Bihar, and the main subjects such as General Science, Geography, History, Indian Polity, and State GK. The weakest coverage is Current Affairs, Environment, Computer, Reasoning, English, and several state-specific subject combinations.

The two most important practical limitations are the current AI-provider rate limits and the forwarded-poll answer limitation. The PDF OCR/indexing path is healthy, but the pending `Raj_geo.pdf` metadata record should be completed before relying on it for that source. The recent mock-test fixes are present and covered by tests, but a new live mock should be run for final visual confirmation.
