-- Central notification retention for every DailyLogNotify PC.
-- This migration ONLY creates an admin-only RPC. Applying it deletes ZERO events.
-- Deletion occurs only on explicit confirmed Admin user action.
--
-- Scopes use Asia/Bangkok calendar boundaries:
--   yesterday = yesterday 00:00 up to today 00:00
--   last_7_days = past seven completed days, excludes today
--   older_than_7_days = only notifications older than 7 full Bangkok days
--   older_than_30_days = only notifications older than 30 full Bangkok days
--   all = every existing notification event before the request
--
-- We leave a dedicated marker event after deletion. Every connected or
-- later-reconnected Notify PC consumes the marker and deletes matching local
-- history records. Markers themselves are never purged by this RPC.
CREATE OR REPLACE FUNCTION public.purge_notification_history(p_scope text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, auth, pg_temp
AS $function$
DECLARE
    v_uid uuid := auth.uid();
    v_workspace uuid;
    v_session uuid;
    v_now timestamptz := clock_timestamp();
    v_today_start timestamptz;
    v_from timestamptz;
    v_to timestamptz;
    v_deleted integer := 0;
    v_marker_id bigint;
    v_scope text := trim(coalesce(p_scope, ''));
    v_payload jsonb;
BEGIN
    IF v_scope NOT IN ('yesterday', 'last_7_days', 'older_than_7_days', 'older_than_30_days', 'all') THEN
        RAISE EXCEPTION 'Invalid history retention scope' USING ERRCODE = '22023';
    END IF;
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
    END IF;

    -- The JWT must identify an active, unrevoked auth.sessions row.
    -- An expired/revoked admin session is not sufficient authorization.
    BEGIN
        v_session := nullif(auth.jwt()->>'session_id', '')::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        v_session := NULL;
    END;
    IF v_session IS NULL OR NOT EXISTS (
        SELECT 1 FROM auth.sessions ss
        WHERE ss.id = v_session AND ss.user_id = v_uid
    ) THEN
        RAISE EXCEPTION 'Active Admin session required' USING ERRCODE = '42501';
    END IF;

    SELECT wm.workspace_id INTO v_workspace
      FROM public.workspace_members wm
     WHERE wm.user_id = v_uid AND lower(coalesce(wm.role, '')) = 'admin'
     ORDER BY wm.created_at DESC LIMIT 1;
    IF v_workspace IS NULL THEN
        RAISE EXCEPTION 'Admin only' USING ERRCODE = '42501';
    END IF;

    v_today_start := (
        date_trunc('day', v_now AT TIME ZONE 'Asia/Bangkok')
        AT TIME ZONE 'Asia/Bangkok'
    );
    IF v_scope = 'yesterday' THEN
        v_from := v_today_start - interval '1 day';
        v_to := v_today_start;
    ELSIF v_scope = 'last_7_days' THEN
        v_from := v_today_start - interval '7 days';
        v_to := v_today_start;
    ELSIF v_scope = 'older_than_7_days' THEN
        v_from := NULL;
        v_to := v_today_start - interval '7 days';
    ELSIF v_scope = 'older_than_30_days' THEN
        v_from := NULL;
        v_to := v_today_start - interval '30 days';
    ELSE
        v_from := NULL;
        v_to := v_now;
    END IF;

    DELETE FROM public.notification_events ne
     WHERE ne.workspace_id = v_workspace
       AND NOT (
           ne.notification_type = 'history_purge'
           AND ne.source_key = '__central_history_purge__'
       )
       AND ne.created_at < v_to
       AND (v_from IS NULL OR ne.created_at >= v_from);
    GET DIAGNOSTICS v_deleted = ROW_COUNT;

    v_payload := jsonb_build_object(
        'version', 1,
        'scope', v_scope,
        'start', v_from,
        'end', v_to,
        'deleted_events', v_deleted
    );
    INSERT INTO public.notification_events (
        workspace_id, source, title, message,
        notification_type, source_key, created_by
    )
    VALUES (
        v_workspace, 'DailyLog Central',
        'Central History Purged', v_payload::text,
        'history_purge', '__central_history_purge__', v_uid
    )
    RETURNING id INTO v_marker_id;

    RETURN v_payload || jsonb_build_object('marker_id', v_marker_id);
END
$function$;

REVOKE ALL ON FUNCTION public.purge_notification_history(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.purge_notification_history(text) FROM anon;
GRANT EXECUTE ON FUNCTION public.purge_notification_history(text) TO authenticated;
