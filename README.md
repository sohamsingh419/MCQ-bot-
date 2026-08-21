# GSI Study MCQ Quiz Bot

This repository contains a production-oriented Python Telegram study bot for private learners, study groups, imported MCQ sources, and administrator-created official competitions. The bot uses asynchronous polling, SQLAlchemy 2.x, PostgreSQL in production, and an OpenAI-compatible provider layer with the existing Gemini, Groq, Mistral, and primary-provider configuration preserved.

> **Security rule:** Never commit `.env`, API keys, bot tokens, database passwords, runtime databases, source uploads, or logs. Use Render secret variables or another protected environment-variable store.

## Current behavior

Private onboarding is **Language → State → Subjects → Done**. There is no exam-selection step. Hindi is the default UI language, the learner can switch to English, and all learner-facing MCQ content remains Hindi. State users start with only their State GK umbrella subject; All India users start with only All India GK. The umbrella subjects rotate through their hidden state or national topic catalogs. If a learner selects explicit subjects, the umbrella default is replaced and questions remain limited to those selected subjects.

Subject rotation and explanations are permanently enabled. Each successful automatic delivery alternates between an AI-generated question and an imported source-file question. If the preferred pool is temporarily unavailable, the bot falls back safely without stalling. Delivered questions are tracked to prevent repetition.

The bot sends native Telegram quiz polls with four options, records poll answers, awards XP and streak bonuses, supports group and private schedules, quiet hours, leaderboards, daily challenges, mock tests, GSI Quiz and Star Quiz competitions, multilingual UI, support links, OCR-backed PDF intake, bulk MCQ import, and administrator diagnostics. Telegram quiz polls require a quiz poll type and a correct option; non-anonymous polls are used so answer updates can be attributed to learners.[1]

## Repository structure

```text
study_mcq_bot/
├── bot/
│   ├── main.py
│   ├── config.py
│   ├── data/                  # hidden internal topic rotation data
│   ├── database/              # SQLAlchemy models, migrations, repositories
│   ├── handlers/              # Telegram commands, callbacks, intake flows
│   ├── services/              # AI, quiz, source, scheduler, scoring services
│   └── utils/
├── assets/                    # official winner cards and stickers
├── data/                      # extracted topic notes used during development
├── docs/
├── scripts/
├── tests/
├── Dockerfile
├── render.yaml
├── requirements.txt
└── .env.example
```

## Main commands

| Command | Access | Purpose |
|---|---|---|
| `/start`, `/help`, `/rules` | Everyone | Open onboarding, help, or bilingual rules |
| `/profile`, `/score`, `/stats`, `/rank` | Everyone | View learner progress and group statistics |
| `/leaderboard`, `/daily`, `/weekly`, `/monthly` | Everyone | View rankings and period summaries |
| `/subjects` | Everyone | View subjects available for the current state |
| `/settings` | Group administrators or private user | Open the settings panel |
| `/setlanguage` | Group administrator or private user | Select Hindi or English UI |
| `/setstate` | Group administrator | Select All India or a state |
| `/setsubjects` | Group administrator | Select one or more subjects |
| `/setinterval` | Group administrator | Select a 10, 15, 20, 30, or 60-minute interval |
| `/startquiz`, `/stopquiz` | Group administrator or private user | Start or stop automatic delivery |
| `/mocktest`, `/stopmocktest` | Group administrator | Manage a synchronized mock test |
| `/createquiz`, `/quiz`, `/cancelquiz` | Bot administrator / official flow | Create and run GSI or Star Quiz competitions |
| `/addquestion`, `/removequestion` | Group administrator | Manage validated manual MCQs |
| `/sources`, `/bulksend` | Authorized bot administrator | Inspect indexed sources or import forwarded MCQs |
| `/broadcast`, `/targeted`, `/deliver` | Configured bot administrator | Deliver approved content to selected audiences |
| `/groupstats`, `/botreport` | Group or bot administrator | View group performance or diagnostics |
| `/status` | Configured bot administrator | View users, groups, bot-admin readiness, active quizzes, stored questions, sources, and scheduler state |

The removed commands `/testquestion`, `/setrotation`, `/setexplanation`, `/setmode`, and difficulty-selection flows are not part of the current user-facing system. Legacy database columns remain only where compatibility requires them. All supported commands are also registered in Telegram’s command menu during startup; admin-only commands still enforce their normal permission checks.

When the bot is added to a group without admin rights, it records the join time and sends the same bilingual readiness reminder at **10 minutes, 1 hour, 2 hours, 6 hours, 12 hours, 24 hours, and 48 hours**. Once Telegram reports that the bot is an administrator, the reminder state is permanently closed for that membership period. No reminder is sent after the 48-hour checkpoint.

## Configuration

Copy the template and set secrets locally only when needed:

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt
python3 -m bot.main
```

For production, use PostgreSQL with the async SQLAlchemy URL form. Render’s managed PostgreSQL connection string is normalized by `bot.config.Settings` when it arrives as `postgres://` or `postgresql://`.

| Variable group | Important variables |
|---|---|
| Telegram and database | `BOT_TOKEN`, `DATABASE_URL` |
| Existing AI providers | `AI_API_KEY`, optional `AI_BASE_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY` and their model variables |
| Administrators | `ADMIN_USER_IDS` |
| Source mode | `SOURCE_GROUP_ID`, `BULK_SOURCE_GROUP_ID`, `SOURCE_OCR_ENABLED`, `SOURCE_STORAGE_DIR`, `SOURCE_INGEST_TIMEOUT_SECONDS` |
| Official competitions | `OFFICIAL_QUIZ_CONFIG_GROUP_ID`, `OFFICIAL_QUIZ_PLAY_GROUP_ID` |
| Support links | `SUPPORT_CHANNEL_URL`, `SUPPORT_GROUP_URL`, `OWNER_CONTACT_URL` |
| Operations | `TIMEZONE`, `SCHEDULER_TICK_SECONDS`, `LOG_LEVEL`, `LOG_FILE` |

The Docker image installs Poppler, Tesseract, Hindi OCR data, and the Python `python-docx` dependency required for PDF, OCR, and DOCX ingestion. Runtime source storage is configurable. The included Render Blueprint uses `/tmp` for source files because the default worker filesystem is not a durable document archive; imported and validated questions remain in PostgreSQL, while original documents should be retained in the source Telegram group or moved to a persistent storage strategy.

## Render deployment

This bot is a **background worker**, not an HTTP web service. Long polling and the in-process scheduler require exactly one live process for a bot token. The repository includes `Dockerfile`, `.dockerignore`, and `render.yaml` so Render can build a Docker worker and provision a managed PostgreSQL database. Render’s Blueprint specification supports Docker workers with `type: worker`, `runtime: docker`, and a repository-root Dockerfile; it also supports secure `sync: false` variables and `fromDatabase` references for PostgreSQL.[2]

### Recommended deployment steps

1. Push this repository to a private GitHub, GitLab, or Bitbucket repository. Do not push `.env` or any populated secret file.
2. In the Render dashboard, create a new **Blueprint** and connect the repository. Render reads the root `render.yaml` by default.[3]
3. Enter the prompted values for `BOT_TOKEN`, `AI_API_KEY`, the available Gemini/Groq/Mistral keys, `ADMIN_USER_IDS`, and optional `NEWS_API_KEY`.
4. Review the generated worker and PostgreSQL resources, then deploy the Blueprint.
5. Confirm the worker log contains `Database initialized, Telegram command menu registered, and scheduler started`, `Application started`, and successful Telegram polling activity.
6. Test `/start`, `/help`, `/rules`, `/settings`, source ingestion, and one official quiz in the configured Telegram chats.

Only one Render worker should use the bot token. Running the same token locally at the same time can create competing polling consumers.

## Database and source durability

PostgreSQL is required for a multi-group production deployment. SQLite remains useful for local tests only. The application creates additive schema migrations during startup and preserves legacy columns where compatibility is needed.

Source ingestion accepts PDF, scanned PDF with OCR, DOCX, TXT, CSV, JSON, XML, HTML, RTF, and related text formats. The source Telegram group is the operational source of truth. If the original uploaded files must remain available after a Render restart, attach a durable disk or keep a separate object-storage backup; the default Render worker filesystem is not a permanent archive.

## Testing and checks

Run the same checks used before packaging:

```bash
python3 -m compileall -q bot scripts tests
TIMEZONE=UTC PYTHONPATH=. pytest -q
```

The `TIMEZONE=UTC` override keeps time-sensitive unit tests outside the configured 00:00–07:00 IST quiet-hours window. Production remains configured with `TIMEZONE=Asia/Kolkata`.

## References

[1]: https://core.telegram.org/bots/api#sendpoll "Telegram Bot API — sendPoll"
[2]: https://render.com/docs/blueprint-spec "Render Blueprint YAML Reference"
[3]: https://render.com/docs/infrastructure-as-code "Render Blueprints and Infrastructure as Code"
