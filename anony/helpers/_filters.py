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
