# Connect Gmail, Drive, Calendar and Google Maps

These integrations use Google's official APIs. The [public-apis directory](https://github.com/public-apis/public-apis) is a discovery list; it does not issue Google credentials or grant access to your account.

## 1. Install the app dependencies

Use the same Python that starts the server. From `D:\Intent OS`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend run build
.\.venv\Scripts\python.exe run_intentos.py --server
```

Gemini is separate from Google account sign-in. In Connections, save your Gemini key, select an available text model, and use **Test & use model**. Saving a key activates Gemini for new goals; the key in Windows Credential Manager takes precedence over `GEMINI_API_KEY`. Existing goals retain their original provider.

## 2. Create a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create/select your project.
2. Enable **Gmail API**, **Google Drive API**, and **Google Calendar API** under APIs & Services → Library.
3. Configure Google Auth Platform: app name, contact email, audience. For a personal external app in Testing mode, add your Google email as a test user.
4. Create an OAuth client of type **Web application**.
5. Add this exact authorized redirect URI: `http://127.0.0.1:8765/api/google/callback`. If you use another port, change both the Google URI and `GOOGLE_REDIRECT_URI`.
6. Copy `.env.example` to `.env` **only if `.env` does not already exist**. Otherwise edit the existing file. Set these values locally; do not paste secrets into chat:

```dotenv
GOOGLE_CLIENT_ID=your-web-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8765/api/google/callback
```

7. Restart IntentOS. Open Connections → Google workspace, select Gmail, Drive and Calendar, and click **Connect selected services**. Review Google's consent screen and sign in yourself.
8. When submitting a goal, enable its needed services under **More options**. Drive upload/download also needs **Local files** and the relevant source/output folder.

Setup reference: [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server).

## 3. Enable Google Maps

1. Link billing to your Google Cloud project and set budgets/alerts and API quotas appropriate for your usage.
2. Enable **Routes API** and **Places API (New)**.
3. Create a separate API key. Restrict it to these two APIs and appropriate server/IP restrictions for your setup (browser referrer restrictions are unsuitable for this Python backend).
4. Set `GOOGLE_MAPS_API_KEY` in `.env`, then restart IntentOS. Google OAuth alone does not enable Maps.

Google documents [Compute Routes](https://developers.google.com/maps/documentation/routes/compute_route_directions) and [Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search). Places details such as phone, hours and ratings can incur different charges; check your project's current pricing and quotas.

## Available operations and limits

| Service | Operations | Boundaries |
| --- | --- | --- |
| Gmail | Search with Gmail query syntax and pagination; read headers/plain text; list attachment metadata; create drafts; send plain text mail | One recipient for draft/send; message text limited to 16,000 characters; no attachment downloads, HTML editor or mailbox deletion |
| Drive | Filename search and pagination; read UTF-8 text / Google Docs; download files; export Docs/Sheets/Slides; upload a new file | Downloads up to 10 MB, uploads up to 5 MB; no overwrites; PDF default for Google exports; read PDF/Office text after download with `files_read` |
| Calendar | List events with pagination; create, update and delete an event | Primary calendar; timezone-aware timestamps; create does not invite attendees; edit/delete identifies an event returned by list |
| Maps | Search places; place address, phone, website, opening hours and ratings; driving/walking/bicycle/transit directions | Requires enabled APIs, billing and valid key; no background location tracking |

An explicit request such as “Send an email to person@example.com about our meeting tomorrow at 10 AM” generates the subject/body and authorizes one send to that address. No Gmail password or separate Gmail read checkbox is needed. Draft-only requests never auto-send. Ambiguous recipients, other account writes, drafts, uploads, downloads and event changes appear as exact actions for approval. The local auto-output checkbox does not approve Google actions. New local downloads preserve existing files. Tokens remain in the OS credential store.

## Permissions

| Service | Requested scopes |
| --- | --- |
| Gmail | `gmail.readonly`, `gmail.compose`, `gmail.send` |
| Drive | `drive.readonly`, `drive.file` |
| Calendar | `calendar.events` |

Drive read access covers existing account files; `drive.file` permits new uploads and access to app-authorized files. Uploading to an existing folder may require that folder to be authorized for this app; uploading to the account root works without a parent ID. The app does not request unrestricted Drive modification access. If you connected before these features, reconnect to grant the new scopes. Testing-mode tokens can expire; reconnect when prompted. Publishing broadly can require Google's verification for sensitive/restricted scopes.

## Try it

- “Search Gmail for messages from professor@example.com after September 1, 2026 and summarize the latest one.”
- “Create a draft to professor@example.com with this project update: …”
- “Find my AWS notes in Drive and download the selected document as a PDF into my output folder.”
- “Upload this granted local report to a new Drive file.”
- “List tomorrow's calendar events, then move the project review to 4 PM.”
- “Find cafes near Chennai Central and show a driving route to the one I choose.”

The regression tests mock account responses; they do not establish access to your Google account. Complete setup and exercise read operations before approving real external writes.


## Google Meet

Enable **Google Meet API** in the same Google Cloud project as your OAuth client. In IntentOS Connections, select Meet together with your existing Gmail, Drive and Calendar services, click **Connect selected services**, and grant access on Google's consent screen. Enabling an API alone does not update an existing token's permissions.

The Meet integration requests `meetings.space.created` and `meetings.space.readonly`. It can create reusable meeting links, read spaces, end an app-created active conference, list accessible conference records and participants, and read existing recording/transcript metadata and transcript entries. Recordings and transcripts must already exist; access depends on your account, the host and Google permissions. This integration does not join calls, record audio/video or automatically start recording/transcription. Calendar scheduling is separate: `calendar_create` accepts `meet_link="true"`, and `calendar_get` checks asynchronous link generation. Creating an event does not invite attendees.

Use **Check Meet** to test read access without creating a meeting. Examples: “Create a Google Meet link”; “Schedule a meeting tomorrow at 10 AM for 30 minutes with a Meet link”; “List my recent Meet conferences.” Creation and ending meetings use the existing exact-action approval flow.

Sources: [Meet authorization](https://developers.google.com/workspace/meet/api/guides/authenticate-authorize), [Meet REST reference](https://developers.google.com/workspace/meet/api/reference/rest/v2).

## Maps setup in the app

1. Open your Google Cloud project and enable billing for Maps usage.
2. Enable **Routes API** and **Places API (New)**.
3. In **APIs & Services → Credentials → Create credentials → API key**, create a key. Restrict its API access to Routes and Places API (New). Calls originate from the Python backend; HTTP referrer restrictions are for browser applications, not this backend. If you have a stable public outbound IP, use the matching server IP restriction.
4. In IntentOS **Connections → Google Maps**, paste the key into the password field and click **Save Maps key**. The key is kept in Windows Credential Manager, separately from AI keys and Google OAuth. A saved key takes precedence over `GOOGLE_MAPS_API_KEY` in `.env`.
5. Click **Test Maps APIs**. It tests both APIs using public New Delhi landmarks and reports separate results. It does not use your location. These requests use your project's Maps quota/billing.

Source: [Routes API keys](https://developers.google.com/maps/documentation/routes/get-api-key), [Places API keys](https://developers.google.com/maps/documentation/places/web-service/get-api-key).

Connection checks are available for Calendar, Drive, Gmail, Meet and Maps. A saved Google connection means tokens exist; use the checks to verify API access. Checks do not create events, meeting spaces, messages or Drive files.
