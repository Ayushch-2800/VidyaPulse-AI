-- Task 16: Active Recall Flashcard & Quiz Subsystem
-- One row per (lecture, kind). kind is extensible for future study sets (e.g. 'summary').

CREATE TABLE IF NOT EXISTS study_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lecture_id uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('flashcards', 'quiz')),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
  content jsonb NOT NULL DEFAULT '[]'::jsonb,
  model text,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lecture_id, kind)
);

CREATE INDEX IF NOT EXISTS study_artifacts_user_id_idx ON study_artifacts (user_id);

-- Students read only their own study sets; the FastAPI backend writes with the service-role key.
ALTER TABLE study_artifacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can select own study artifacts"
  ON study_artifacts FOR SELECT
  USING (auth.uid() = user_id);
