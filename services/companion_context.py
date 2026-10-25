"""Read-only app awareness for chat; no account content or capability execution."""


def application_context(catalog=None, google_status=None):
    # Select fields explicitly: never serialize config, credentials, task history,
    # tool schemas/functions, account contents or the whole runtime snapshot.
    capabilities = None if catalog is None else [
        {key: tool[key] for key in ('name', 'description', 'scope', 'writes')}
        for tool in catalog
    ]
    scopes = None if capabilities is None else {tool['scope'] for tool in capabilities}
    integrations = {}
    for service in ('gmail', 'drive', 'calendar', 'meet', 'maps'):
        supported = None if scopes is None else service in scopes
        if supported is False:
            state = 'unsupported'
        elif google_status is None:
            state = 'unknown'
        elif service == 'maps':
            state = 'key_configured' if google_status.get('maps') else 'not_configured'
        elif not google_status.get('connected'):
            state = 'not_connected'
        elif service in google_status.get('services', []):
            state = 'connected'
        else:
            state = 'not_authorized'
        integrations[service] = {'supported': supported, 'state': state}

    return {
        'name': 'IntentOS',
        'purpose': ('A local AI workspace that turns natural-language requests into tracked intents. '
                    'Its planner uses the registered capabilities below to carry out tasks with '
                    'scoped access, permission checks, progress, results and execution history.'),
        'chat': ('Orbii answers questions and discusses ideas or supplied completed results. '
                 'Chat does not create intents, access account contents or execute capabilities. '
                 'Make this an intent / Use as intent copies a message into an editable workspace '
                 'draft; Start intent submits it. Necessary access and action approvals happen '
                 'in that workflow.'),
        'other_features': ['Processes and history for tracking intents',
                           'Connections for service setup and checks',
                           'OS Lab for educational process scheduling and memory simulations',
                           'Text input and output by default; optional microphone and spoken replies'],
        'integration_transport': 'Built-in Google API integrations using OAuth; Maps uses a separate API key. These are not MCP server connections.',
        'capabilities': capabilities,
        'integrations': integrations,
        'google_oauth_configured': None if google_status is None else bool(google_status.get('configured')),
        'connection_evidence': ('Current locally recorded authorization, refreshed for this chat request. '
                                'Connected means a stored token and the required service scopes exist; '
                                'it does not verify that credentials are still valid or APIs are enabled. '
                                'A configured OAuth client or Maps key alone does not prove live access. '
                                'No service health check or account data retrieval was performed. '
                                'Unknown means unavailable evidence, not disconnected.'),
    }
