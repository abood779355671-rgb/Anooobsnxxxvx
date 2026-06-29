# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import can_manage_vc_strict, cmd


@app.on_message(cmd(["skip", "next", "تخطي", "التالي"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc_strict
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    delete_btn = types.InlineKeyboardMarkup(
        [[types.InlineKeyboardButton(text=m.lang["delete_msg"], callback_data="delete_this")]]
    )

    # التحقق من وجود قائمة انتظار
    has_next = queue.get_next(m.chat.id, check=True)

    await anon.play_next(m.chat.id)

    if has_next:
        text = m.lang["play_skipped"].format(m.from_user.mention)
    else:
        text = m.lang["play_skipped_empty"].format(m.from_user.mention)

    await m.reply_text(text, reply_markup=delete_btn)
