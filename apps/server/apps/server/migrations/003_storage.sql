-- 1. Create Private Storage Buckets
INSERT INTO storage.buckets (id, name, public) 
VALUES 
  ('lectures-audio', 'lectures-audio', false),
  ('lecture-keyframes', 'lecture-keyframes', false),
  ('student-exports', 'student-exports', false)
ON CONFLICT (id) DO NOTHING;

-- 2. Ensure RLS is enabled on the Storage Objects table
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- 3. RLS Policies: Users can only upload, read, and delete THEIR OWN files
CREATE POLICY "Users can upload their own files" 
ON storage.objects FOR INSERT TO authenticated 
WITH CHECK (auth.uid() = owner);

CREATE POLICY "Users can view their own files" 
ON storage.objects FOR SELECT TO authenticated 
USING (auth.uid() = owner);

CREATE POLICY "Users can update their own files" 
ON storage.objects FOR UPDATE TO authenticated 
USING (auth.uid() = owner);

CREATE POLICY "Users can delete their own files" 
ON storage.objects FOR DELETE TO authenticated 
USING (auth.uid() = owner);
