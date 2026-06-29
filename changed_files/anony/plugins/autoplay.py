# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic
#
# autoplay.py — Toggle YouTube-style autoplay for groups

from pyrogram import filters, types
from anony import app, db, lang
from anony.helpers import cmd


@app.on_message(
    cmd(["autoplay", "تشغيل_تلقائي"])
    & filters.group
)
@lang.language()
async def autoplay_handler(_, m: types.Message) -> None:
    chat_id = m.chat.id
    current = await db.get_autoplay(chat_id)
    await db.set_autoplay(chat_id, not current)
    status = "✅ تم تفعيل التشغيل التلقائي" if not current else "❌ تم إيقاف التشغيل التلقائي"
    await m.reply_text(
        f"<b>{status}</b>\n\n"
        f"<blockquote>سيتم تشغيل أغاني مشابهة تلقائياً بعد انتهاء قائمة التشغيل.</blockquote>"
    )
