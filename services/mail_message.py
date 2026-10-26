"""One MIME message for every recipient, with bounded, approved local files."""
import base64
import hashlib
import mimetypes
from email.message import EmailMessage

from services.mail_policy import validate_mail_recipients
from services.summary_policy import PlanCorrection

MAX_ATTACHMENTS = 12
MAX_ATTACHMENT_BYTES = 18_000_000
ATTACHMENT_SCHEMA = {'type': 'array', 'items': {'type': 'string'}, 'minItems': 0,
                     'maxItems': MAX_ATTACHMENTS,
                     'description': 'Local file paths to attach to this one email. Include uploads marked email. Max 12 files, 18 MB total; omit for no attachments.'}


def attachment_data(registry, args, task):
    paths = args.get('attachments', [])
    if not isinstance(paths, list) or len(paths) > MAX_ATTACHMENTS:
        raise PlanCorrection('Choose at most 12 email attachments.')
    if paths and 'files' not in task.get('scopes', []):
        raise PlanCorrection('Enable Local files to attach files to email.')
    files, seen, total = [], set(), 0
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise PlanCorrection('Each email attachment must be a local file path.')
        path = registry.path(raw, task)
        if path in seen:
            raise PlanCorrection('The same email attachment was selected twice.')
        seen.add(path)
        if not path.is_file():
            raise PlanCorrection('An email attachment is missing or is a folder: ' + path.name)
        if path.stat().st_size + total > MAX_ATTACHMENT_BYTES:
            raise PlanCorrection('Email attachments must total 18 MB or less. Choose smaller files.')
        with path.open('rb') as stream:
            data = stream.read(MAX_ATTACHMENT_BYTES - total + 1)
        total += len(data)
        if total > MAX_ATTACHMENT_BYTES:
            raise PlanCorrection('Email attachments must total 18 MB or less.')
        files.append(({'path': str(path), 'name': path.name, 'bytes': len(data),
                       'sha256': hashlib.sha256(data).hexdigest()}, data))
    required = {str(registry.path(a['path'], task)) for a in task.get('attachments', []) if a.get('role') == 'email'}
    if required - {item['path'] for item, _ in files}:
        raise PlanCorrection('Include every upload marked Email attachment in attachments before proposing this email.')
    return files


def validate_attachments(registry, action, task):
    files = attachment_data(registry, action['arguments'], task)
    manifest = [item for item, _ in files]
    if action.get('id') and manifest != action.get('mail_files', []):
        raise PlanCorrection('Email attachments changed after the preview. Prepare a new email for approval.')
    action['arguments'].update({'attachments': [item['path'] for item in manifest]} if manifest else {})
    action['mail_files'] = manifest


def encode_message(registry, args, task):
    recipients = validate_mail_recipients(task, {'arguments': args})
    files = attachment_data(registry, args, task)
    pending = task.get('pending') or {}
    if pending.get('id') and [item for item, _ in files] != pending.get('mail_files', []):
        raise PlanCorrection('Email attachments changed after approval. Review them again before sending.')
    mail = EmailMessage()
    mail['To'], mail['Subject'] = ', '.join(recipients), args['subject']
    mail.set_content(args['body'])
    for item, data in files:
        mime, encoding = mimetypes.guess_type(item['name'])
        maintype, subtype = (mime if mime and not encoding else 'application/octet-stream').split('/', 1)
        mail.add_attachment(data, maintype=maintype, subtype=subtype, filename=item['name'])
    return base64.urlsafe_b64encode(mail.as_bytes()).decode()
