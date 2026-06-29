# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio

from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported, ConnectionError)
from pyrogram.errors import (ChatSendMediaForbidden, ChatSendPhotosForbidden,
                             MessageIdInvalid)
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from anony import (app, config, db, lang, logger,
                   queue, thumb, userbot, yt)
from anony.helpers import Media, Track, buttons


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self._play_next_locks: dict = {}       # per-chat lock to prevent duplicate play_next
        self._stream_end_cache: dict = {}      # dedup: skip duplicate StreamEnded events

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=True)
        return await client.pause(chat_id)

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=False)
        return await client.resume(chat_id)

    async def stop(self, chat_id: int) -> None:
        client = await db.get_assistant(chat_id)
        queue.clear(chat_id)
        await db.remove_call(chat_id)
        await db.set_loop(chat_id, 0)

        try:
            await client.leave_call(chat_id, close=False)
        except Exception:
            pass

    async def seek_stream(self, chat_id: int, seconds: int) -> bool:
        """Seek to a specific position in the current stream."""
        try:
            if not await db.get_call(chat_id):
                return False

            media = queue.get_current(chat_id)
            if not media or media.is_live:
                return False

            media.time = seconds
            _lang = await lang.get_lang(chat_id)
            try:
                msg = await app.get_messages(chat_id, media.message_id)
            except Exception:
                msg = None

            if not msg:
                msg = await app.send_message(chat_id=chat_id, text=_lang["seeking"])

            await self.play_media(chat_id, msg, media, seek_time=seconds)
            return True
        except Exception as e:
            logger.warning(f"Seek stream failed for {chat_id}: {e}")
            return False

    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
    ) -> None:
        client = await db.get_assistant(chat_id)
        _lang = await lang.get_lang(chat_id)
        _thumb = (
            await thumb.generate(media)
            if isinstance(media, Track)
            else config.DEFAULT_THUMB
        ) if config.THUMB_GEN else None

        if not media.file_path:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            return await self.play_next(chat_id)

        # Optimized ffmpeg params for lag-free playback
        if seek_time > 1:
            ffmpeg_params = f"-ss {seek_time} -probesize 10M -analyzeduration 5M -rtbufsize 5M -fflags +genpts+igndts"
        else:
            ffmpeg_params = "-probesize 10M -analyzeduration 5M -rtbufsize 5M -fflags +genpts+igndts -sync ext"

        stream = types.MediaStream(
            media_path=media.file_path,
            audio_parameters=types.AudioQuality.STUDIO,
            video_parameters=types.VideoQuality.HD_720p,
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=(
                types.MediaStream.Flags.AUTO_DETECT
                if getattr(media, "video", False)
                else types.MediaStream.Flags.IGNORE
            ),
            ffmpeg_parameters=ffmpeg_params,
        )

        try:
            # Retry logic for transient group call errors
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await client.play(
                        chat_id=chat_id,
                        stream=stream,
                        config=types.GroupCallConfig(auto_start=True),
                    )
                    break
                except (exceptions.NoActiveGroupCall,) as e:
                    if attempt < max_retries - 1:
                        logger.debug(f"Group call transitioning for {chat_id}, retrying... ({attempt+1}/{max_retries})")
                        await asyncio.sleep(1)
                    else:
                        raise
                except Exception as e:
                    err = str(e).lower()
                    if ("cannot be initialized more than once" in err or "connection" in err) and attempt < max_retries - 1:
                        try:
                            await client.leave_call(chat_id, close=False)
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                    else:
                        raise

            if not seek_time:
                media.time = 1
                await db.add_call(chat_id)
                text = _lang["play_media"].format(
                    media.url,
                    media.title,
                    media.duration,
                    media.user,
                )
                keyboard = buttons.controls(chat_id)
                try:
                    if _thumb:
                        await message.edit_media(
                            media=InputMediaPhoto(media=_thumb, caption=text),
                            reply_markup=keyboard,
                        )
                    else:
                        await message.edit_text(text, reply_markup=keyboard)
                except (ChatSendMediaForbidden, ChatSendPhotosForbidden, MessageIdInvalid):
                    if _thumb:
                        sent = await app.send_photo(
                            chat_id=chat_id, photo=_thumb,
                            caption=text, reply_markup=keyboard,
                        )
                    else:
                        sent = await app.send_message(
                            chat_id=chat_id, text=text, reply_markup=keyboard,
                        )
                    media.message_id = sent.id
            else:
                media.time = seek_time

        except FileNotFoundError:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self.play_next(chat_id)
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_no_call"])
        except exceptions.NoAudioSourceFound:
            await message.edit_text(_lang["error_no_audio"])
            await self.play_next(chat_id)
        except (ConnectionError, ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
        except RTMPStreamingUnsupported:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_rtmp"])
        except Exception as e:
            logger.error(f"Unexpected error in play_media for {chat_id}: {e}", exc_info=True)
            await self.stop(chat_id)
            try:
                await message.edit_text(f"❌ Playback error: {str(e)[:100]}")
            except Exception:
                pass

    async def replay(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return

        media = queue.get_current(chat_id)
        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)

    async def play_next(self, chat_id: int) -> None:
        # Prevent concurrent play_next calls for same chat
        if chat_id not in self._play_next_locks:
            self._play_next_locks[chat_id] = asyncio.Lock()

        lock = self._play_next_locks[chat_id]
        if lock.locked():
            logger.info(f"play_next already running for {chat_id}, skipping duplicate call")
            return

        async with lock:
            try:
                if not await db.get_call(chat_id):
                    return

                loop_count = await db.get_loop(chat_id)

                # Loop mode
                if loop_count == 1:
                    return await self.replay(chat_id)
                if loop_count > 1:
                    await db.set_loop(chat_id, loop_count - 1)
                    return await self.replay(chat_id)

                # Save last track for autoplay before advancing
                _last_track = queue.get_current(chat_id)

                media = queue.get_next(chat_id)

                try:
                    if media and media.message_id:
                        await app.delete_messages(
                            chat_id=chat_id,
                            message_ids=media.message_id,
                            revoke=True,
                        )
                        media.message_id = 0
                except Exception as e:
                    logger.debug(f"Could not delete previous message in {chat_id}: {e}")

                if not media:
                    # ── Autoplay: find a related song ────────────────────────────
                    if _last_track and await db.get_autoplay(chat_id):
                        try:
                            _lang = await lang.get_lang(chat_id)
                            _autoplay_msg = await app.send_message(
                                chat_id=chat_id,
                                text=f"🎵 Autoplaying similar songs..."
                            )
                            _next_track = await yt.search_related(
                                title=_last_track.title,
                                channel_name=getattr(_last_track, "channel_name", None),
                                exclude_id=_last_track.id,
                            )
                            if _next_track:
                                _next_track.user = "Autoplay"
                                if not _next_track.file_path:
                                    _next_track.file_path = await yt.download(
                                        _next_track.id,
                                        video=getattr(_next_track, "video", False),
                                    )
                                if _next_track.file_path:
                                    queue.add(chat_id, _next_track)
                                    await self.play_media(chat_id, _autoplay_msg, _next_track)
                                    return
                            # Autoplay failed — clean up message
                            try:
                                await _autoplay_msg.delete()
                            except Exception:
                                pass
                        except Exception as e:
                            logger.warning(f"Autoplay failed for {chat_id}: {e}")

                    return await self.stop(chat_id)

                _lang = await lang.get_lang(chat_id)
                msg = None
                try:
                    msg = await app.send_message(chat_id=chat_id, text=_lang["play_next"])
                except Exception as e:
                    logger.error(f"Failed to send play_next message for {chat_id}: {e}")

                if not media.file_path:
                    is_live = getattr(media, "is_live", False)
                    media.file_path = await yt.download(
                        media.id,
                        is_live=is_live,
                        video=getattr(media, "video", False),
                    )
                    if not media.file_path:
                        if msg:
                            await msg.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
                        await self.play_next(chat_id)
                        return

                media.message_id = msg.id if msg else 0
                if msg:
                    await self.play_media(chat_id, msg, media)
                else:
                    logger.info(f"Playing next track for {chat_id} without message update")
                    await self.play_media(chat_id, None, media)

            except Exception as e:
                logger.error(f"Error in play_next for {chat_id}: {e}", exc_info=True)
                try:
                    await self.stop(chat_id)
                except Exception:
                    pass

    async def ping(self) -> float:
        pings = [client.ping for client in self.clients]
        return round(sum(pings) / len(pings), 2)

    async def decorators(self, client: PyTgCalls) -> None:
        @client.on_update()
        async def update_handler(_, update: types.Update) -> None:
            if isinstance(update, types.StreamEnded):
                if update.stream_type == types.StreamEnded.Type.AUDIO:
                    chat_id = update.chat_id
                    current_time = asyncio.get_event_loop().time()

                    # Deduplicate rapid StreamEnded events for the same chat
                    if chat_id in self._stream_end_cache:
                        if current_time - self._stream_end_cache[chat_id] < 2.0:
                            return

                    self._stream_end_cache[chat_id] = current_time
                    # Clean old cache entries
                    self._stream_end_cache = {
                        cid: t for cid, t in self._stream_end_cache.items()
                        if current_time - t < 5.0
                    }
                    await self.play_next(chat_id)

            elif isinstance(update, types.ChatUpdate):
                if update.status in [
                    types.ChatUpdate.Status.KICKED,
                    types.ChatUpdate.Status.LEFT_GROUP,
                    types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                ]:
                    await self.stop(update.chat_id)

    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for ub in userbot.clients:
            client = PyTgCalls(ub, cache_duration=100)
            await client.start()
            self.clients.append(client)
            await self.decorators(client)
        logger.info("📞 PyTgCalls client(s) started.")
