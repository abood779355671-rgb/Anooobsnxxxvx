# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, lang
from anony.helpers import can_manage_vc_strict, cmd, phrase


@app.on_message(
    (cmd(["openvc", "فتح_المكالمة"]) | phrase(["فتح المكالمة"]))
    & filters.group
    & ~app.bl_users
)
@lang.language()
@can_manage_vc_strict
async def _open_call(_, m: types.Message):
    sent = await m.reply_text(m.lang["vc_open_opening"])
    try:
        await anon.open_call(m.chat.id)
    except Exception as e:
        return await sent.edit_text(m.lang["vc_open_error"].format(str(e)))

    await sent.edit_text(m.lang["vc_open_success"].format(m.from_user.mention))


@app.on_message(
    (cmd(["closevc", "غلق_المكالمة", "اغلاق_المكالمة"]) | phrase(["غلق المكالمة", "اغلاق المكالمة"]))
    & filters.group
    & ~app.bl_users
)
@lang.language()
@can_manage_vc_strict
async def _close_call(_, m: types.Message):
    sent = await m.reply_text(m.lang["vc_close_closing"])
    try:
        await anon.close_call(m.chat.id)
    except Exception as e:
        return await sent.edit_text(m.lang["vc_close_error"].format(str(e)))

    await sent.edit_text(m.lang["vc_close_success"].format(m.from_user.mention))

