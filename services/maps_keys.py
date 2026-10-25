"""Maps API key storage, separate from Google OAuth and planning providers."""
from services.gemini import AIKeys


class MapsKeys(AIKeys):
    providers = {'maps': ('Google Maps', 'GOOGLE_MAPS_API_KEY')}

    def __init__(self, config):
        super().__init__(config, 'maps')
