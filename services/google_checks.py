"""Explicit connection probes. Do not create events, spaces, messages or files."""
from services.connections import ConnectionError


def check_service(config, google, registry, service):
    endpoints = {
        'calendar': 'https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults=1&fields=items(id)',
        'drive': 'https://www.googleapis.com/drive/v3/files?pageSize=1&fields=files(id)',
        'gmail': 'https://gmail.googleapis.com/gmail/v1/users/me/profile',
        'meet': 'https://meet.googleapis.com/v2/conferenceRecords?pageSize=1',
    }
    if service in endpoints:
        google.call(service, endpoints[service])
        return {'service': service, 'ok': True, 'message': 'API access verified'}
    if service == 'maps':
        from services.maps_keys import MapsKeys
        from services.google_tools import GoogleTools
        if not MapsKeys(config).get():
            raise ConnectionError('Save your Google Maps API key in Connections first.')
        # Public example addresses, not the user's location. Test both enabled APIs.
        checks = {}
        probes = {'places': lambda: GoogleTools(registry).maps_places({'query': 'India Gate, New Delhi'}, {}),
                  'routes': lambda: registry.maps_route({'origin': 'India Gate, New Delhi', 'destination': 'New Delhi Railway Station', 'mode': 'DRIVE'}, {})}
        for name, probe in probes.items():
            try:
                probe()
                checks[name] = {'ok': True}
            except (ConnectionError, ValueError) as exc:
                checks[name] = {'ok': False, 'error': str(exc)}
        return {'service': service, 'ok': all(c['ok'] for c in checks.values()), 'checks': checks}
    raise ValueError('Choose calendar, drive, gmail, meet or maps')
