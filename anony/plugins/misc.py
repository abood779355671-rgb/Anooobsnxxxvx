# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
import asyncio

from pyrogram import enums, errors, filters, types

from anony import anon, app, config, db, lang, queue, tasks, userbot, yt
from anony.helpers import buttons

# Tracks, per chat_id, the timestamp (time.time()) at which the voice chat
# was first observed to have no real listeners. Used by vc_watcher() to
# implement a grace period before auto-leaving (see AUTO_END_DELAY).
_empty_since: dict[int, float] = {}


@app.on_message(filters.video_chat_started, group=19)
@app.on_message(filters.video_chat_ended, group=20)
async def _watcher_vc(_, m: types.Message):
    await anon.stop(m.chat.id)


async def auto_leave():
    while True:
        await asyncio.sleep(3600)
        for ub in userbot.clients:
            try:
                chats = [dialog.chat.id async for dialog in ub.get_dialogs()
                            if dialog.chat.type in [
                                enums.ChatType.GROUP, enums.ChatType.SUPERGROUP,
                            ]][-20:]
                for chat in chats:
                    if chat in [app.logger, -1001686672798, -1001549206010]:
                        continue
                    if chat in db.active_calls:
                        continue
                    await ub.leave_chat(chat)
                    await asyncio.sleep(12)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue


async def track_time():
    while True:
        await asyncio.sleep(1)
        for chat_id in list(db.active_calls):
            if not await db.playing(chat_id):
                continue
            media = queue.get_current(chat_id)
            if not media:
                continue
            media.time += 1


async def update_timer(length=10, sleep=12):
    while True:
        await asyncio.sleep(sleep)
        for chat_id in list(db.active_calls):
            if not await db.playing(chat_id):
                continue
            try:
                media = queue.get_current(chat_id)
                if not media:
                    continue
                duration, message_id = media.duration_sec, media.message_id
                if not duration or not message_id or not media.time:
                    continue
                played = media.time
                remaining = max(duration - played, 0)
                pos = min(int((played / duration) * length), length - 1)
                timer = "—" * pos + "◉" + "—" * (length - pos - 1)

                if remaining <= 30:
                    next = queue.get_next(chat_id, check=True)
                    if next and not next.file_path:
                        next.file_path = await yt.download(next.id, video=next.video)

                if remaining < 10:
                    remove = True
                else:
                    if config.THUMB_GEN:
                        timer = f"{time.strftime('%M:%S', time.gmtime(played))} | {timer} | -{time.strftime('%M:%S', time.gmtime(remaining))}"
                    else:
                        timer = None
                    remove = False

                if not timer and not remove:
                    continue

                await app.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=buttons.controls(
                        chat_id=chat_id, timer=timer, remove=remove
                    ),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass


async def vc_watcher(sleep=15):
    while True:
        await asyncio.sleep(sleep)

        # Prune stale entries for chats that are no longer active, so the
        # dict doesn't grow forever.
        for chat_id in list(_empty_since):
            if chat_id not in db.active_calls:
                _empty_since.pop(chat_id, None)

        for chat_id in list(db.active_calls):
            client = await db.get_assistant(chat_id)
            media = queue.get_current(chat_id)
            participants = await client.get_participants(chat_id)

            if len(participants) >= 2:
                # A real listener is present, reset the grace timer.
                _empty_since.pop(chat_id, None)
                continue

            if chat_id not in _empty_since:
                # First time we've seen this chat empty, start the timer
                # but don't leave yet.
                _empty_since[chat_id] = time.time()
                continue

            if time.time() - _empty_since[chat_id] < config.AUTO_END_DELAY:
                continue

            # Grace period elapsed with no listeners, leave the chat.
            _lang = await lang.get_lang(chat_id)
            try:
                if media:
                    sent = await app.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=media.message_id,
                        reply_markup=buttons.controls(
                            chat_id=chat_id, status=_lang["stopped"], remove=True
                        ),
                    )
                    await anon.stop(chat_id)
                    await sent.reply_text(_lang["auto_left"])
                else:
                    await anon.stop(chat_id)
                    await app.send_message(chat_id, _lang["auto_left"])
                _empty_since.pop(chat_id, None)
            except errors.MessageIdInvalid:
                # Leave didn't complete (stale message); leave the timer
                # entry in place so it's retried on the next tick.
                pass


if config.AUTO_END:
    tasks.append(asyncio.create_task(vc_watcher()))
if config.AUTO_LEAVE:
    tasks.append(asyncio.create_task(auto_leave()))
tasks.append(asyncio.create_task(track_time()))
tasks.append(asyncio.create_task(update_timer()))
