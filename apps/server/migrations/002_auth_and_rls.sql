-- 1. Function and Trigger to auto-sync Supabase auth.users to public.users
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (id, email, preferred_language)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'preferred_language', 'en')
  )
  ON CONFLICT (id) DO UPDATE
  SET email = EXCLUDED.email;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Drop trigger if exists and recreate
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 2. Enable Row Level Security (RLS) on all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE lectures ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE visual_chunks ENABLE ROW LEVEL SECURITY;

-- 3. RLS Policies for Users Table
CREATE POLICY "Users can view own profile" 
  ON users FOR SELECT 
  USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" 
  ON users FOR UPDATE 
  USING (auth.uid() = id);

-- 4. RLS Policies for Lectures Table
CREATE POLICY "Users can select own lectures" 
  ON lectures FOR SELECT 
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own lectures" 
  ON lectures FOR INSERT 
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own lectures" 
  ON lectures FOR UPDATE 
  USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own lectures" 
  ON lectures FOR DELETE 
  USING (auth.uid() = user_id);

-- 5. RLS Policies for Transcript Chunks Table
CREATE POLICY "Users can select own transcript chunks" 
  ON transcript_chunks FOR SELECT 
  USING (
    EXISTS (
      SELECT 1 FROM lectures 
      WHERE lectures.id = transcript_chunks.lecture_id 
        AND lectures.user_id = auth.uid()
    )
  );

CREATE POLICY "Users can insert own transcript chunks" 
  ON transcript_chunks FOR INSERT 
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM lectures 
      WHERE lectures.id = transcript_chunks.lecture_id 
        AND lectures.user_id = auth.uid()
    )
  );

-- 6. RLS Policies for Visual Chunks Table
CREATE POLICY "Users can select own visual chunks" 
  ON visual_chunks FOR SELECT 
  USING (
    EXISTS (
      SELECT 1 FROM lectures 
      WHERE lectures.id = visual_chunks.lecture_id 
        AND lectures.user_id = auth.uid()
    )
  );

CREATE POLICY "Users can insert own visual chunks" 
  ON visual_chunks FOR INSERT 
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM lectures 
      WHERE lectures.id = visual_chunks.lecture_id 
        AND lectures.user_id = auth.uid()
    )
  );
