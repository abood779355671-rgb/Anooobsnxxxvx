# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import app, config, db, lang, userbot
from anony.helpers import admin_check, cmd


# ──────────────────────────────────────────────
#  /assistant  •  /myassistant
#  يعرض بيانات اليوزربوت المعيَّن للمجموعة الحالية
# ──────────────────────────────────────────────
@app.on_message(cmd(["assistant", "myassistant", "المساعد", "مساعدي"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _assistant(_, m: types.Message) -> None:
    chat_id = m.chat.id

    num = db.assistant.get(chat_id)
    if not num:
        return await m.reply_text(m.lang["assist_not_found"])

    client = await db.get_client(chat_id)
    if not client:
        return await m.reply_text(m.lang["assist_not_found"])

    username = f"@{client.username}" if client.username else "N/A"
    connected = "✅" if client in userbot.clients else "❌"

    await m.reply_text(
        m.lang["assist_info"].format(num, client.name, username, connected)
    )


# ──────────────────────────────────────────────
#  /setassistant <1|2|3>
#  يتيح للأدمن تعيين يوزربوت بعينه للمجموعة
# ──────────────────────────────────────────────
@app.on_message(cmd(["setassistant", "تعيين_مساعد"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _setassistant(_, m: types.Message) -> None:
    chat_id = m.chat.id

    # أرقام اليوزربوتات المتاحة فعلياً حسب الـ SESSIONs المضبوطة في config
    # (هذا أدق من len(userbot.clients) لأنه لا ينخدع لو كان هناك "فجوة"،
    #  مثلاً SESSION1 و SESSION3 مضبوطين بدون SESSION2)
    session_map = {1: config.SESSION1, 2: config.SESSION2, 3: config.SESSION3}
    valid_nums = [num for num, session in session_map.items() if session]

    # التحقق من وجود الرقم في الأمر
    if len(m.command) < 2 or not m.command[1].isdigit():
        return await m.reply_text(m.lang["assist_set_invalid"].format(max(valid_nums)))

    num = int(m.command[1])

    # تحقق واحد يغطي كل الحالات: ضمن 1-3 *و* SESSION الخاص به موجود فعلاً
    if num not in valid_nums:
        return await m.reply_text(m.lang["assist_set_invalid"].format(max(valid_nums)))

    # تحديث الذاكرة المؤقتة وقاعدة البيانات
    db.assistant[chat_id] = num
    await db.assistantdb.update_one(
        {"_id": chat_id},
        {"$set": {"num": num}},
        upsert=True,
    )

    # جلب بيانات الكلاينت الجديد وعرضها
    client = await db.get_client(chat_id)
    username = f"@{client.username}" if client.username else "N/A"

    await m.reply_text(
        m.lang["assist_set"].format(num, client.name, username)
    )


# ──────────────────────────────────────────────
#  /assistants
#  للسودو فقط — يعرض جميع اليوزربوتات مع إحصائياتها
# ──────────────────────────────────────────────
@app.on_message(cmd(["assistants", "المساعدون"]) & app.sudoers)
@lang.language()
async def _assistants(_, m: types.Message) -> None:
    if not userbot.clients:
        return await m.reply_text(m.lang["assist_not_found"])

    # حساب عدد المجموعات المُعيَّنة لكل رقم يوزربوت
    count_map: dict[int, int] = {}
    for assigned_num in db.assistant.values():
        count_map[assigned_num] = count_map.get(assigned_num, 0) + 1

    # نمر على الأرقام الحقيقية 1/2/3 بدل enumerate(userbot.clients)
    # حتى لا يختلط الترقيم في حال وجود "فجوة" بين الـ SESSIONs
    clients_map = {1: userbot.one, 2: userbot.two, 3: userbot.three}
    session_map = {1: config.SESSION1, 2: config.SESSION2, 3: config.SESSION3}

    text = m.lang["assist_list"]
    for num, session in session_map.items():
        if not session:
            continue
        client = clients_map[num]
        username = f"@{client.username}" if getattr(client, "username", None) else "N/A"
        groups = count_map.get(num, 0)
        text += f"\n{num}. <b>{client.name}</b> ({username}) — <code>{groups}</code> 🏘"

    await m.reply_text(text)


# ──────────────────────────────────────────────
#  /reassign
#  إعادة التوزيع العشوائي لليوزربوت
# ──────────────────────────────────────────────
@app.on_message(cmd(["reassign", "إعادة_تعيين"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _reassign(_, m: types.Message) -> None:
    chat_id = m.chat.id

    num = await db.set_assistant(chat_id)
    client = await db.get_client(chat_id)
    username = f"@{client.username}" if client.username else "N/A"

    await m.reply_text(
        m.lang["assist_reassigned"].format(num, client.name, username)
    )
