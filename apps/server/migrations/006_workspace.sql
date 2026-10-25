-- Task 18: Multilingual Student Workspace & Notes Exporter
-- Safe to re-run. Run after 005_study_artifacts.sql.

-- 1. Lecture summaries are stored next to the flashcards and quiz
ALTER TABLE study_artifacts DROP CONSTRAINT IF EXISTS study_artifacts_kind_check;
ALTER TABLE study_artifacts ADD CONSTRAINT study_artifacts_kind_check
  CHECK (kind IN ('flashcards', 'quiz', 'summary'));

-- 2. Student notes: saved answers, flashcards and formulas, plus the student's own notes
CREATE TABLE IF NOT EXISTS notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lecture_id uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  kind text NOT NULL DEFAULT 'note'
    CHECK (kind IN ('note', 'answer', 'flashcard', 'formula')),
  title text NOT NULL DEFAULT '',
  body text NOT NULL DEFAULT '',      -- markdown with $...$ math and [MM:SS] citations
  timestamp_seconds double precision, -- where in the lecture the note points, if anywhere
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notes_lecture_id_idx ON notes (lecture_id, created_at);

-- Students manage only their own notes; the FastAPI backend writes with the service-role key.
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own notes" ON notes;
CREATE POLICY "Users can manage own notes"
  ON notes FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- 3. Translation cache: each text is sent to Gemini once per language, then served from here.
-- Backend-only (service role), so RLS is on with no policies.
CREATE TABLE IF NOT EXISTS translations (
  source_hash text NOT NULL, -- sha256 of the source text
  language text NOT NULL,    -- hi, ta, te, mr or bn
  translated_text text NOT NULL,
  model text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_hash, language)
);

ALTER TABLE translations ENABLE ROW LEVEL SECURITY;
