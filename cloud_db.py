import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client


class CloudDB:
    """Cloud data layer for DailyLog using Supabase Auth + RLS."""

    def __init__(self):
        app_dir = Path(
            sys.executable if getattr(sys, "frozen", False) else __file__
        ).resolve().parent

        load_dotenv(app_dir / ".env")
        load_dotenv()

        self.url = os.getenv("SUPABASE_URL", "").strip()
        self.key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()

        if not self.url:
            raise ValueError("ไม่พบ SUPABASE_URL ในไฟล์ .env")
        if not self.key:
            raise ValueError("ไม่พบ SUPABASE_PUBLISHABLE_KEY ในไฟล์ .env")

        self.client = create_client(self.url, self.key)
        self.user = None
        self.session = None
        self.workspace_id: Optional[str] = None
        self.role: Optional[str] = None
        self.username = ""
        self.email = ""

    @staticmethod
    def make_username(email: str) -> str:
        """Return the app display name for a logged-in email."""
        email = str(email or "").strip().lower()
        display_names = {
            "pnck533@gmail.com": "pear",
        }
        if email in display_names:
            return display_names[email]
        if not email:
            return "Unknown"
        return email.split("@", 1)[0]

    def login(self, email: str, password: str):
        response = self.client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )

        self.user = response.user
        self.session = response.session

        if not self.user or not self.session:
            raise RuntimeError("Login ไม่สำเร็จ: ไม่พบ user/session")

        membership = (
            self.client.table("workspace_members")
            .select("workspace_id, user_id, role")
            .eq("user_id", self.user.id)
            .execute()
        )

        if not membership.data:
            self.client.auth.sign_out()
            self.user = None
            self.session = None
            raise RuntimeError("User นี้ยังไม่ได้อยู่ใน Workspace")

        self.workspace_id = membership.data[0]["workspace_id"]
        self.role = membership.data[0].get("role")
        self.email = str(getattr(self.user, "email", None) or email).strip()
        self.username = self.make_username(self.email)

        return self.user

    def logout(self):
        try:
            self.client.auth.sign_out()
        finally:
            self.user = None
            self.session = None
            self.workspace_id = None
            self.role = None
            self.username = ""
            self.email = ""

    def _require_login(self):
        if not self.user or not self.session or not self.workspace_id:
            raise RuntimeError("ยังไม่ได้ Login")

    @staticmethod
    def _row_to_tuple(row):
        return (
            row.get("id"),
            row.get("log_date"),
            row.get("log_time"),
            row.get("title"),
            row.get("description") or "",
            CloudDB.make_username(row.get("created_by_email") or row.get("created_by_name") or ""),
            row.get("created_by_email") or "",
        )

    def get_log_dates(self):
        self._require_login()
        response = (
            self.client.table("logs")
            .select("log_date")
            .eq("workspace_id", self.workspace_id)
            .execute()
        )
        return {str(row["log_date"]) for row in response.data if row.get("log_date")}

    def get_logs_for_date(self, log_date: str):
        self._require_login()
        try:
            response = (
                self.client.table("logs")
                .select("id, log_date, log_time, title, description, created_by_name, created_by_email")
                .eq("workspace_id", self.workspace_id)
                .eq("log_date", log_date)
                .order("log_time", desc=False)
                .execute()
            )
        except Exception as error:
            if "created_by_name" in str(error) or "created_by_email" in str(error):
                response = (
                    self.client.table("logs")
                    .select("id, log_date, log_time, title, description")
                    .eq("workspace_id", self.workspace_id)
                    .eq("log_date", log_date)
                    .order("log_time", desc=False)
                    .execute()
                )
            else:
                raise error
        return [self._row_to_tuple(row) for row in response.data]

    def search_logs(self, keyword: str):
        self._require_login()
        try:
            response = (
                self.client.table("logs")
                .select("id, log_date, log_time, title, description, created_by_name, created_by_email")
                .eq("workspace_id", self.workspace_id)
                .or_(f"title.ilike.%{keyword}%,description.ilike.%{keyword}%")
                .order("log_date", desc=True)
                .order("log_time", desc=True)
                .execute()
            )
        except Exception as error:
            if "created_by_name" in str(error) or "created_by_email" in str(error):
                response = (
                    self.client.table("logs")
                    .select("id, log_date, log_time, title, description")
                    .eq("workspace_id", self.workspace_id)
                    .or_(f"title.ilike.%{keyword}%,description.ilike.%{keyword}%")
                    .order("log_date", desc=True)
                    .order("log_time", desc=True)
                    .execute()
                )
            else:
                raise error
        return [self._row_to_tuple(row) for row in response.data]

    def get_log(self, log_id: int):
        self._require_login()
        try:
            response = (
                self.client.table("logs")
                .select("id, log_date, log_time, title, description, created_by_name, created_by_email")
                .eq("workspace_id", self.workspace_id)
                .eq("id", log_id)
                .limit(1)
                .execute()
            )
        except Exception as error:
            if "created_by_name" in str(error) or "created_by_email" in str(error):
                response = (
                    self.client.table("logs")
                    .select("id, log_date, log_time, title, description")
                    .eq("workspace_id", self.workspace_id)
                    .eq("id", log_id)
                    .limit(1)
                    .execute()
                )
            else:
                raise error

        if not response.data:
            return None
        return self._row_to_tuple(response.data[0])

    def add_log(self, log_date: str, log_time: str, title: str, description: str):
        self._require_login()
        payload = {
            "workspace_id": self.workspace_id,
            "created_by": self.user.id,
            "updated_by": self.user.id,
            "created_by_name": self.username,
            "created_by_email": self.email,
            "log_date": log_date,
            "log_time": log_time,
            "title": title,
            "description": description,
        }
        try:
            response = self.client.table("logs").insert(payload).execute()
        except Exception as error:
            if "created_by_name" in str(error) or "created_by_email" in str(error):
                raise RuntimeError(
                    "ยังไม่ได้เพิ่มคอลัมน์ผู้บันทึกใน Supabase logs\n"
                    "ให้รันไฟล์ add_log_author_columns.sql ก่อน"
                ) from error
            raise
        return response.data[0] if response.data else None

    def upsert_monitor_source(
        self,
        source_key: str,
        source_name: str,
        source_type: str,
        gas_url: str,
        enabled: bool = True,
        publish_to_notify: bool = True,
        display_order: int = 100,
    ):
        self._require_login()

        if str(self.role or "").lower() != "admin":
            raise RuntimeError(
                "เฉพาะ Admin เท่านั้นที่ตั้งค่า Central Monitor ได้"
            )

        payload = {
            "workspace_id": self.workspace_id,
            "source_key": str(source_key or "").strip(),
            "source_name": str(source_name or "").strip(),
            "source_type": str(source_type or "").strip(),
            "gas_url": str(gas_url or "").strip(),
            "enabled": bool(enabled),
            "publish_to_notify": bool(
                publish_to_notify
            ),
            "display_order": int(
                display_order or 100
            ),
            "updated_by": self.user.id,
        }

        if not payload["source_key"] or not payload["gas_url"]:
            raise ValueError(
                "source_key และ gas_url ห้ามว่าง"
            )

        response = (
            self.client.table("monitor_sources")
            .upsert(
                payload,
                on_conflict="workspace_id,source_key",
            )
            .execute()
        )

        return response.data[0] if response.data else None

    def list_monitor_sources(self):
        self._require_login()

        if str(self.role or "").lower() != "admin":
            raise RuntimeError(
                "เฉพาะ Admin เท่านั้นที่ดู Central Monitor Sources ได้"
            )

        response = (
            self.client.table("monitor_sources")
            .select(
                "source_key,source_name,source_type,gas_url,"
                "enabled,publish_to_notify,display_order,"
                "created_at,updated_at"
            )
            .eq(
                "workspace_id",
                self.workspace_id,
            )
            .order(
                "display_order",
            )
            .order(
                "source_name",
            )
            .execute()
        )

        return response.data or []

    def delete_monitor_source(
        self,
        source_key: str,
    ):
        self._require_login()

        if str(self.role or "").lower() != "admin":
            raise RuntimeError(
                "เฉพาะ Admin เท่านั้นที่ลบ Central Monitor Source ได้"
            )

        key = str(
            source_key or ""
        ).strip()

        if not key:
            return []

        response = (
            self.client.table("monitor_sources")
            .delete()
            .eq(
                "workspace_id",
                self.workspace_id,
            )
            .eq(
                "source_key",
                key,
            )
            .execute()
        )

        return response.data or []

    def get_latest_main_notification_event_id(
        self,
    ):
        self._require_login()

        response = (
            self.client.table(
                "notification_events"
            )
            .select("id")
            .eq(
                "workspace_id",
                self.workspace_id,
            )
            .like(
                "source_key",
                "main_%",
            )
            .order(
                "id",
                desc=True,
            )
            .limit(1)
            .execute()
        )

        if not response.data:
            return 0

        return int(
            response.data[0].get(
                "id",
                0,
            )
            or 0
        )

    def get_main_notification_events_after(
        self,
        last_id: int,
    ):
        self._require_login()

        response = (
            self.client.table(
                "notification_events"
            )
            .select(
                "id,source_key,source,title,message,"
                "notification_type,created_at"
            )
            .eq(
                "workspace_id",
                self.workspace_id,
            )
            .like(
                "source_key",
                "main_%",
            )
            .gt(
                "id",
                int(last_id or 0),
            )
            .order(
                "id",
                desc=False,
            )
            .limit(100)
            .execute()
        )

        return response.data or []

    def disable_monitor_source(
        self,
        source_key: str,
    ):
        self._require_login()

        if str(self.role or "").lower() != "admin":
            raise RuntimeError(
                "เฉพาะ Admin เท่านั้นที่ตั้งค่า Central Monitor ได้"
            )

        response = (
            self.client.table("monitor_sources")
            .update(
                {
                    "enabled": False,
                    "updated_by": self.user.id,
                }
            )
            .eq(
                "workspace_id",
                self.workspace_id,
            )
            .eq(
                "source_key",
                str(source_key or "").strip(),
            )
            .execute()
        )

        return response.data

    def publish_notification_event(self, source: str, title: str, message: str, notification_type: str = "info"):
        self._require_login()
        payload = {
            "workspace_id": self.workspace_id,
            "source": str(source or "").strip(),
            "title": str(title or "").strip(),
            "message": str(message or ""),
            "notification_type": str(notification_type or "info"),
            "created_by": self.user.id,
        }
        response = (
            self.client.table("notification_events")
            .insert(payload)
            .execute()
        )
        return response.data[0] if response.data else None

    def update_log(self, log_id: int, title: str, description: str):
        self._require_login()
        response = (
            self.client.table("logs")
            .update(
                {
                    "title": title,
                    "description": description,
                    "updated_by": self.user.id,
                }
            )
            .eq("workspace_id", self.workspace_id)
            .eq("id", log_id)
            .execute()
        )
        return response.data[0] if response.data else None

    def delete_log(self, log_id: int):
        self._require_login()
        response = (
            self.client.table("logs")
            .delete()
            .eq("workspace_id", self.workspace_id)
            .eq("id", log_id)
            .execute()
        )
        return response.data