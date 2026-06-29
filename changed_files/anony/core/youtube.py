# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic
#
# youtube.py — YouTube Handler (ArtistBots API + yt-dlp Cookies Fallback)
# ────────────────────────────────────────────────────────────────────────
# Search  : py_yt (VideosSearch / Playlist)
# Download: ArtistBots API (primary) → yt-dlp + cookies (fallback)
# Autoplay: search_related() — YouTube-style similar song discovery

import os
import re
import glob
import time
import asyncio
import aiohttp
import random
import yt_dlp
from dataclasses import replace
from pathlib import Path
from typing import Optional

from pyrogram import enums, types
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
            r"(youtube\.com/(watch\?v=|shorts/|live/|embed/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.iregex = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)"
            r"(?!/(watch\?v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}"
            r"|playlist\?list=PL[A-Za-z0-9_-]+|[A-Za-z0-9_-]{11}))\S*"
        )

        # Cookies state
        self.cookies: list[str] = []
        self._cookies_checked = False
        self._cookies_warned = False

        # ArtistBots session & round-robin key rotation
        self._api_session: Optional[aiohttp.ClientSession] = None
        self._api_session_lock = asyncio.Lock()
        self._api_key_index = 0
        self._api_key_lock = asyncio.Lock()

        # Limit concurrent downloads (prevents bandwidth saturation)
        self._download_semaphore = asyncio.Semaphore(5)

        # Search result cache (max 100 entries, TTL 10 min)
        self._search_cache: dict = {}

    # ── URL helpers ─────────────────────────────────────────────────────────────

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    def url(self, message_1: types.Message) -> Optional[str]:
        """Extract YouTube URL from a Pyrogram message (or its reply)."""
        messages = [message_1]
        link = None

        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            text = message.text or message.caption or ""

            if message.entities:
                for entity in message.entities:
                    if entity.type == enums.MessageEntityType.URL:
                        link = text[entity.offset: entity.offset + entity.length]
                        break

            if message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == enums.MessageEntityType.TEXT_LINK:
                        link = entity.url
                        break

        if link:
            # Remove tracking parameters
            return link.split("&si")[0].split("?si")[0]
        return None

    # ── Cookie helpers ──────────────────────────────────────────────────────────

    def get_cookies(self) -> Optional[str]:
        """Return a random cookie file path from anony/cookies/ directory."""
        if not self._cookies_checked:
            cookies_dir = "anony/cookies"
            if os.path.exists(cookies_dir):
                for f in os.listdir(cookies_dir):
                    if f.endswith(".txt"):
                        self.cookies.append(f)
            self._cookies_checked = True

        if not self.cookies:
            if not self._cookies_warned:
                self._cookies_warned = True
                logger.warning("🍪 No cookie files found in anony/cookies/; yt-dlp fallback may fail.")
            return None

        cookie_file = f"anony/cookies/{random.choice(self.cookies)}"
        logger.debug(f"Using cookie file: {cookie_file}")
        return cookie_file

    async def save_cookies(self, urls: list[str]) -> None:
        """Download and save cookies from pastebin/batbin URLs."""
        logger.info("🍪 Saving cookies from urls...")
        saved_count = 0
        cookies_dir = Path("anony/cookies")
        cookies_dir.mkdir(parents=True, exist_ok=True)

        for url in urls:
            try:
                path = cookies_dir / f"cookie{random.randint(10000, 99999)}.txt"
                link = url
                if "pastebin.com" in url and "/raw" not in url:
                    link = url.replace("pastebin.com", "pastebin.com/raw")
                elif "batbin.me" in url and "/raw" not in url:
                    link = url.replace("batbin.me", "batbin.me/raw")

                async with aiohttp.ClientSession() as session:
                    async with session.get(link, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status != 200:
                            logger.error(f"❌ Cookie download failed: HTTP {resp.status} from {url}")
                            continue
                        content = await resp.read()
                        if not content or len(content) < 50:
                            logger.error(f"❌ Cookie file empty/invalid from {url}")
                            continue
                        path.write_bytes(content)
                        if path.exists() and path.stat().st_size > 0:
                            saved_count += 1
                            fname = path.name
                            if fname not in self.cookies:
                                self.cookies.append(fname)
                            logger.info(f"✅ Saved: {fname} ({len(content)} bytes)")
            except Exception as e:
                logger.error(f"❌ Cookie download error from {url}: {e}")

        self._cookies_checked = True
        if saved_count > 0:
            logger.info(f"✅ Cookies saved successfully! ({saved_count} file(s))")
        else:
            logger.error("❌ No cookies saved! Check COOKIE_URL in .env.")

    # ── ArtistBots API helpers ──────────────────────────────────────────────────

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

        for attempt in range(2):
            try:
                session = await self._get_api_session()
                endpoint = f"{base_url.rstrip('/')}/download"
                logger.debug(f"ArtistBots [{masked}] → {endpoint} ({download_type})")

                async with session.get(
                    endpoint,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=600),
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

            if attempt == 0:
                logger.info(f"🔄 Retrying ArtistBots download for {vid}...")
        return None

    # ── yt-dlp Cookies Fallback ─────────────────────────────────────────────────

    def _locate_download_file(self, video_id: str, video: bool = False) -> Optional[str]:
        """Locate any completed download file for a video id."""
        pattern = f"downloads/{video_id}*"
        candidates = sorted([
            path for path in glob.glob(pattern)
            if not path.endswith((".part", ".ytdl", ".info.json", ".temp"))
        ])

        video_exts = {".mp4", ".mkv", ".webm", ".mov"}
        audio_exts = {".m4a", ".webm", ".opus", ".mp3", ".ogg", ".wav", ".flac"}

        if video:
            for path in candidates:
                if not os.path.isdir(path) and Path(path).suffix.lower() in video_exts:
                    return path
        else:
            for path in candidates:
                if not os.path.isdir(path) and Path(path).suffix.lower() in audio_exts:
                    return path
            for path in candidates:
                if not os.path.isdir(path) and Path(path).suffix.lower() in {".mp4", ".mkv", ".mov"}:
                    return path

        for path in candidates:
            if not os.path.isdir(path):
                return path
        return None

    async def download_via_cookies(self, video_id: str, video: bool = False) -> Optional[str]:
        """
        Download audio/video using yt-dlp with cookies (Fallback Method).
        """
        url = self.base + video_id
        filename_pattern = f"downloads/{video_id}"

        # Check existing files
        existing = [f for f in glob.glob(f"{filename_pattern}.*") if not f.endswith(".part")]
        if existing:
            if video:
                vf = [f for f in existing if Path(f).suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
                if vf:
                    return vf[0]
            else:
                af = [f for f in existing if Path(f).suffix.lower() in {".m4a", ".webm", ".opus", ".mp3"}]
                if af:
                    return af[0]

        Path("downloads").mkdir(parents=True, exist_ok=True)

        async with self._download_semaphore:
            cookie = self.get_cookies()
            base_opts = {
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "quiet": True,
                "noplaylist": True,
                "geo_bypass": True,
                "no_warnings": True,
                "overwrites": False,
                "nocheckcertificate": True,
                "continuedl": True,
                "noprogress": True,
                "concurrent_fragment_downloads": 4,
                "http_chunk_size": 524288,
                "socket_timeout": 30,
                "retries": 2,
                "fragment_retries": 2,
                "extractor_retries": 5,
                "sleep_interval_requests": 1,
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }

            if video:
                ydl_opts = {
                    **base_opts,
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                    "merge_output_format": "mp4",
                    "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
                }
            else:
                ydl_opts = {
                    **base_opts,
                    "format": "bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio/best",
                    "postprocessors": [],
                }

            if cookie:
                ydl_opts["cookiefile"] = cookie

            def _download(opts):
                ydl = None
                try:
                    ydl = yt_dlp.YoutubeDL(opts)
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        return None
                    time.sleep(0.5)
                    located = self._locate_download_file(video_id, video=video)
                    if located:
                        logger.info(f"✅ Download completed: {located}")
                        return located
                    logger.error(f"❌ Download finished but file not found for: {video_id}")
                    return None
                except Exception as ex:
                    logger.warning(f"⚠️ Download error for {video_id}: {ex}")
                    recovered = self._locate_download_file(video_id, video=video)
                    if recovered:
                        logger.info(f"✅ Recovered existing file: {recovered}")
                        return recovered
                    return None
                finally:
                    if ydl:
                        try:
                            ydl.close()
                        except Exception:
                            pass

            logger.info(f"🍪 [COOKIES FALLBACK] Downloading {video_id} with yt-dlp...")
            result = await asyncio.to_thread(_download, ydl_opts)
            if result:
                logger.info(f"✅ [COOKIES SUCCESS] Downloaded: {result}")
            else:
                logger.warning(f"⚠️ [COOKIES FAILED] Could not download {video_id}")
            return result

    # ── Live stream helper ──────────────────────────────────────────────────────

    async def _extract_live_url(self, video_id: str) -> Optional[str]:
        """Extract direct stream URL for a live stream using yt-dlp."""
        cookie = self.get_cookies()
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "cookiefile": cookie,
            "format": "bestaudio/best",
            "noplaylist": True,
            "socket_timeout": 20,
            "extractor_retries": 5,
            "sleep_interval_requests": 1,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(self.base + video_id, download=False)
                    if not info:
                        return None
                    direct = info.get("url")
                    if direct:
                        return direct
                    for fmt in info.get("formats", []):
                        if fmt.get("acodec") != "none" and fmt.get("url"):
                            return fmt["url"]
                    return info.get("manifest_url")
                except Exception as ex:
                    logger.error(f"Live stream extraction failed: {ex}")
                    return None

        try:
            stream_url = await asyncio.wait_for(asyncio.to_thread(_extract), timeout=35)
            if stream_url:
                logger.info(f"✅ Live stream URL extracted for {video_id}")
            return stream_url
        except asyncio.TimeoutError:
            logger.error(f"⏰ Live stream URL extraction timed out for {video_id}")
            return None

    # ── Public API ──────────────────────────────────────────────────────────────

    async def search(self, query: str, m_id: int, video: bool = False) -> Optional[Track]:
        """Search YouTube via py_yt with caching."""
        cache_key = f"{query}:{video}"
        current_time = asyncio.get_running_loop().time()

        if cache_key in self._search_cache:
            cached_result, cache_timestamp = self._search_cache[cache_key]
            if current_time - cache_timestamp < 600:  # 10 min TTL
                fresh = replace(cached_result)
                fresh.message_id = m_id
                fresh.file_path = None
                fresh.user = None
                fresh.time = 0
                fresh.video = video
                return fresh

        try:
            _search = VideosSearch(query, limit=1)
            results = await asyncio.wait_for(_search.next(), timeout=8)
        except asyncio.TimeoutError:
            logger.warning(f"⏰ YouTube search timed out: {query}")
            return None
        except Exception as e:
            logger.warning(f"⚠️ YouTube search error '{query}': {e}")
            return None

        if not results or not results.get("result"):
            return None

        data = results["result"][0]
        duration = data.get("duration")
        is_live = duration is None or duration == "LIVE"

        track = Track(
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

        # Cache result
        self._search_cache[cache_key] = (track, current_time)
        if len(self._search_cache) > 100:
            oldest_key = min(self._search_cache.keys(), key=lambda k: self._search_cache[k][1])
            del self._search_cache[oldest_key]

        return replace(track)

    async def search_related(
        self,
        title: str,
        channel_name: str = None,
        exclude_id: str = None,
        limit: int = 8,
    ) -> Optional[Track]:
        """
        Search for a DIFFERENT related song — YouTube-style autoplay.
        Tries multiple query variations and randomly picks one that is
        not the currently-playing song.
        """
        queries = []
        if channel_name:
            queries.append(f"{channel_name} songs")

        # Strip common suffixes/prefixes that would pin us to the exact song
        clean_title = re.sub(r"\s*[-|].*", "", title).strip()
        queries += [
            f"{clean_title} similar songs",
            f"songs like {clean_title}",
            f"{clean_title} best songs",
        ]
        if channel_name:
            queries.append(f"{channel_name} best songs")

        tried = set()
        for query in queries:
            if query in tried:
                continue
            tried.add(query)
            try:
                _search = VideosSearch(query, limit=limit)
                results = await _search.next()
            except Exception as e:
                logger.debug(f"search_related query failed '{query}': {e}")
                continue

            if not results or not results.get("result"):
                continue

            candidates = [
                r for r in results["result"]
                if r.get("id") and r.get("link") and r.get("id") != exclude_id
            ]
            if not candidates:
                continue

            random.shuffle(candidates)
            data = candidates[0]

            duration = data.get("duration")
            is_live = duration is None or duration == "LIVE"

            return Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=duration if not is_live else "LIVE",
                duration_sec=0 if is_live else utils.to_seconds(duration),
                message_id=0,
                title=(data.get("title") or "")[:25],
                thumbnail=data.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                is_live=is_live,
            )

        return None

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

    async def download(
        self,
        video_id: str,
        is_live: bool = False,
        video: bool = False,
    ) -> Optional[str]:
        """
        Download audio or video from YouTube.

        PRIORITY: ArtistBots API (primary) → yt-dlp + cookies (fallback)

        Args:
            video_id: YouTube video ID
            is_live: Whether it's a live stream
            video: True for video download, False for audio
        Returns:
            Local file path, or None on failure
        """
        # ── Live streams: use yt-dlp to extract direct stream URL ───────────────
        if is_live:
            logger.info(f"📺 Live stream detected for {video_id}, using yt-dlp...")
            return await self._extract_live_url(video_id)

        # ── Regular audio/video download ─────────────────────────────────────────
        ext = ".mp4" if video else ".mp3"
        cached = f"downloads/{video_id}{ext}"
        if os.path.exists(cached) and os.path.getsize(cached) > 0:
            return cached

        async with self._download_semaphore:
            # Priority 1: ArtistBots API
            base_url = config.VIDEO_API_URL if video else config.API_URL
            if base_url and config.API_KEYS:
                logger.info(f"🎯 [PRIORITY 1] Trying ArtistBots API for {video_id}")
                result = await self._artistbots_download(video_id, base_url, video)
                if result:
                    logger.info(f"✅ [SUCCESS] Downloaded via API: {video_id}")
                    return result
                logger.warning(f"⚠️ [API FAILED] {video_id}, trying cookies fallback...")

            # Priority 2: yt-dlp with cookies (if enabled)
            if config.ENABLE_COOKIES_FALLBACK:
                logger.info(f"🍪 [PRIORITY 2] Trying yt-dlp cookies for {video_id}")
                result = await self.download_via_cookies(video_id, video=video)
                if result:
                    logger.info(f"✅ [SUCCESS] Downloaded via cookies: {video_id}")
                    return result

            logger.error(f"❌ [FAILED] All download methods failed for {video_id}")
            return None
