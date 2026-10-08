import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

type SourceRow = {
  workspace_id: string;
  source_key: string;
  source_name: string;
  source_type: string;
  gas_url: string;
  enabled: boolean;
};

type AnyRow = Record<string, unknown>;

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

function nowIso() {
  return new Date().toISOString();
}

function bangkokTodayKey() {
  const parts = new Intl.DateTimeFormat(
    "en-CA",
    {
      timeZone: "Asia/Bangkok",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    },
  ).formatToParts(new Date());

  const values: Record<string, string> = {};
  for (const part of parts) {
    values[part.type] = part.value;
  }

  return `${values.year}-${values.month}-${values.day}`;
}

function normalize(value: unknown) {
  return String(value ?? "").trim();
}

function dateKeyFromText(value: unknown): string | null {
  const text = normalize(value);
  if (!text) return null;

  const match = text.match(
    /(\d{1,4})[\/.-](\d{1,2})[\/.-](\d{1,4})/,
  );

  if (!match) return null;

  let a = Number(match[1]);
  const b = Number(match[2]);
  let c = Number(match[3]);

  let year: number;
  let month: number;
  let day: number;

  if (match[1].length === 4) {
    year = a > 2400 ? a - 543 : a;
    month = b;
    day = c;
  } else {
    year = c > 2400 ? c - 543 : c;
    if (year < 100) year += 2000;
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

  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function actionUrl(url: string, action: string) {
  const target = new URL(url);
  target.searchParams.set("action", action);
  target.searchParams.set("_central_ts", String(Date.now()));
  return target.toString();
}

async function fetchGasJson(url: string) {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    55_000,
  );

  try {
    const response = await fetch(
      actionUrl(url, "changes"),
      {
        method: "GET",
        headers: {
          "Accept": "application/json",
          "Cache-Control": "no-cache",
          "User-Agent": "DailyLog-Central-Worker/2.0",
        },
        signal: controller.signal,
        redirect: "follow",
      },
    );

    const raw = await response.text();

    if (!response.ok) {
      throw new Error(
        `GAS HTTP ${response.status}: ${raw.slice(0, 240)}`,
      );
    }

    let payload: AnyRow;

    try {
      payload = JSON.parse(raw);
    } catch {
      throw new Error(
        `GAS response is not JSON: ${raw.slice(0, 240)}`,
      );
    }

    if (
      payload.success === false ||
      payload.ok === false
    ) {
      throw new Error(
        normalize(
          payload.error ??
          payload.message ??
          "GAS returned failure",
        ),
      );
    }

    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

async function getState(
  workspaceId: string,
  sourceKey: string,
) {
  const { data, error } = await db
    .from("monitor_state")
    .select("state")
    .eq("workspace_id", workspaceId)
    .eq("source_key", sourceKey)
    .maybeSingle();

  if (error) throw error;

  const state = data?.state;

  return (
    state &&
    typeof state === "object" &&
    !Array.isArray(state)
  )
    ? state as AnyRow
    : {};
}

async function saveState(
  source: SourceRow,
  state: AnyRow,
  errorMessage: string | null = null,
) {
  const payload: AnyRow = {
    workspace_id: source.workspace_id,
    source_key: source.source_key,
    state,
    last_checked_at: nowIso(),
    updated_at: nowIso(),
    last_error: errorMessage,
  };

  if (!errorMessage) {
    payload.last_success_at = nowIso();
  }

  const { error } = await db
    .from("monitor_state")
    .upsert(
      payload,
      {
        onConflict: "workspace_id,source_key",
      },
    );

  if (error) throw error;
}

async function publishEvent(
  source: SourceRow,
  dedupeKey: string,
  title: string,
  message: string,
  notificationType: string,
) {
  const { error } = await db
    .from("notification_events")
    .upsert(
      {
        workspace_id: source.workspace_id,
        source: source.source_name,
        title,
        message,
        notification_type: notificationType,
        created_by: null,
        dedupe_key: dedupeKey,
      },
      {
        onConflict: "workspace_id,dedupe_key",
        ignoreDuplicates: true,
      },
    );

  if (error) throw error;
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

function rowSignature(row: AnyRow) {
  return JSON.stringify(
    rowData(row).map(
      (item) => ({
        column: normalize(item.column),
        header: normalize(item.header),
        value: normalize(item.value),
      }),
    ),
  );
}

function rowMap(row: AnyRow) {
  const result = new Map<string, AnyRow>();

  for (const item of rowData(row)) {
    const key =
      normalize(item.column) ||
      normalize(item.header);

    if (!key) continue;

    result.set(
      key,
      {
        column: normalize(item.column),
        header: normalize(item.header),
        value: normalize(item.value),
      },
    );
  }

  return result;
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

    if (!value) continue;

    lines.push(
      `${itemLabel(item)}: ${value}`,
    );
  }

  if (lines.length) {
    return lines.join("\n");
  }

  const fallback: Array<[string, string]> = [
    ["Model", normalize(row.model)],
    ["VIN", normalize(row.vin)],
    ["Customer", normalize(row.customer)],
    ["Sale", normalize(row.sale)],
    ["Pay Day", normalize(row.pay_day)],
    ["Delivery Date", normalize(row.delivery_date)],
  ];

  return fallback
    .filter(([, value]) => value)
    .map(
      ([label, value]) =>
        `${label}: ${value}`,
    )
    .join("\n") || "ไม่มีข้อมูลในแถว";
}

function diffFullRow(
  oldRow: AnyRow,
  newRow: AnyRow,
) {
  const oldMap = rowMap(oldRow);
  const newMap = rowMap(newRow);
  const keys: string[] = [];

  for (const item of rowData(newRow)) {
    const key =
      normalize(item.column) ||
      normalize(item.header);

    if (key && !keys.includes(key)) {
      keys.push(key);
    }
  }

  for (const item of rowData(oldRow)) {
    const key =
      normalize(item.column) ||
      normalize(item.header);

    if (key && !keys.includes(key)) {
      keys.push(key);
    }
  }

  const changes: string[] = [];

  for (const key of keys) {
    const oldItem =
      oldMap.get(key) ?? {};

    const newItem =
      newMap.get(key) ?? {};

    const before =
      normalize(oldItem.value);

    const after =
      normalize(newItem.value);

    if (before === after) {
      continue;
    }

    const label =
      itemLabel(
        Object.keys(newItem).length
          ? newItem
          : oldItem,
      );

    if (!before && after) {
      changes.push(
        `${label}: เพิ่ม ${after}`,
      );
    } else if (before && !after) {
      changes.push(
        `${label}: ลบ ${before}`,
      );
    } else {
      changes.push(
        `${label}: ${before || "-"} → ${after || "-"}`,
      );
    }
  }

  if (changes.length) {
    return changes;
  }

  const fallbackFields: Array<[string, string]> = [
    ["Model", "model"],
    ["VIN", "vin"],
    ["Customer", "customer"],
    ["Sale", "sale"],
    ["Pay Day", "pay_day"],
    ["Delivery Date", "delivery_date"],
  ];

  for (const [label, key] of fallbackFields) {
    const before = normalize(oldRow[key]);
    const after = normalize(newRow[key]);

    if (before === after) continue;

    if (!before && after) {
      changes.push(
        `${label}: เพิ่ม ${after}`,
      );
    } else if (before && !after) {
      changes.push(
        `${label}: ลบ ${before}`,
      );
    } else {
      changes.push(
        `${label}: ${before || "-"} → ${after || "-"}`,
      );
    }
  }

  return changes;
}

function sourceRows(payload: AnyRow) {
  if (Array.isArray(payload.rows)) {
    return payload.rows;
  }

  if (Array.isArray(payload.data)) {
    return payload.data;
  }

  return [];
}

async function processSale(
  source: SourceRow,
  payload: AnyRow,
  state: AnyRow,
) {
  const current: Record<string, AnyRow> = {};

  for (const item of sourceRows(payload)) {
    if (
      !item ||
      typeof item !== "object" ||
      Array.isArray(item)
    ) {
      continue;
    }

    const row = item as AnyRow;
    const rowNumber = normalize(row.row);

    if (!rowNumber) continue;

    current[rowNumber] = row;
  }

  const version = normalize(payload.version);

  const initialized =
    state.initialized === true &&
    normalize(state.version) === version;

  const previous =
    initialized &&
    state.rows &&
    typeof state.rows === "object" &&
    !Array.isArray(state.rows)
      ? state.rows as Record<string, AnyRow>
      : {};

  if (initialized) {
    for (const [rowNumber, row] of Object.entries(current)) {
      const old = previous[rowNumber];

      if (!old) {
        await publishEvent(
          source,
          `${source.source_key}|new|${rowNumber}|${rowSignature(row)}`,
          `${source.source_name} - เพิ่มข้อมูล`,
          "ข้อมูลที่เพิ่ม\n" + formatFullRow(row),
          "new",
        );
        continue;
      }

      const changes =
        diffFullRow(old, row);

      if (changes.length) {
        await publishEvent(
          source,
          `${source.source_key}|edit|${rowNumber}|${rowSignature(row)}`,
          `${source.source_name} - มีการแก้ไขข้อมูล`,
          (
            "ข้อมูลที่เปลี่ยน\n"
            + changes.join("\n")
            + "\n\nข้อมูลทั้งแถว\n"
            + formatFullRow(row)
          ),
          "edit",
        );
      }
    }

    for (const [rowNumber, old] of Object.entries(previous)) {
      if (rowNumber in current) {
        continue;
      }

      await publishEvent(
        source,
        `${source.source_key}|delete|${rowNumber}|${rowSignature(old)}`,
        `${source.source_name} - ลบข้อมูล`,
        "ข้อมูลที่ถูกลบ\n" + formatFullRow(old),
        "delete",
      );
    }
  }

  const today = bangkokTodayKey();

  for (const [rowNumber, row] of Object.entries(current)) {
    const payToday =
      dateKeyFromText(row.pay_day) === today;

    const deliveryToday =
      dateKeyFromText(row.delivery_date) === today;

    if (!payToday && !deliveryToday) {
      continue;
    }

    let dueKind =
      "Pay Day / Delivery Date วันนี้";

    if (payToday && !deliveryToday) {
      dueKind = "Pay Day วันนี้";
    } else if (deliveryToday && !payToday) {
      dueKind = "ส่งรถวันนี้";
    }

    await publishEvent(
      source,
      `${source.source_key}|due|${today}|${rowNumber}|${normalize(row.pay_day)}|${normalize(row.delivery_date)}`,
      `${source.source_name} - ${dueKind}`,
      "ข้อมูลทั้งแถว\n" + formatFullRow(row),
      "due",
    );
  }

  return {
    initialized: true,
    version,
    rows: current,
    today,
  };
}

async function processSa(
  source: SourceRow,
  payload: AnyRow,
  state: AnyRow,
) {
  const current: Record<string, AnyRow> = {};

  for (const item of sourceRows(payload)) {
    if (
      !item ||
      typeof item !== "object" ||
      Array.isArray(item)
    ) {
      continue;
    }

    const row = item as AnyRow;
    const sheet = normalize(row.sheet);
    const rowNumber = normalize(row.row);

    if (!sheet || !rowNumber) {
      continue;
    }

    current[`${sheet}|${rowNumber}`] = row;
  }

  const version = normalize(payload.version);

  const today =
    normalize(payload.today) ||
    bangkokTodayKey();

  const initialized =
    state.initialized === true &&
    normalize(state.version) === version &&
    normalize(state.today) === today;

  const previous =
    initialized &&
    state.rows &&
    typeof state.rows === "object" &&
    !Array.isArray(state.rows)
      ? state.rows as Record<string, AnyRow>
      : {};

  // New day/version = baseline only.
  // Later scans detect every B:P cell change inside today's
  // merged Column-D ranges.
  if (initialized) {
    for (const [identity, row] of Object.entries(current)) {
      const old = previous[identity];

      if (!old) {
        await publishEvent(
          source,
          `${source.source_key}|new|${today}|${identity}|${rowSignature(row)}`,
          `${source.source_name} - เพิ่มข้อมูล`,
          "ข้อมูลที่เพิ่ม\n" + formatFullRow(row),
          "new",
        );
        continue;
      }

      const changes =
        diffFullRow(old, row);

      if (changes.length) {
        await publishEvent(
          source,
          `${source.source_key}|edit|${today}|${identity}|${rowSignature(row)}`,
          `${source.source_name} - มีการแก้ไขข้อมูล`,
          (
            "ข้อมูลที่เปลี่ยน\n"
            + changes.join("\n")
            + "\n\nข้อมูลทั้งแถว\n"
            + formatFullRow(row)
          ),
          "edit",
        );
      }
    }

    for (const [identity, old] of Object.entries(previous)) {
      if (identity in current) {
        continue;
      }

      await publishEvent(
        source,
        `${source.source_key}|delete|${today}|${identity}|${rowSignature(old)}`,
        `${source.source_name} - ลบข้อมูล`,
        "ข้อมูลที่ถูกลบ\n" + formatFullRow(old),
        "delete",
      );
    }
  }

  return {
    initialized: true,
    version,
    today,
    rows: current,
    mode: normalize(payload.mode),
  };
}

async function processStructured(
  source: SourceRow,
  payload: AnyRow,
  state: AnyRow,
) {
  const events =
    Array.isArray(payload.changes)
      ? payload.changes
      : [];

  for (
    let index = 0;
    index < events.length;
    index++
  ) {
    const item = events[index];

    if (!item || typeof item !== "object") continue;

    const event = item as AnyRow;

    const eventType =
      normalize(event.type) ||
      "row_change";

    const sheet = normalize(event.sheet);
    const row = normalize(event.row);

    const key =
      `${source.source_key}|structured|${eventType}|${sheet}|${row}|${JSON.stringify(event)}`;

    await publishEvent(
      source,
      key,
      `${source.source_name} - แจ้งเตือน`,
      JSON.stringify(
        event,
        null,
        2,
      ),
      eventType.includes("today")
        ? "due"
        : "info",
    );
  }

  return {
    ...state,
    initialized: true,
    last_payload_version:
      normalize(payload.version),
  };
}

async function processSource(
  source: SourceRow,
) {
  const state = await getState(
    source.workspace_id,
    source.source_key,
  );

  try {
    const payload = await fetchGasJson(
      source.gas_url,
    );

    let nextState: AnyRow;

    if (source.source_type === "sale") {
      nextState = await processSale(
        source,
        payload,
        state,
      );
    } else if (source.source_type === "sa") {
      nextState = await processSa(
        source,
        payload,
        state,
      );
    } else {
      nextState = await processStructured(
        source,
        payload,
        state,
      );
    }

    await saveState(
      source,
      nextState,
      null,
    );

    return {
      source_key: source.source_key,
      ok: true,
      count:
        Number(payload.count ?? 0),
      partial:
        payload.partial === true,
    };
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : String(error);

    await saveState(
      source,
      state,
      message,
    );

    return {
      source_key: source.source_key,
      ok: false,
      error: message,
    };
  }
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response(
      "POST required",
      { status: 405 },
    );
  }

  const { data, error } = await db
    .from("monitor_sources")
    .select(
      "workspace_id,source_key,source_name,source_type,gas_url,enabled",
    )
    .eq("enabled", true);

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

  const results = await Promise.all(
    sources.map(
      (source) =>
        processSource(source),
    ),
  );

  return new Response(
    JSON.stringify({
      ok: true,
      checked_at: nowIso(),
      sources: results,
    }),
    {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    },
  );
});
