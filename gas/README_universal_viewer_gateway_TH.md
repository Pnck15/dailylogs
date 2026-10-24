# Central Viewer Gateway — Google Sheets / Excel .xlsx monitoring

One **standalone Google Apps Script Web App** reads many permitted workbooks.
Supabase keeps source configuration, runs a shared monitor worker and
distributes change notifications to the existing DailyLog and DailyLogNotify.

**Access restriction:** The account deploying the GAS must have Viewer/Reader
permissions to each source file. For Excel, download access is required.
No URL or code bypasses Google Drive permissions, private sharing or
download restrictions. This gateway does NOT create Google OAuth access for
Supabase on its own.

## Initial setup (once per Google account)
1. Create a new **standalone** Apps Script at https://script.google.com/home/projects/create
2. Copy the entire [universal_viewer_gateway.gs](universal_viewer_gateway.gs)
   into Code.gs. It MUST be standalone, not bound to anyone else's Excel.
3. Run `setupViewerGateway()`, authorize read access to SpreadsheetApp, DriveApp
   and storage of the snapshot in this Google account's private Drive.
4. Deploy → New deployment → Web app → Execute as **Me**.
   If selecting **Anyone**, the long unpredictable token in the private URL
   is essential. Do NOT share this URL or commit its secret to GitHub.
5. Run `showViewerGatewayUrl()`, then copy the complete Web App URL with
   `?token=...` from the Execution log.
6. Open DailyLog.exe **v1.2.18+** → **Main Notification Sources**.
   Paste the endpoint in **Viewer Gateway**, click **Save Gateway** once.
   This configuration is kept in the workspace in Supabase and is not
   published as a DailyLogNotify notification choice.

## Add as many monitored spreadsheets as the permitted account can read
1. In **Main Notification Sources**, choose **+ New** or your old Red Plate
   source; put a unique descriptive **Source Name**.
2. Paste the *ordinary* native Google Sheets URL containing an optional gid.
   Do not paste the private Gateway endpoint in the Source URL.
3. **Excel .xlsx with multiple tabs:** enter the EXACT worksheet name in
   the **Tab name for Excel** field. The external Google Sheets gid used by
   Google's Office-mode Excel viewer is not guaranteed to match the XLSX
   worksheet sheetId. Use this field to avoid monitoring the wrong tab.
4. Click **Test Connection**. It will actually try a read through the
   gateway (no snapshot changes from the test), then click **Save**.
5. The Central Worker polls each saved source through the same Gateway;
   the GAS keeps a **separate private baseline and change retry queue**
   for each file + gid + tab. The first scan creates a baseline and
   DOES NOT notify historical edits. Later scans compare values.
6. Notifications include add/edit/delete and column-header modifications.
   The source Excel/Google Sheet is NEVER written to by the Gateway.
   The existing DailyLogNotify source selection continues working.

## Current Red Plate
Existing Red Plate's GAS URL is missing `?token=...` and returns
`Missing or invalid monitor token.` Simply changing Python EXE cannot
unlock the deployment.

After the new Gateway is deployed, edit the EXISTING Red Plate Source:
- **Source URL** = original Google Sheets viewer URL for file
  `1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb`
- **Excel Tab Name** = `04-红牌ชีตnew`
- Keep Enabled and Show in DailyLogNotify checked.
- Test Connection; Save. Do not duplicate Red Plate source.

## Limitations
- For a Viewer link whose account lacks permission, Gateway returns an
  authorization error. Public URLs may work only if publicly readable.
- The Gateway's standard safety bounds are 6500 data rows, 260 columns,
  3000 pending events and a 9.5 MB private JSON snapshot. Large Excel
  (e.g. ~28 MB source) can exceed Apps Script runtime/memory/ZIP limits.
  The first scan may fail under those limits; DO NOT report success until
  `monitor_state.last_success_at` is populated and real change tests pass.
- This is periodic snapshot diff, NOT Google's live edit event feed:
  changes made and reverted between scans are not detectable.
  It cannot reliably identify **which editor** changed a cell.
- The bearer token authorizes access to workbooks visible to the deploying
  account. Keep token protected as a credential. A leaked token must be rotated.
- Source scanning respects the central scheduled worker cadence; errors remain
  visible in `monitor_state.last_error`, and are not reported as success.
