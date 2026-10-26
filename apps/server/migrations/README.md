# Supabase migrations

Run these in the Supabase SQL editor (Database, SQL Editor, New query), in this order. The
backend never runs them itself.

| Order | File | What it adds | Safe to re-run |
|---|---|---|---|
| 0 | *(base schema, not in this folder)* | `users`, `lectures`, `transcript_chunks`, `visual_chunks`, `keyframes`, `multimodal_chunks` (with `vector(1536)` embeddings), the `match_multimodal_chunks` search function, and the private `lectures` storage bucket. These were created in the Supabase dashboard during the early tasks. | n/a |
| 1 | `002_auth_and_rls.sql` | Signup trigger that copies `auth.users` into `users`, and row-level security on the base tables | No (policies already exist the second time) |
| 2 | `003_storage.sql` | Private buckets `lectures-audio`, `lecture-keyframes`, `student-exports` and owner-only storage policies | No (same reason) |
| 3 | `004_cheat_sheets.sql` | `cheat_sheets` and `exam_topics` (Task 15). Then run `python seed_exam_topics.py` once to fill `exam_topics`. | No |
| 4 | `005_study_artifacts.sql` | `study_artifacts` for flashcards and quizzes (Task 16) | No |
| 5 | `006_workspace.sql` | Summaries in `study_artifacts`, `notes`, and the `translations` cache (Task 18) | Yes |

## Check a project

`check_schema.sql` is read-only. Run it in the SQL editor of any project and every row should say
`ok`; a `missing` row says what to create or which file to run.

## Production project

The simplest production setup is the Supabase project you already use: it has the base schema,
the buckets and every migration you have run. Run `check_schema.sql` there and fix anything it
lists (for example `006_workspace.sql`, if it has not been run there yet).

A second, empty project needs the base schema copied from the current one, since it is not in
this folder:

```bash
# Connection strings: Project Settings, Database, Connection string (URI). Use the
# "Session pooler" string if your network has no IPv6.
supabase db dump --db-url "$CURRENT_DB_URL" -f schema.sql      # Supabase CLI, public schema
psql "$NEW_DB_URL" -f schema.sql
```

The dump covers tables, functions and policies in `public`, not storage buckets or the trigger on
`auth.users`. Run `check_schema.sql` in the new project and fix what it lists: create the private
`lectures` bucket in Storage, run `003_storage.sql`, and re-create the signup trigger with the
first block of `002_auth_and_rls.sql`. Then run `python seed_exam_topics.py` with the new project's
keys to fill `exam_topics`.
