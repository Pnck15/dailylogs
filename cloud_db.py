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