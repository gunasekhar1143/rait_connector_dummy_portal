Generate complete SQLite schema and seeding code for:

$ARGUMENTS

Produce:
1. CREATE TABLE IF NOT EXISTS DDL for all specified tables with foreign keys and NOT NULL constraints
2. Required PRAGMA statements: journal_mode=WAL, foreign_keys=ON
3. Async Python seeding function using aiosqlite with INSERT OR IGNORE (idempotent)
4. Python seed data constants as typed List[tuple] with inline column-name comments

Hard rules:
- CREATE TABLE IF NOT EXISTS only — never DROP TABLE
- INSERT OR IGNORE for all seed data — never DELETE + re-insert
- Include one index per foreign key column (for JOIN performance)
- AUTOINCREMENT only on surrogate integer PKs; use TEXT PKs for business IDs
- Add a brief SQL comment on each table: -- <one-line purpose>

Output: complete Python code block ready to paste into database.py.
