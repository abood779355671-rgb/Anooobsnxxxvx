# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from pyrogram import filters, types

from anony import anon, app, db, lang
from anony.helpers import can_manage_vc_strict, cmd


@app.on_message(cmd(["end", "stop", "إيقاف", "وقف", "انهاء", "انهي"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc_strict
async def _stop(_, m: types.Message):
    if len(m.command) > 1:
        return

    call = await db.get_call(m.chat.id)
    await anon.stop(m.chat.id)

    if not call:
        return await m.reply_text(m.lang["not_playing"])

    delete_btn = types.InlineKeyboardMarkup(
        [[types.InlineKeyboardButton(text=m.lang["delete_msg"], callback_data="delete_this")]]
    )
    await m.reply_text(
        m.lang["play_stopped"].format(m.from_user.mention),
        reply_markup=delete_btn,
    )
