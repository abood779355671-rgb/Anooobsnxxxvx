# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import app, db, lang
from anony.helpers import admin_check, cmd


@app.on_message(cmd(["vcinfo", "معلومات_البث", "مشاركون"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _vcinfo(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    sent = await m.reply_text(m.lang["vcinfo_fetching"])

    try:
        client = await db.get_assistant(m.chat.id)
        participants = await client.get_participants(m.chat.id)
    except Exception as e:
        return await sent.edit_text(m.lang["vcinfo_error"].format(str(e)))

    if not participants:
        return await sent.edit_text(m.lang["vcinfo_empty"])

    total = len(participants)
    muted = sum(1 for p in participants if getattr(p, "muted", False))
    unmuted = total - muted
    video_on = sum(
        1 for p in participants
        if getattr(p, "video_joined", False) or getattr(p, "video", False)
    )
    presenting = sum(
        1 for p in participants
        if getattr(p, "presentation_joined", False) or getattr(p, "screen_sharing", False)
    )
    raised_hand = sum(1 for p in participants if getattr(p, "raised_hand", False))

    text = m.lang["vcinfo_result"].format(
        m.chat.title,   # {0} اسم المجموعة
        total,          # {1} إجمالي المشاركين
        unmuted,        # {2} يتحدثون
        muted,          # {3} صامتون
        video_on,       # {4} فيديو مفعّل
        presenting,     # {5} مشاركة شاشة
        raised_hand,    # {6} يرفعون أيديهم
    )

    await sent.edit_text(text)


@app.on_message(cmd(["vcusers", "الصاعدين"]) & filters.group & ~app.bl_users)
@lang.language()
async def _vc_joined(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    sent = await m.reply_text(m.lang["vcjoined_fetching"])

    try:
        client = await db.get_assistant(m.chat.id)
        participants = await client.get_participants(m.chat.id)
    except Exception as e:
        return await sent.edit_text(m.lang["vcjoined_error"].format(str(e)))

    if not participants:
        return await sent.edit_text(m.lang["vcjoined_empty"])

    lines = ""
    count = 0
    for p in participants:
        user_id = getattr(p, "user_id", None)
        if not user_id:
            continue
        try:
            user = await app.get_users(user_id)
            name = user.mention
        except Exception:
            name = f"<code>{user_id}</code>"

        muted = getattr(p, "muted", False)
        status = "🔇" if muted else "🔊"
        count += 1
        lines += m.lang["vcjoined_item"].format(count, name, status)

    if not count:
        return await sent.edit_text(m.lang["vcjoined_empty"])

    text = m.lang["vcjoined_result"].format(m.chat.title, count, lines)
    await sent.edit_text(text)
