# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic
#
# youtube.py — YouTube Handler (ArtistBots API)
# ─────────────────────────────────────────────
# Search  : py_yt (VideosSearch / Playlist)
# Download: ArtistBots API only
#   GET {API_URL}/download?url={video_id}&type=audio&api_key={key}
#   GET {VIDEO_API_URL}/download?url={video_id}&type=video&api_key={key}

import os
import re
import asyncio
import aiohttp
from typing import Optional

from py_yt import Playlist, VideosSearch

from anony import config, logger
from anony.helpers import Track, utils


_YOUTUBE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_CHUNK_SIZE = 128 * 1024  # 128 KB


def _extract_video_id(link: str) -> str:
    """Return the bare 11-char YouTube video ID from a URL or bare ID."""
    if not link:
        return ""
    s = link.strip()
    if _YOUTUBE_ID_RE.match(s):
        return s
    if "v=" in s:
        return s.split("v=")[-1].split("&")[0]
    last = s.split("/")[-1].split("?")[0]
    if _YOUTUBE_ID_RE.match(last):
        return last
    return ""


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="

        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.iregex = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)"
            r"(?!/(watch\?v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}"
            r"|playlist\?list=PL[A-Za-z0-9_-]+|[A-Za-z0-9_-]{11}))\S*"
        )

        # ArtistBots session & round-robin key rotation
        self._api_session: Optional[aiohttp.ClientSession] = None
        self._api_session_lock = asyncio.Lock()
        self._api_key_index = 0
        self._api_key_lock = asyncio.Lock()

        # Limit concurrent downloads (prevents bandwidth saturation)
        self._download_semaphore = asyncio.Semaphore(5)

    # ── URL helpers ────────────────────────────────────────────────────────────

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    # ── ArtistBots API helpers ─────────────────────────────────────────────────

    async def _next_api_key(self) -> Optional[str]:
        """Round-robin across config.API_KEYS."""
        keys = config.API_KEYS
        if not keys:
            return None
        async with self._api_key_lock:
            key = keys[self._api_key_index % len(keys)]
            self._api_key_index = (self._api_key_index + 1) % len(keys)
            return key

    async def _get_api_session(self) -> aiohttp.ClientSession:
        """Shared aiohttp session (created once, reused)."""
        if self._api_session and not self._api_session.closed:
            return self._api_session
        async with self._api_session_lock:
            if self._api_session and not self._api_session.closed:
                return self._api_session
            timeout = aiohttp.ClientTimeout(total=600, sock_connect=20, sock_read=60)
            connector = aiohttp.TCPConnector(
                limit=0, ttl_dns_cache=300, enable_cleanup_closed=True
            )
            self._api_session = aiohttp.ClientSession(
                timeout=timeout, connector=connector
            )
            return self._api_session

    async def _artistbots_download(
        self, vid: str, base_url: str, video: bool
    ) -> Optional[str]:
        """
        Download audio/video via ArtistBots API (streams response to disk).
        Endpoint: GET {base_url}/download?url={vid}&type={audio|video}&api_key={key}
        """
        api_key = await self._next_api_key()
        if not base_url or not api_key:
            logger.error("❌ ArtistBots not configured (API_URL / API_KEYS missing)")
            return None

        download_type = "video" if video else "audio"
        file_ext = ".mp4" if video else ".mp3"
        out_path = f"downloads/{vid}{file_ext}"

        os.makedirs("downloads", exist_ok=True)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path

        params = {"url": vid, "type": download_type, "api_key": api_key}
        masked = api_key[:8] + "..." if len(api_key) > 8 else "***"

        try:
            session = await self._get_api_session()
            endpoint = f"{base_url.rstrip('/')}/download"
            logger.debug(f"ArtistBots [{masked}] → {endpoint} ({download_type})")

            async with session.get(
                endpoint,
                params=params,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"⚠️ ArtistBots returned HTTP {resp.status} for {vid} (key {masked})"
                    )
                    return None
                with open(out_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)

            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                logger.info(f"✅ {download_type.capitalize()} downloaded via ArtistBots: {vid}")
                return out_path

            if os.path.exists(out_path):
                os.remove(out_path)
            return None

        except asyncio.TimeoutError:
            logger.error(f"⏰ ArtistBots timeout for {vid} (key {masked})")
        except aiohttp.ClientError as e:
            logger.error(f"🌐 ArtistBots client error for {vid}: {e}")
        except Exception as e:
            logger.error(f"❌ ArtistBots download failed for {vid}: {type(e).__name__}: {e}")
        return None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def search(self, query: str, m_id: int, video: bool = False) -> Optional[Track]:
        """Search YouTube via py_yt."""
        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await asyncio.wait_for(_search.next(), timeout=20)
        except asyncio.TimeoutError:
            logger.warning(f"⏰ YouTube search timed out for query: {query}")
            return None
        except Exception as e:
            logger.warning(f"⚠️ YouTube search error for '{query}': {e}")
            return None

        if not results or not results.get("result"):
            return None

        data = results["result"][0]
        duration = data.get("duration")
        is_live = duration is None or duration == "LIVE"

        return Track(
            id=data.get("id"),
            channel_name=data.get("channel", {}).get("name"),
            duration=duration if not is_live else "LIVE",
            duration_sec=0 if is_live else utils.to_seconds(duration),
            message_id=m_id,
            title=(data.get("title") or "")[:25],
            thumbnail=data.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
            url=data.get("link"),
            view_count=data.get("viewCount", {}).get("short"),
            is_live=is_live,
            video=video,
        )

    async def playlist(self, limit: int, user: str, url: str, video: bool = False) -> list:
        """Extract tracks from a YouTube playlist URL."""
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in (plist.get("videos") or [])[:limit]:
                try:
                    link = data.get("link", "")
                    if "&list=" in link:
                        link = link.split("&list=")[0]
                    thumbnails = data.get("thumbnails") or [{}]
                    thumb_url = thumbnails[-1].get("url", "").split("?")[0]
                    duration = data.get("duration", "0:00")
                    tracks.append(Track(
                        id=data.get("id", ""),
                        channel_name=data.get("channel", {}).get("name", ""),
                        duration=duration,
                        duration_sec=utils.to_seconds(duration),
                        title=(data.get("title") or "Unknown")[:25],
                        thumbnail=thumb_url,
                        url=link,
                        user=user,
                        view_count="",
                        video=video,
                    ))
                except Exception:
                    continue
        except Exception:
            pass
        return tracks

    async def download(self, video_id: str, video: bool = False) -> Optional[str]:
        """
        Download audio or video via ArtistBots API.
        Returns the local file path, or None on failure.
        """
        # Return cached file if already on disk
        ext = ".mp4" if video else ".mp3"
        cached = f"downloads/{video_id}{ext}"
        if os.path.exists(cached) and os.path.getsize(cached) > 0:
            return cached

        base_url = config.VIDEO_API_URL if video else config.API_URL
        if not base_url or not config.API_KEYS:
            logger.error(
                "❌ ArtistBots not configured — set API_URL/VIDEO_API_URL and API_KEYS in .env"
            )
            return None

        async with self._download_semaphore:
            result = await self._artistbots_download(video_id, base_url, video)
            if not result:
                logger.error(f"❌ ArtistBots failed for {video_id}. No fallback configured.")
            return result
