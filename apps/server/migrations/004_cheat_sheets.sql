-- Task 15: Automated PYQ Mapping & Formula Cheat-Sheet Engine
-- Assumes lectures.id is a uuid (Supabase default) and pgvector is already enabled.

-- 1. One cheat sheet per lecture, regenerated in place
CREATE TABLE IF NOT EXISTS cheat_sheets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lecture_id uuid NOT NULL UNIQUE REFERENCES lectures(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
  content jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {definitions: [...], theorems: [...], formulas: [...]}
  topic_tags jsonb NOT NULL DEFAULT '[]'::jsonb, -- lecture-level exam topics, best match first
  model text,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 2. Seeded JEE/NEET/UPSC/GATE syllabus topics, embedded with the same 1536-d Gemini model
CREATE TABLE IF NOT EXISTS exam_topics (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  exam text NOT NULL,
  subject text NOT NULL,
  topic text NOT NULL,
  embedding vector(1536),
  UNIQUE (exam, subject, topic)
);

-- 3. RLS: students read only their own lectures' cheat sheets; topics are public reference data.
-- The FastAPI backend writes with the service-role key, which bypasses RLS.
ALTER TABLE cheat_sheets ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_topics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can select own cheat sheets"
  ON cheat_sheets FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM lectures
      WHERE lectures.id = cheat_sheets.lecture_id
        AND lectures.user_id = auth.uid()
    )
  );

CREATE POLICY "Anyone signed in can read exam topics"
  ON exam_topics FOR SELECT TO authenticated
  USING (true);
