import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

type AnyRow = Record<string, unknown>;

type SourceRow = {
  workspace_id: string;
  source_key: string;
  source_name: string;
  source_type: string;
  enabled: boolean;
};

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error("Missing Supabase service configuration");
}

const db = createClient(
  supabaseUrl,
  serviceRoleKey,
  {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  },
);

function normalize(value: unknown) {
  return String(value ?? "").trim();
}

function bangkokNowParts() {
  const parts = new Intl.DateTimeFormat(
    "en-GB",
    {
      timeZone: "Asia/Bangkok",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    },
  ).formatToParts(new Date());

  const values: Record<string, string> = {};

  for (const part of parts) {
    values[part.type] = part.value;
  }

  const year = values.year;
  const month = values.month;
  const day = values.day;
  const hour = Number(values.hour);
  const minute = Number(values.minute);

  return {
    dateKey: `${year}-${month}-${day}`,
    hour,
    minute,
    minuteOfDay: (hour * 60) + minute,
    clock: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`,
  };
}

function rowData(row: AnyRow): AnyRow[] {
  const items = row.row_data;

  if (!Array.isArray(items)) {
    return [];
  }

  return items.filter(
    (item) =>
      item &&
      typeof item === "object" &&
      !Array.isArray(item),
  ) as AnyRow[];
}

function rowDataColumn(
  row: AnyRow,
  column: string,
) {
  const wanted = normalize(column).toUpperCase();

  for (const item of rowData(row)) {
    if (
      normalize(item.column).toUpperCase()
      === wanted
    ) {
      return normalize(item.value);
    }
  }

  return "";
}

function itemLabel(item: AnyRow) {
  const column = normalize(item.column);
  const header = normalize(item.header);

  if (column && header) {
    return `${column} - ${header}`;
  }

  return header || column || "ข้อมูล";
}

function formatFullRow(row: AnyRow) {
  const lines: string[] = [];

  for (const item of rowData(row)) {
    const value = normalize(item.value);

    if (!value) {
      continue;
    }

    lines.push(
      `${itemLabel(item)}: ${value}`,
    );
  }

  return lines.join("\n") || "ไม่มีข้อมูลในแถว";
}

function dateKeyFromText(value: unknown): string | null {
  const text = normalize(value);

  if (!text) {
    return null;
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return text;
  }

  const match = text.match(
    /(\d{1,4})[\/.-](\d{1,2})[\/.-](\d{1,4})/,
  );

  if (!match) {
    return null;
  }

  const a = Number(match[1]);
  const b = Number(match[2]);
  const c = Number(match[3]);

  let year: number;
  let month: number;
  let day: number;

  if (match[1].length === 4) {
    year = a > 2400 ? a - 543 : a;
    month = b;
    day = c;
  } else {
    year = c > 2400 ? c - 543 : c;
    if (year < 100) {
      year += 2000;
    }
    month = b;
    day = a;
  }

  if (
    !Number.isFinite(year) ||
    !Number.isFinite(month) ||
    !Number.isFinite(day)
  ) {
    return null;
  }

  return (
    `${String(year).padStart(4, "0")}-`
    + `${String(month).padStart(2, "0")}-`
    + `${String(day).padStart(2, "0")}`
  );
}

function parseAppointmentMinutes(value: unknown): number | null {
  const text = normalize(value)
    .replace(/：/g, ":")
    .replace(/，/g, ",");

  if (!text) {
    return null;
  }

  const match = text.match(
    /(?:^|\D)(\d{1,2})(?:[:.](\d{1,2}))?(?!\d)/,
  );

  if (!match) {
    return null;
  }

  const hour = Number(match[1]);
  const minute = Number(match[2] ?? "0");

  if (
    !Number.isInteger(hour) ||
    !Number.isInteger(minute) ||
    hour < 0 ||
    hour > 23 ||
    minute < 0 ||
    minute > 59
  ) {
    return null;
  }

  return (hour * 60) + minute;
}

function stableIdentity(row: AnyRow) {
  const sheet = normalize(row.sheet);
  const sequence =
    normalize(row.sequence) ||
    rowDataColumn(row, "C");
  const plate =
    normalize(row.plate) ||
    rowDataColumn(row, "F");

  if (sequence || plate) {
    return `${sheet}|C=${sequence}|F=${plate}`;
  }

  return `${sheet}|ROW=${normalize(row.row)}`;
}

async function publishEvent(
  source: SourceRow,
  dedupeKey: string,
  title: string,
  message: string,
) {
  const { error } = await db
    .from("notification_events")
    .upsert(
      {
        workspace_id: source.workspace_id,
        source_key: source.source_key,
        source: source.source_name,
        title,
        message,
        notification_type: "reminder",
        created_by: null,
        dedupe_key: dedupeKey,
      },
      {
        onConflict: "workspace_id,dedupe_key",
        ignoreDuplicates: true,
      },
    );

  if (error) {
    throw error;
  }
}

async function processSource(
  source: SourceRow,
  now: ReturnType<typeof bangkokNowParts>,
) {
  const { data, error } = await db
    .from("monitor_state")
    .select("state")
    .eq("workspace_id", source.workspace_id)
    .eq("source_key", source.source_key)
    .maybeSingle();

  if (error) {
    throw error;
  }

  const state =
    data?.state &&
    typeof data.state === "object" &&
    !Array.isArray(data.state)
      ? data.state as AnyRow
      : {};

  const rows =
    state.rows &&
    typeof state.rows === "object" &&
    !Array.isArray(state.rows)
      ? state.rows as Record<string, AnyRow>
      : {};

  let published = 0;

  for (const row of Object.values(rows)) {
    if (
      !row ||
      typeof row !== "object" ||
      Array.isArray(row)
    ) {
      continue;
    }

    const mergedRange = normalize(row.merged_range);
    const inMergedGroup =
      row.in_merged_date_group === true ||
      Boolean(mergedRange);

    if (!inMergedGroup) {
      continue;
    }

    const appointmentDate =
      dateKeyFromText(
        row.appointment_date ??
        row.group_date ??
        row.date ??
        rowDataColumn(row, "D"),
      );

    if (
      !appointmentDate ||
      appointmentDate !== now.dateKey
    ) {
      continue;
    }

    const appointmentTime =
      normalize(row.appointment_time)
      || rowDataColumn(row, "B");

    const appointmentMinute =
      parseAppointmentMinutes(
        appointmentTime,
      );

    if (appointmentMinute === null) {
      continue;
    }

    const delta =
      appointmentMinute
      - now.minuteOfDay;

    let kind = "";
    let titleSuffix = "";

    if (delta === 10) {
      kind = "before10";
      titleSuffix = "นัดหมายอีก 10 นาที";
    } else if (delta === 0) {
      kind = "ontime";
      titleSuffix = "ถึงเวลานัดหมาย";
    } else {
      continue;
    }

    const identity =
      stableIdentity(row);

    const message = (
      `เวลานัดหมาย 预约时间: ${appointmentTime}\n`
      + `วันที่ 日期: ${appointmentDate}\n`
      + (
        mergedRange
          ? `Merged D: ${mergedRange}\n`
          : ""
      )
      + "\nรายละเอียดแจ้ง:\n"
      + formatFullRow(row)
    );

    await publishEvent(
      source,
      (
        `${source.source_key}|appointment|${kind}|`
        + `${appointmentDate}|${appointmentTime}|${identity}`
      ),
      `${source.source_name} - ${titleSuffix}`,
      message,
    );

    published += 1;
  }

  return published;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response(
      "POST required",
      { status: 405 },
    );
  }

  const now = bangkokNowParts();

  const { data, error } = await db
    .from("monitor_sources")
    .select(
      "workspace_id,source_key,source_name,source_type,enabled",
    )
    .eq("enabled", true)
    .eq("source_type", "sa");

  if (error) {
    return new Response(
      JSON.stringify({
        ok: false,
        error: error.message,
      }),
      {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  }

  const sources = (data ?? []) as SourceRow[];
  const results: AnyRow[] = [];

  for (const source of sources) {
    try {
      const published = await processSource(
        source,
        now,
      );

      results.push({
        source_key: source.source_key,
        ok: true,
        published,
      });
    } catch (error) {
      results.push({
        source_key: source.source_key,
        ok: false,
        error:
          error instanceof Error
            ? error.message
            : String(error),
      });
    }
  }

  return new Response(
    JSON.stringify({
      ok: true,
      bangkok_date: now.dateKey,
      bangkok_time: now.clock,
      results,
    }),
    {
      headers: {
        "Content-Type": "application/json",
      },
    },
  );
});
