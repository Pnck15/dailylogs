-- Run this once in Supabase SQL Editor.
-- It adds the username/email of the person who created each DailyLog record.

alter table public.logs
    add column if not exists created_by_name text,
    add column if not exists created_by_email text;

-- Existing records were created before author tracking existed.
-- Keep them as Unknown rather than guessing who created them.
update public.logs
set created_by_name = coalesce(created_by_name, 'Unknown'),
    created_by_email = coalesce(created_by_email, '')
where created_by_name is null
   or created_by_email is null;
