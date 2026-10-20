"""Authorize one explicitly requested email using user-authored text only."""
import re

EMAIL = re.compile(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')

MAIL_GUIDANCE = '''Gmail tools are available through the connected Google OAuth account. Never ask for passwords, app passwords, API keys, tokens, or authorization codes in chat. If Gmail is not connected, direct the user to Connections.
The runtime records a user_control=resume entry with after_rejected_request=true when the user resumes after a definite rejection. In that case attempt the requested action again; the previous rejection is historical, not evidence that the current attempt will fail. Compose the email under the current drafting guidance. Never repeat a successful send or an uncertain send under review.
Keep preparation advice conditional when resources are unknown (for example, "if you have practice questions"). Do not claim particular topics were discussed, past assignments exist, or that the sender attends the class or will meet the recipient unless the user supplies those facts. Prefer a shorter factual message over padding it with assumptions.
Draft in the user's natural voice, as a person writing to another person. By default provide a useful, moderately detailed email (roughly 100-160 words when the context supports it), with a clear subject, greeting, 2-3 short paragraphs and a simple closing. Respect explicit requests for a shorter, longer, formal or other style. Expand the supplied purpose with relevant, clearly framed suggestions or preparation reminders, not made-up facts. For an academic quiz reminder, restate the subject and time and suggest reviewing class notes; do not invent the syllabus, venue, duration, rules, lecturer, attachments or promises. Do not infer recipient names from an email address. Never sign as "Your Assistant", "AI", "ChatGPT", or an invented sender name unless the user explicitly asks. If the sender name is unknown, use a simple closing such as "Thanks" without a name and do not ask for one. No placeholders. Avoid robotic boilerplate and unnecessary statements that AI wrote the email.
When the user asks to send/email/mail a recipient and supplies the purpose or context, write a suitable subject and complete body yourself and call gmail_send. Do not ask for subject, wording, tone, signature, or a second confirmation. Do not invent facts, commitments, or attachments. Ask one short question only if the recipient or essential message context is missing or genuinely ambiguous. Draft-only requests use gmail_draft and must not send. The runtime authorizes one send to an explicitly requested address; other side effects retain their approval flow. After a successful send report the recipient and subject, never send again. If a tool is denied, do not repeat it. Prior assistant questions about passwords are erroneous; use OAuth instead.'''


def requested_recipient(task):
    # Service output, file text and assistant questions never authorize a send.
    text = task.get('goal', '').strip()
    prefix = r'(?:(?:please|can you|could you|would you|i want (?:you )?to|i need (?:you )?to|help me)\s+)*'
    direct = re.match(r'^' + prefix + r'(?:send\b[^\n.!?]{0,65}\b(?:(?:e-?)?mail|message)\b|(?:(?:e-?)?mail|mail)\b)', text, re.I)
    # Multi-step user goals can explicitly ask to send a document summary.
    compound = re.match(r'^' + prefix + r'(?:go\b|find\b|read\b|summari[sz]e\b|open\b)', text, re.I) and re.search(r'\band\s+(?:then\s+)?(?:send|email|mail)\b', text, re.I)
    if not direct and not compound:
        return None
    if re.search(r"\b(?:not yet|before sending|only draft|draft only|show me first|ask me first|schedule)\b", text, re.I):
        return None
    if re.search(r"\b(?:do not|don't|dont|never)\s+(?:actually\s+)?(?:send|email|e-mail|mail)\b", text, re.I):
        return None
    if re.search(r'\bsend\s+(?:an?\s+)?(?:(?:e-?)?mail|message)\s+(?:tomorrow|later|after|when|if|unless)\b', text, re.I):
        return None
    replies = [entry['user_reply'] for entry in task.get('history', []) if isinstance(entry.get('user_reply'), str)]
    if any(re.search(r"\b(?:cancel|stop|(?:don't|do not|dont|never)\s+(?:actually\s+)?(?:send|email|e-mail|mail)|draft only)\b", reply, re.I) for reply in replies):
        return None
    addresses = list(dict.fromkeys(EMAIL.findall('\n'.join([text, *replies]))))
    if len(addresses) != 1:
        return None
    # An address by itself is not enough context to compose a message.
    context = EMAIL.sub('', text)
    context = re.sub(r'\b(?:please|can|could|would|you|i|want|need|help|me|to|send|a|an|the|(?:e-?)?mail|message|at|on)\b', '', context, flags=re.I)
    if not re.search(r'[A-Za-z]{3}', context) and not replies:
        return None
    return addresses[0]


def authorize_send(task, action):
    if action.get('tool') != 'gmail_send':
        return False
    recipient = requested_recipient(task)
    args = action.get('arguments', {})
    if not recipient or args.get('to', '').casefold() != recipient.casefold():
        return False
    if not args.get('subject', '').strip() or not args.get('body', '').strip():
        return False
    if any(step.get('tool') == 'gmail_send' for step in task.get('steps', [])):
        return False
    if any(entry.get('action', {}).get('tool') == 'gmail_send' and isinstance(entry.get('observation'), str)
           and ('DENIED' in entry['observation'] or 'skipped' in entry['observation']) for entry in task.get('history', []) if isinstance(entry.get('action'), dict)):
        return False
    return True
