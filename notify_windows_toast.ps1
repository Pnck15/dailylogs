# DailyLogNotify native Windows 10/11 toast (Windows PowerShell 5.1).
# All notifications are sent locally; no Supabase/history writes.
param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [string]$AppId = "MiniDailyLog.DailyLogNotify",
    [string]$TitleBase64 = "",
    [string]$BodyBase64 = "",
    [switch]$RegisterOnly,
    [switch]$DiagnoseOnly,
    [switch]$RepairShortcut
)
$ErrorActionPreference = "Stop"
try {
    if (-not [System.IO.File]::Exists($ExePath)) {
        throw "Notification executable does not exist: $ExePath"
    }
    if (-not $env:APPDATA -or -not $env:LOCALAPPDATA) {
        throw "Interactive Windows user profile is required."
    }
    $programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    [System.IO.Directory]::CreateDirectory($programs) | Out-Null
    $linkPath = Join-Path $programs "DailyLogNotify.lnk"
    $dataRoot = Join-Path $env:LOCALAPPDATA "MiniDailyLog\DailyLogNotify"
    [System.IO.Directory]::CreateDirectory($dataRoot) | Out-Null
    $registrationStamp = Join-Path $dataRoot "toast_registration.txt"
    $fingerprint = [string]::Join([Environment]::NewLine, @($ExePath, $AppId))

    # Unpackaged Windows Toasts need a Start-menu .lnk whose
    # System.AppUserModel.ID matches CreateToastNotifier(appId).
    # Never alter the user's notification permission. A repair only rewrites
    # OUR owned Start-menu shortcut/AUMID, not Windows notification settings.
    if ($RepairShortcut -or
        -not [System.IO.File]::Exists($linkPath) -or
        -not [System.IO.File]::Exists($registrationStamp) -or
        [System.IO.File]::ReadAllText($registrationStamp) -ne $fingerprint) {
        $source = @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace MiniDailyLogWindowsToast {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLink { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown),
     Guid("000214F9-0000-0000-C000-000000000046")]
    interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder path, int max, out IntPtr data, int flags);
        void GetIDList(out IntPtr id);
        void SetIDList(IntPtr id);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder desc, int max);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder directory, int max);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder arguments, int max);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetHotkey(out short key);
        void SetHotkey(short key);
        void GetShowCmd(out int cmd);
        void SetShowCmd(int cmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder icon, int max, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, int reserved);
        void Resolve(IntPtr hwnd, int flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    [StructLayout(LayoutKind.Sequential, Pack=4)]
    struct PropertyKey {
        public Guid fmtid;
        public uint pid;
    }

    [StructLayout(LayoutKind.Explicit)]
    struct PropVariant {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr value;
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown),
     Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    interface IPropertyStore {
        void GetCount(out uint count);
        void GetAt(uint i, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    public static class Shortcut {
        public static void Create(string path, string executable, string aumid) {
            object link = new ShellLink();
            try {
                var shortcut = (IShellLinkW)link;
                shortcut.SetPath(executable);
                shortcut.SetWorkingDirectory(
                    System.IO.Path.GetDirectoryName(executable));
                shortcut.SetDescription("DailyLogNotify - Central Notifications");
                shortcut.SetIconLocation(executable, 0);

                var key = new PropertyKey {
                    fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
                    pid = 5
                };
                var value = new PropVariant {
                    vt = 31,
                    value = Marshal.StringToCoTaskMemUni(aumid)
                };
                try {
                    var store = (IPropertyStore)link;
                    store.SetValue(ref key, ref value);
                    store.Commit();
                } finally {
                    Marshal.FreeCoTaskMem(value.value);
                }
                ((IPersistFile)link).Save(path, true);
            } finally {
                if (Marshal.IsComObject(link)) Marshal.ReleaseComObject(link);
            }
        }
    }
}
'@
        Add-Type -TypeDefinition $source -Language CSharp -ErrorAction Stop | Out-Null
        [MiniDailyLogWindowsToast.Shortcut]::Create($linkPath, $ExePath, $AppId)
        [System.IO.File]::WriteAllText($registrationStamp, $fingerprint)
    }

    if ($RegisterOnly) {
        Write-Output "REGISTERED"
        exit 0
    }

    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
    [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId)
    $setting = [string]$notifier.Setting
    # Exact setting identifies the block level; Do Not Disturb alone does
    # NOT determine whether this WinRT app is allowed to send toast.
    if ($DiagnoseOnly -or $RepairShortcut) {
        if ($RepairShortcut) { Write-Output "SHORTCUT_REPAIRED" }
        Write-Output ("TOAST_SETTING:" + $setting)
        exit 0
    }
    if ($setting -ne "Enabled") {
        switch ($setting) {
            "DisabledForApplication" {
                throw "TOAST_SETTING:DisabledForApplication; Enable DailyLogNotify under Windows Settings > System > Notifications > Notifications from apps."
            }
            "DisabledForUser" {
                throw "TOAST_SETTING:DisabledForUser; Turn on the master Notifications toggle in Windows Settings > System > Notifications."
            }
            "DisabledByGroupPolicy" {
                throw "TOAST_SETTING:DisabledByGroupPolicy; Notifications are blocked by an administrator's Windows Group Policy."
            }
            "DisabledByManifest" {
                throw "TOAST_SETTING:DisabledByManifest; Windows app identity could not use native notifications. Repair the DailyLogNotify Start-menu shortcut."
            }
            default {
                throw ("TOAST_SETTING:" + $setting + "; Windows blocked this app's notifications.")
            }
        }
    }

    $title = [System.Text.Encoding]::UTF8.GetString(
        [System.Convert]::FromBase64String($TitleBase64))
    $body = [System.Text.Encoding]::UTF8.GetString(
        [System.Convert]::FromBase64String($BodyBase64))
    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $xml.GetElementsByTagName("text")
    [void]$textNodes.Item(0).AppendChild($xml.CreateTextNode($title))
    [void]$textNodes.Item(1).AppendChild($xml.CreateTextNode($body))
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $notifier.Show($toast)
    Write-Output "TOAST_SUBMITTED"
    exit 0
} catch {
    [Console]::Error.WriteLine("DAILYLOG_TOAST_ERROR: " + $_.Exception.Message)
    exit 1
}
