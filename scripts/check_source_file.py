from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path('/home/ubuntu/study_mcq_bot/runtime_test.db')
TARGET = 'rajasthan_history.txt'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

def query(sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]

source_rows = query(
    "SELECT id, filename, state, subject, status, page_count, chunk_count, extraction_error, telegram_chat_id, telegram_message_id, created_at, updated_at FROM source_documents WHERE lower(filename)=lower(?) OR lower(filename) LIKE ? ORDER BY id DESC",
    (TARGET, f'%{TARGET}%'),
)
linked = []
for source in source_rows:
    linked.extend(query(
        "SELECT id, question_text, options, correct_option, state, subject, topic, language, source, source_document_id, source_title, source_page_start, source_page_end, is_active, created_at FROM questions WHERE source_document_id=? ORDER BY id",
        (source['id'],),
    ))
print(json.dumps({
    'target': TARGET,
    'database_exists': DB.exists(),
    'source_documents': source_rows,
    'linked_question_count': len(linked),
    'linked_active_question_count': sum(1 for row in linked if row['is_active']),
    'linked_questions': linked,
}, ensure_ascii=False, indent=2, default=str))
conn.close()
