# PDF Source Mode design

## Data flow

Telegram source group document -> authorized intake -> SourceDocument metadata -> local/S3-backed PDF storage -> text extraction (pypdf; OCR optional) -> topic chunks -> source retrieval -> grounded MCQ generation -> source attribution in explanation/card.

## Metadata

Every source document has state scope, subject, title/filename, optional class/exam label, source URL/description, status, page count, and extraction error. State and subject are mandatory before indexing. Source documents uploaded by a global bot admin or a source-group administrator are accepted. A normal group member cannot add source material.

## Source modes

- practice: existing syllabus-grounded AI generation and stored-question fallback.
- source: use only indexed chunks matching the chat state, selected subject, and rotating topic. If no indexed source exists, do not silently substitute a practice question; tell the chat that Source Mode has no ready source for that scope.
- source-preferred: use indexed source chunks first; if unavailable, fall back to practice mode and label the question as practice.

## Document intake

A document posted after the bot is added is placed in awaiting_metadata status and the uploader receives state and subject inline selectors. After both are selected, the bot queues synchronous extraction for small PDFs and stores the result as ready or failed. Large or scanned PDFs should be processed by a background worker in production; OCR is optional and must never fabricate text.

## Chunking

Text is normalized, split by page, then grouped into bounded chunks with page_start/page_end. Each chunk stores a deterministic content hash to avoid duplicate ingestion. Retrieval filters by state/subject and optionally topic keywords; the first implementation uses PostgreSQL/SQLite text search-compatible LIKE matching, with embeddings as a later upgrade.

## Source-grounded generation

The AI receives only the selected source excerpts and is instructed to use them as the factual basis, not to invent unsupported claims. Generated questions retain source metadata in the Question record. The explanation/card can show source title and page range. The existing structural validator, independent validator, and no-repeat history remain active.
