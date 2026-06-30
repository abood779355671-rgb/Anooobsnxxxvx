# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from pyrogram import filters


def cmd(commands, prefixes=None):
    """
    Custom command filter that works with AND without the '/' prefix.
    e.g. both '/play' and 'play' will trigger the handler.
    """
    if isinstance(commands, str):
        commands = [commands]

    # Build a combined filter: /command OR command (no prefix)
    slash_filter = filters.command(commands, prefixes="/")
    no_prefix_filter = filters.command(commands, prefixes="")

    return slash_filter | no_prefix_filter


def phrase(phrases):
    """
    Custom filter that matches a message whose full text (optionally
    prefixed with '/') equals one of the given phrases exactly.
    Needed for multi-word commands (e.g. "فتح المكالمة") since Telegram's
    command system only recognizes single-word commands.
    """
    if isinstance(phrases, str):
        phrases = [phrases]
    normalized = {p.strip() for p in phrases}

    async def func(_, __, m):
        if not m.text:
            return False
        text = m.text.strip()
        if text.startswith("/"):
            text = text[1:]
        return text in normalized

    return filters.create(func)
