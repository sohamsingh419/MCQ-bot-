from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

DB_PATH = Path(os.environ.get("AUDIT_DB", "/home/ubuntu/study_mcq_bot/runtime_test.db"))
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

def rows(sql: str, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]

def scalar(sql: str, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None

def columns(table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

result: dict[str, object] = {"database": str(DB_PATH), "exists": DB_PATH.exists()}
if not DB_PATH.exists():
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0)

result["tables"] = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
result["questions"] = {
    "total": scalar("SELECT COUNT(*) FROM questions"),
    "active": scalar("SELECT COUNT(*) FROM questions WHERE is_active = 1"),
    "inactive": scalar("SELECT COUNT(*) FROM questions WHERE is_active = 0"),
    "by_source": rows("SELECT COALESCE(source,'NULL') AS source, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions GROUP BY source ORDER BY count DESC"),
    "by_source_document": rows("SELECT COALESCE(source,'NULL') AS source, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions WHERE source_document_id IS NOT NULL GROUP BY source ORDER BY count DESC"),
    "by_difficulty": rows("SELECT difficulty, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions GROUP BY difficulty ORDER BY count DESC"),
    "by_type": rows("SELECT question_type, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions GROUP BY question_type ORDER BY count DESC"),
    "active_policy_checks": {
        "active_application_based": scalar("SELECT COUNT(*) FROM questions WHERE is_active=1 AND question_type='Application-based'"),
        "active_non_reasoning_assertion_reason": scalar("SELECT COUNT(*) FROM questions WHERE is_active=1 AND question_type='Assertion-Reason' AND subject <> 'Reasoning'"),
        "active_statement_based": scalar("SELECT COUNT(*) FROM questions WHERE is_active=1 AND question_type='Statement-based'"),
        "active_multiple_statement": scalar("SELECT COUNT(*) FROM questions WHERE is_active=1 AND question_type='Multiple-statement'"),
    },
    "by_language": rows("SELECT language, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions GROUP BY language ORDER BY count DESC"),
    "by_state": rows("SELECT state, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions GROUP BY state ORDER BY count DESC"),
    "by_subject": rows("SELECT subject, COUNT(*) AS count, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active FROM questions GROUP BY subject ORDER BY count DESC"),
    "active_by_scope": rows("SELECT state, subject, language, COUNT(*) AS active FROM questions WHERE is_active=1 GROUP BY state, subject, language ORDER BY active DESC, state, subject"),
}
for table, key in [("source_documents", "source_documents"), ("source_chunks", "source_chunks"), ("group_settings", "group_settings"), ("users", "users"), ("mock_tests", "mock_tests"), ("delivery_campaigns", "delivery_campaigns")]:
    if table in result["tables"]:
        result[key] = {"total": scalar(f"SELECT COUNT(*) FROM {table}"), "rows": rows(f"SELECT * FROM {table} LIMIT 100")}

if "source_documents" in result:
    result["source_documents"]["by_status"] = rows("SELECT status, COUNT(*) AS count FROM source_documents GROUP BY status ORDER BY count DESC")
    result["source_documents"]["by_scope"] = rows("SELECT state, subject, status, COUNT(*) AS count FROM source_documents GROUP BY state, subject, status ORDER BY count DESC")
if "group_settings" in result:
    group_columns = columns("group_settings")
    group_key = "group_id" if "group_id" in group_columns else "chat_id"
    wanted = [name for name in (group_key, "chat_type", "state", "language", "interval_minutes", "subjects", "is_active") if name in group_columns]
    result["group_settings"]["summary"] = rows(f"SELECT {', '.join(wanted)} FROM group_settings ORDER BY {group_key}")
if "mock_tests" in result:
    result["mock_tests"]["by_status"] = rows("SELECT status, COUNT(*) AS count FROM mock_tests GROUP BY status ORDER BY count DESC")
if "delivery_campaigns" in result:
    result["delivery_campaigns"]["by_mode"] = rows("SELECT mode, audience, content_type, COUNT(*) AS count FROM delivery_campaigns GROUP BY mode, audience, content_type ORDER BY count DESC")

print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
conn.close()
