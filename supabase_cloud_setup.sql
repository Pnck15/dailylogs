-- =========================================================
-- Mini Daily Log - Cloud migration support
-- Run this AFTER the main Workspace/RLS setup already used.
-- =========================================================

alter table public.logs
add column if not exists legacy_id bigint;

create unique index if not exists ux_logs_workspace_legacy_id
on public.logs(workspace_id, legacy_id)
where legacy_id is not null;

select id, workspace_id, legacy_id, log_date, log_time, title
from public.logs
order by id desc
limit 20;
