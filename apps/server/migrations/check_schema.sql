-- Read-only check that a Supabase project has everything the app needs.
-- Paste into the SQL editor of the production project and run it: every row should say ok.
-- A "missing" row names what to create or which migration to run (see README.md here).

WITH checks(item, present, fix) AS (
  VALUES
    ('pgvector extension',
      EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector'),
      'Database, Extensions: enable "vector"'),
    ('table users',             to_regclass('public.users') IS NOT NULL, 'base schema'),
    ('table lectures',          to_regclass('public.lectures') IS NOT NULL, 'base schema'),
    ('table transcript_chunks', to_regclass('public.transcript_chunks') IS NOT NULL, 'base schema'),
    ('table visual_chunks',     to_regclass('public.visual_chunks') IS NOT NULL, 'base schema'),
    ('table keyframes',         to_regclass('public.keyframes') IS NOT NULL, 'base schema'),
    ('table multimodal_chunks', to_regclass('public.multimodal_chunks') IS NOT NULL, 'base schema'),
    ('function match_multimodal_chunks',
      EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'match_multimodal_chunks'),
      'base schema'),
    ('lectures.media_bucket_path column',
      EXISTS (SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'lectures'
                AND column_name = 'media_bucket_path'),
      'base schema'),
    ('signup trigger on_auth_user_created',
      EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'on_auth_user_created'),
      '002_auth_and_rls.sql'),
    ('RLS on lectures',
      COALESCE((SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass('public.lectures')), false),
      '002_auth_and_rls.sql'),
    ('bucket lectures',
      EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'lectures'),
      'Storage: new private bucket "lectures"'),
    ('bucket lectures-audio',
      EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'lectures-audio'),
      '003_storage.sql'),
    ('bucket lecture-keyframes',
      EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'lecture-keyframes'),
      '003_storage.sql'),
    ('table cheat_sheets',      to_regclass('public.cheat_sheets') IS NOT NULL, '004_cheat_sheets.sql'),
    ('table exam_topics',       to_regclass('public.exam_topics') IS NOT NULL, '004_cheat_sheets.sql'),
    ('table study_artifacts',   to_regclass('public.study_artifacts') IS NOT NULL, '005_study_artifacts.sql'),
    ('study_artifacts accepts summary',
      EXISTS (SELECT 1 FROM pg_constraint
              WHERE conname = 'study_artifacts_kind_check'
                AND pg_get_constraintdef(oid) LIKE '%summary%'),
      '006_workspace.sql'),
    ('table notes',             to_regclass('public.notes') IS NOT NULL, '006_workspace.sql'),
    ('table translations',      to_regclass('public.translations') IS NOT NULL, '006_workspace.sql')
)
SELECT item,
       CASE WHEN present THEN 'ok' ELSE 'missing' END AS status,
       CASE WHEN present THEN '' ELSE fix END AS how_to_fix
FROM checks
ORDER BY present, item;
