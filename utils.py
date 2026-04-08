import json
import os
from datetime import datetime, timezone
import discord


def load_json(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def build_embed(title: str, color: int, description: str | None = None):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def truncate_text(text: str, limit: int = 1024):
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def format_template(template: str, member, guild):
    values = {
        "mention": member.mention,
        "user": str(member),
        "server": guild.name,
        "member_count": guild.member_count,
    }
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
