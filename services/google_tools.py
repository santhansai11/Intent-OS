"""Google account tools; all writes run through the runtime's exact-action approval."""
import base64
import json
import mimetypes
import os
import re
import uuid
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode, quote

from services.connections import request_json

GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me/'
DRIVE = 'https://www.googleapis.com/drive/v3/files/'
CALENDAR = 'https://www.googleapis.com/calendar/v3/calendars/primary/events/'


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', value):
        raise ValueError('Use the ID returned by a previous search')
    return quote(value, safe='')


class GoogleTools:
    def __init__(self, registry):
        self.registry, self.google = registry, registry.google

    def register(self):
        from services.capabilities import string
        def add(name, description, scope, writes, fields, required, handler):
            self.registry.add(name, description, scope, writes,
                              {k: string(v) for k, v in fields.items()}, required, handler)
        add('gmail_search', 'Search Gmail using Gmail search syntax. Returns message IDs and a next page token.', 'gmail', False,
            {'query': 'Gmail query, e.g. from:someone after:2026/09/01', 'page_token': 'Next page token from previous result'}, ['query'], self.gmail_search)
        add('gmail_read', 'Read a Gmail message, headers and plain text. Attachments are listed, not downloaded.', 'gmail', False,
            {'message_id': 'Message ID from Gmail search'}, ['message_id'], self.gmail_read)
        add('gmail_draft', 'Create a Gmail draft for review; does not send it.', 'gmail', True,
            {'to': 'One email address', 'subject': 'Subject', 'body': 'Plain text body'}, ['to', 'subject', 'body'], self.gmail_draft)
        add('drive_read', 'Read UTF-8 text from Drive or export a Google Doc as text. Use drive_download for PDF/Office files.', 'drive', False,
            {'file_id': 'Drive file ID'}, ['file_id'], self.drive_read)
        add('drive_download', 'Download a Drive file into a NEW local file, up to 10 MB. Google Docs, Sheets and Slides export as PDF by default.', 'drive', True,
            {'file_id': 'Drive file ID', 'destination': 'New absolute local file path', 'export_mime': 'Optional supported Google export MIME type'}, ['file_id', 'destination'], self.drive_download)
        add('drive_upload', 'Upload a local file (up to 5 MB) to a NEW Drive file. Never replaces a remote file.', 'drive', True,
            {'source': 'Granted local file path', 'parent_id': 'Optional Drive folder ID; must be accessible to this app'}, ['source'], self.drive_upload)
        add('drive_create_folder', 'Create a Google Drive folder. Search first to avoid duplicates; use the returned folder id as parent_id for each drive_upload. Reuse the successful checkpoint rather than creating it again.', 'drive', True,
            {'name': 'Folder name', 'parent_id': 'Optional parent folder ID; omit to create in My Drive'}, ['name'], self.drive_create_folder)
        add('calendar_get', 'Read one Calendar event, including its Meet link and conference generation status. Do not claim a pending conference is ready.', 'calendar', False,
            {'event_id': 'Event ID from calendar_create or calendar_list'}, ['event_id'], self.calendar_get)
        add('calendar_update', 'Update title, time, location and description of an existing Calendar event. Requires approval.', 'calendar', True,
            {'event_id': 'Event ID from calendar_list', 'title': 'New title', 'start': 'RFC3339 start with timezone', 'end': 'RFC3339 end with timezone', 'location': 'Location', 'description': 'Description'},
            ['event_id', 'title', 'start', 'end', 'location', 'description'], self.calendar_update)
        add('calendar_delete', 'Delete one Calendar event by ID. Requires approval.', 'calendar', True,
            {'event_id': 'Event ID from calendar_list'}, ['event_id'], self.calendar_delete)
        add('maps_places', 'Search Google Places by text, returning addresses, locations and Google Maps links. Requires Places API (New).', 'maps', False,
            {'query': 'Place or business and city/area', 'page_token': 'Optional next page token'}, ['query'], self.maps_places)
        add('maps_place_details', 'Fetch address, phone, website, hours and rating for a Google place ID.', 'maps', False,
            {'place_id': 'Place ID returned by maps_places'}, ['place_id'], self.maps_place_details)

    def gmail_search(self, args, task):
        return self.google.call('gmail', GMAIL + 'messages?' + urlencode({
            'q': args['query'], 'maxResults': 50, **({'pageToken': args['page_token']} if args.get('page_token') else {})}))

    def gmail_read(self, args, task):
        data = self.google.call('gmail', GMAIL + 'messages/' + identifier(args['message_id']) + '?format=full')
        text, attachments = [], []
        def walk(part):
            body = part.get('body', {})
            if part.get('filename'):
                attachments.append({'name': part['filename'], 'bytes': body.get('size'), 'id': body.get('attachmentId')})
            elif part.get('mimeType') == 'text/plain' and body.get('data'):
                raw = body['data']
                text.append(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)).decode('utf-8', errors='replace'))
            for child in part.get('parts', []):
                walk(child)
        walk(data.get('payload', {}))
        content = '\n'.join(text) or data.get('snippet', '')
        return {'id': data['id'], 'thread_id': data.get('threadId'), 'headers': [h for h in data.get('payload', {}).get('headers', []) if h['name'].lower() in ('from', 'to', 'subject', 'date', 'cc')],
                'content': content[:16000], 'truncated': len(content) > 16000, 'attachments': attachments}

    def gmail_draft(self, args, task):
        if not re.fullmatch(r'[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+', args['to']):
            raise ValueError('Supply one complete recipient email address')
        mail = EmailMessage()
        mail['To'], mail['Subject'] = args['to'], args['subject']
        mail.set_content(args['body'])
        return self.google.call('gmail', GMAIL + 'drafts', {'message': {'raw': base64.urlsafe_b64encode(mail.as_bytes()).decode()}})

    def drive_content(self, args, text=False):
        url = DRIVE + identifier(args['file_id'])
        metadata = self.google.call('drive', url + '?fields=id,name,mimeType,size,capabilities')
        if metadata.get('capabilities', {}).get('canDownload') is False:
            raise ValueError('The owner has disabled downloading this file')
        if int(metadata.get('size', 0)) > 10_000_000:
            raise ValueError('Choose a Drive file smaller than 10 MB')
        mime = metadata.get('mimeType', '')
        if mime.startswith('application/vnd.google-apps.'):
            export = 'text/plain' if text else args.get('export_mime', 'application/pdf')
            if mime not in ('application/vnd.google-apps.document', 'application/vnd.google-apps.spreadsheet', 'application/vnd.google-apps.presentation'):
                raise ValueError('This Google file type cannot be exported here')
            if text and mime != 'application/vnd.google-apps.document':
                raise ValueError('Download Sheets or Slides as PDF, then use files_read')
            if export not in ('text/plain', 'application/pdf', 'text/csv', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'):
                raise ValueError('Unsupported export MIME type')
            url += '/export?' + urlencode({'mimeType': export})
            mime = export
        else:
            if text and not (mime.startswith('text/') or mime in ('application/json', 'application/xml')):
                raise ValueError('Download this file, then use files_read for PDF or Office text')
            url += '?alt=media'
        raw = self.google.call('drive', url, response_bytes=True)
        return metadata, raw, mime

    def drive_read(self, args, task):
        metadata, raw, _ = self.drive_content(args, text=True)
        content = raw.decode('utf-8', errors='replace')
        return {'id': metadata['id'], 'name': metadata['name'], 'content': content[:16000], 'truncated': len(content) > 16000}

    def drive_download(self, args, task):
        path = self.registry.path(args['destination'], task)
        if path.exists():
            raise ValueError('Choose a new destination; existing files are preserved')
        metadata, raw, mime = self.drive_content(args)
        extensions = {'application/pdf': '.pdf', 'text/plain': '.txt', 'text/csv': '.csv', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx'}
        if metadata.get('mimeType', '').startswith('application/vnd.google-apps.') and path.suffix.lower() != extensions.get(mime):
            raise ValueError('Destination extension must match the exported format')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as file:
            file.write(raw)
        return {'artifact': str(path), 'bytes': len(raw), 'source_id': metadata['id'], 'status': 'downloaded'}

    def drive_create_folder(self, args, task):
        name = args['name'].strip()
        if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise ValueError('Use a folder name of 1–200 characters without control characters')
        metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if args.get('parent_id'):
            metadata['parents'] = [identifier(args['parent_id'])]
        return self.google.call('drive', DRIVE.rstrip('/') + '?fields=id,name,mimeType,webViewLink', metadata)

    def drive_upload(self, args, task):
        path = self.registry.path(args['source'], task)
        if not path.is_file() or path.stat().st_size > 5_000_000:
            raise ValueError('Choose a local file smaller than 5 MB')
        metadata = {'name': path.name}
        if args.get('parent_id'):
            metadata['parents'] = [identifier(args['parent_id'])]
        boundary = 'intentos_' + uuid.uuid4().hex
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode() + json.dumps(metadata).encode() +
                f'\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode())
        return self.google.call('drive', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink', body,
                                content_type='multipart/related; boundary=' + boundary)

    def calendar_get(self, args, task):
        return self.google.call('calendar', CALENDAR + identifier(args['event_id']))

    def calendar_update(self, args, task):
        self.registry.dates(args)
        return self.google.call('calendar', CALENDAR + identifier(args['event_id']), {
            'summary': args['title'], 'description': args['description'], 'location': args['location'],
            'start': {'dateTime': args['start']}, 'end': {'dateTime': args['end']}}, method='PATCH')

    def calendar_delete(self, args, task):
        self.google.call('calendar', CALENDAR + identifier(args['event_id']), method='DELETE')
        return {'status': 'deleted', 'event_id': args['event_id']}

    def maps_headers(self, fields):
        from services.maps_keys import MapsKeys
        key = MapsKeys(self.registry.config).get()
        if not key:
            raise ValueError('Save a Google Maps key in Connections and enable Places API (New) in Google Cloud')
        return {'X-Goog-Api-Key': key, 'X-Goog-FieldMask': fields}

    def maps_places(self, args, task):
        return request_json('https://places.googleapis.com/v1/places:searchText',
            {'textQuery': args['query'], 'pageSize': 20, **({'pageToken': args['page_token']} if args.get('page_token') else {})},
            self.maps_headers('places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri,nextPageToken'))

    def maps_place_details(self, args, task):
        return request_json('https://places.googleapis.com/v1/places/' + identifier(args['place_id']), headers=self.maps_headers(
            'id,displayName,formattedAddress,location,googleMapsUri,nationalPhoneNumber,websiteUri,regularOpeningHours,rating,userRatingCount'))
