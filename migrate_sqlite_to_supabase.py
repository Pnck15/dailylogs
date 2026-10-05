import argparse
import getpass
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("ไม่พบ SUPABASE_URL หรือ SUPABASE_PUBLISHABLE_KEY ใน .env")


def valid_sqlite(path: Path):
    if not path.is_file():
        return False
    try:
        with path.open("rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return False
        con = sqlite3.connect(str(path), timeout=5)
        ok = con.execute("PRAGMA integrity_check").fetchone()
        con.close()
        return bool(ok and ok[0] == "ok")
    except sqlite3.Error:
        return False


def choose_database(explicit=None):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not valid_sqlite(p):
            raise SystemExit(f"SQLite ใช้งานไม่ได้: {p}")
        return p

    here = Path(__file__).resolve().parent
    candidates = [
        here / "daily_log.db",
        here / "dist" / "daily_log.db",
        here / "dist" / "DailyLog" / "daily_log.db",
        here.parent / "daily_log.db",
    ]

    for p in candidates:
        if valid_sqlite(p):
            return p

    raise SystemExit(
        "ไม่พบ SQLite database ที่ใช้งานได้\n"
        "ใช้ --db C:\\path\\daily_log.db เพื่อระบุไฟล์เอง"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="path ของ daily_log.db")
    args = parser.parse_args()

    db_path = choose_database(args.db)
    print("SQLite:", db_path)

    email = input("Supabase email: ").strip()
    password = getpass.getpass("Supabase password: ")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    auth = supabase.auth.sign_in_with_password(
        {"email": email, "password": password}
    )

    if not auth.user or not auth.session:
        raise SystemExit("Login ไม่สำเร็จ")

    user_id = auth.user.id

    membership = (
        supabase.table("workspace_members")
        .select("workspace_id, role")
        .eq("user_id", user_id)
        .execute()
    )

    if not membership.data:
        raise SystemExit("User ยังไม่ได้อยู่ใน Workspace")

    workspace_id = membership.data[0]["workspace_id"]
    print("Workspace:", workspace_id)

    con = sqlite3.connect(str(db_path))
    rows = con.execute("""
        SELECT id, log_date, log_time, title, description
        FROM logs
        ORDER BY id ASC
    """).fetchall()
    con.close()

    print("SQLite logs:", len(rows))

    if not rows:
        print("ไม่มีข้อมูลให้ย้าย")
        return

    existing = (
        supabase.table("logs")
        .select("legacy_id")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    existing_ids = {
        int(r["legacy_id"])
        for r in existing.data
        if r.get("legacy_id") is not None
    }

    to_insert = []
    skipped = 0

    for row_id, log_date, log_time, title, description in rows:
        if row_id in existing_ids:
            skipped += 1
            continue

        to_insert.append({
            "workspace_id": workspace_id,
            "created_by": user_id,
            "updated_by": user_id,
            "legacy_id": row_id,
            "log_date": str(log_date),
            "log_time": str(log_time),
            "title": str(title),
            "description": description or "",
        })

    print("Already migrated:", skipped)
    print("To migrate:", len(to_insert))

    if not to_insert:
        print("Migration complete: ไม่มีข้อมูลใหม่")
        return

    batch_size = 100
    migrated = 0

    for start in range(0, len(to_insert), batch_size):
        batch = to_insert[start:start + batch_size]
        response = supabase.table("logs").insert(batch).execute()
        migrated += len(response.data)
        print(f"Uploaded {migrated}/{len(to_insert)}")

    print("================================")
    print("MIGRATION COMPLETE")
    print("================================")


if __name__ == "__main__":
    main()
