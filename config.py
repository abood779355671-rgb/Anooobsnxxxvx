from os import getenv
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.API_ID = int(getenv("API_ID", 0))
        self.API_HASH = getenv("API_HASH")

        self.BOT_TOKEN = getenv("BOT_TOKEN")
        self.MONGO_URL = getenv("MONGO_URL")

        self.LOGGER_ID = int(getenv("LOGGER_ID", 0))
        self.OWNER_ID = int(getenv("OWNER_ID", 0))

        self.DURATION_LIMIT = int(getenv("DURATION_LIMIT", 60)) * 60
        self.QUEUE_LIMIT = int(getenv("QUEUE_LIMIT", 20))
        self.PLAYLIST_LIMIT = int(getenv("PLAYLIST_LIMIT", 20))
        self.SONG_DOWNLOAD_LIMIT = int(getenv("SONG_DOWNLOAD_LIMIT", 20)) * 60

        self.SESSION1 = getenv("SESSION", None)
        self.SESSION2 = getenv("SESSION2", None)
        self.SESSION3 = getenv("SESSION3", None)

        self.SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/fallenx")
        self.SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/DevilsHeavenMF")

        self.AUTO_LEAVE: bool = getenv("AUTO_LEAVE", "False").lower() == "true"
        self.AUTO_END: bool = getenv("AUTO_END", "False").lower() == "true"
        self.AUTO_END_DELAY: int = int(getenv("AUTO_END_DELAY", 300))

        self.THUMB_GEN: bool = getenv("THUMB_GEN", "True").lower() == "true"
        self.VIDEO_PLAY: bool = getenv("VIDEO_PLAY", "True").lower() == "true"

        self.LANG_CODE = getenv("LANG_CODE", "ar")

        # ── ArtistBots API (YouTube bypass for datacenter IPs) ──────────────
        # When set, the bot downloads audio/video via:
        #   GET {API_URL}/download?url={video_id}&type=audio&api_key={key}
        #   GET {VIDEO_API_URL}/download?url={video_id}&type=video&api_key={key}
        # Leave empty → bot will fail to download (ArtistBots is required).
        self.API_URL: str = getenv("API_URL", "").strip()
        self.VIDEO_API_URL: str = getenv("VIDEO_API_URL", "").strip()
        # Comma-separated keys (e.g. "key1,key2,key3") — each has 500/day quota.
        # Bot rotates round-robin so N keys ≈ N×500 requests/day.
        # Falls back to single API_KEY for backwards compatibility.
        self.API_KEYS: List[str] = self._parse_api_keys()

        self.DEFAULT_THUMB = getenv("DEFAULT_THUMB", "https://te.legra.ph/file/3e40a408286d4eda24191.jpg")
        self.PING_IMG = getenv("PING_IMG", "https://files.catbox.moe/haagg2.png")
        self.START_IMG = getenv("START_IMG", "https://files.catbox.moe/zvziwk.jpg")

    def _parse_api_keys(self) -> List[str]:
        """Parse API_KEYS (comma-separated) with fallback to single API_KEY."""
        raw = getenv("API_KEYS", "").strip()
        keys = [k.strip() for k in raw.split(",") if k.strip()] if raw else []
        if not keys:
            single = getenv("API_KEY", "").strip()
            if single:
                keys = [single]
        return keys

    def check(self):
        missing = [
            var
            for var in ["API_ID", "API_HASH", "BOT_TOKEN", "MONGO_URL", "LOGGER_ID", "OWNER_ID", "SESSION1"]
            if not getattr(self, var)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
