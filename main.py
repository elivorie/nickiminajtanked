import os
import json
from datetime import timedelta, datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands

from utils import load_json, save_json, build_embed, truncate_text, utc_now_iso, format_template

TOKEN = os.getenv("DISCORD_TOKEN")
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")

SETTINGS_FILE = "data/settings.json"
WARNS_FILE = "data/warns.json"
AUTOMOD_FILE = "data/automod.json"
LASTFM_USERS_FILE = "data/lastfm_users.json"
STICKY_FILE = "data/sticky.json"
SNIPE_FILE = "data/snipe.json"
NP_TRIGGERS_FILE = "data/np_triggers.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# -------------------------
# defaults + file helpers
# -------------------------

def default_guild_settings():
    return {
        "mod_log_channel_id": 0,
        "delete_log_channel_id": 0,
        "edit_log_channel_id": 0,
        "join_leave_log_channel_id": 0,
        "boost_log_channel_id": 0,
        "welcome_channel_id": 0,
        "booster_role_id": 0,
        "member_role_id": 0,
        "jail_role_id": 0,
        "anti_link_enabled": False,
        "anti_spam_enabled": False,
        "anti_invite_enabled": False,
        "welcome_enabled": False,
        "goodbye_enabled": False,
        "boost_message_enabled": False,
        "welcome_message": "Welcome to **{server}**, {mention} ♡",
        "goodbye_message": "**{user}** left **{server}**",
        "boost_message": "Thank you for boosting **{server}**, {mention} ♡",
        "boost_embed_title": "thank you for boosting",
        "boost_embed_footer": "",
        "boost_embed_image": "",
        "boost_embed_thumbnail_mode": "avatar",
        "booster_lastfm_custom_enabled": False,
        "booster_lastfm_title": "now playing",
        "booster_lastfm_footer": "",
        "booster_lastfm_image": "",
        "booster_lastfm_thumbnail_mode": "album",
        "embed_color": 0x111111
    }


def ensure_files():
    os.makedirs("data", exist_ok=True)
    defaults = {
        SETTINGS_FILE: {},
        WARNS_FILE: {},
        AUTOMOD_FILE: {"spam_tracker": {}},
        LASTFM_USERS_FILE: {},
        STICKY_FILE: {},
        SNIPE_FILE: {},
        NP_TRIGGERS_FILE: {}
    }
    for path, default_value in defaults.items():
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_value, f, indent=2)


def get_all_settings():
    return load_json(SETTINGS_FILE)


def get_guild_settings(guild_id: int):
    data = get_all_settings()
    gid = str(guild_id)
    defaults = default_guild_settings()

    if gid not in data:
        data[gid] = defaults
        save_json(SETTINGS_FILE, data)
    else:
        changed = False
        for k, v in defaults.items():
            if k not in data[gid]:
                data[gid][k] = v
                changed = True
        if changed:
            save_json(SETTINGS_FILE, data)

    return data[gid]


def update_guild_setting(guild_id: int, key: str, value):
    data = get_all_settings()
    gid = str(guild_id)
    if gid not in data:
        data[gid] = default_guild_settings()
    data[gid][key] = value
    save_json(SETTINGS_FILE, data)


def guild_color(guild_id: int):
    settings = get_guild_settings(guild_id)
    return settings.get("embed_color", 0xFF66C4)


def build_boost_message_embed(member: discord.Member):
    settings = get_guild_settings(member.guild.id)
    text = format_template(settings.get("boost_message", ""), member=member, guild=member.guild)
    title = settings.get("boost_embed_title", "Thank You for Boosting")
    footer = settings.get("boost_embed_footer", "").strip()
    image_url = settings.get("boost_embed_image", "").strip()
    thumb_mode = settings.get("boost_embed_thumbnail_mode", "avatar")

    embed = build_embed(title, guild_color(member.guild.id), text)

    if thumb_mode == "avatar":
        embed.set_thumbnail(url=member.display_avatar.url)
    elif thumb_mode == "server_icon" and member.guild.icon:
        embed.set_thumbnail(url=member.guild.icon.url)

    if image_url:
        embed.set_image(url=image_url)

    if footer:
        embed.set_footer(text=format_template(footer, member=member, guild=member.guild))

    return embed


def get_log_channel(guild: discord.Guild, setting_key: str):
    settings = get_guild_settings(guild.id)
    cid = settings.get(setting_key, 0)
    if not cid:
        return None
    return guild.get_channel(cid)


async def send_to_log(guild: discord.Guild, setting_key: str, embed: discord.Embed):
    channel = get_log_channel(guild, setting_key)
    if channel:
        await channel.send(embed=embed)


# -------------------------
# warnings
# -------------------------

def add_warn(guild_id: int, user_id: int, moderator_id: int, reason: str):
    data = load_json(WARNS_FILE)
    gid = str(guild_id)
    uid = str(user_id)

    if gid not in data:
        data[gid] = {}
    if uid not in data[gid]:
        data[gid][uid] = []

    data[gid][uid].append({
        "moderator_id": moderator_id,
        "reason": reason,
        "timestamp": utc_now_iso()
    })
    save_json(WARNS_FILE, data)


def get_warns(guild_id: int, user_id: int):
    return load_json(WARNS_FILE).get(str(guild_id), {}).get(str(user_id), [])


def clear_warns(guild_id: int, user_id: int):
    data = load_json(WARNS_FILE)
    gid = str(guild_id)
    uid = str(user_id)

    if gid in data and uid in data[gid]:
        del data[gid][uid]
        save_json(WARNS_FILE, data)
        return True
    return False


# -------------------------
# sticky messages
# -------------------------

def get_sticky_data():
    return load_json(STICKY_FILE)


def set_sticky(guild_id: int, channel_id: int, content: str):
    data = get_sticky_data()
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {}
    data[gid][str(channel_id)] = {
        "content": content,
        "last_message_id": 0
    }
    save_json(STICKY_FILE, data)


def clear_sticky(guild_id: int, channel_id: int):
    data = get_sticky_data()
    gid = str(guild_id)
    cid = str(channel_id)
    if gid in data and cid in data[gid]:
        del data[gid][cid]
        save_json(STICKY_FILE, data)
        return True
    return False


def get_sticky_for_channel(guild_id: int, channel_id: int):
    return get_sticky_data().get(str(guild_id), {}).get(str(channel_id))


def update_sticky_last_message(guild_id: int, channel_id: int, message_id: int):
    data = get_sticky_data()
    gid = str(guild_id)
    cid = str(channel_id)
    if gid in data and cid in data[gid]:
        data[gid][cid]["last_message_id"] = message_id
        save_json(STICKY_FILE, data)


# -------------------------
# snipes
# -------------------------

def save_snipe(guild_id: int, channel_id: int, content: dict):
    data = load_json(SNIPE_FILE)
    gid = str(guild_id)
    data.setdefault(gid, {})
    data[gid][str(channel_id)] = content
    save_json(SNIPE_FILE, data)


def get_snipe(guild_id: int, channel_id: int):
    return load_json(SNIPE_FILE).get(str(guild_id), {}).get(str(channel_id))


# -------------------------
# automod
# -------------------------

def get_automod_data():
    data = load_json(AUTOMOD_FILE)
    if "spam_tracker" not in data:
        data["spam_tracker"] = {}
        save_json(AUTOMOD_FILE, data)
    return data


def reset_user_spam(guild_id: int, user_id: int):
    data = get_automod_data()
    gid = str(guild_id)
    uid = str(user_id)
    if gid in data["spam_tracker"] and uid in data["spam_tracker"][gid]:
        del data["spam_tracker"][gid][uid]
        save_json(AUTOMOD_FILE, data)


def track_user_message(guild_id: int, user_id: int):
    data = get_automod_data()
    gid = str(guild_id)
    uid = str(user_id)
    now = datetime.now(timezone.utc).timestamp()

    data.setdefault("spam_tracker", {})
    data["spam_tracker"].setdefault(gid, {})
    data["spam_tracker"][gid].setdefault(uid, [])
    data["spam_tracker"][gid][uid].append(now)
    data["spam_tracker"][gid][uid] = [s for s in data["spam_tracker"][gid][uid] if now - s <= 8]
    save_json(AUTOMOD_FILE, data)
    return len(data["spam_tracker"][gid][uid])


# -------------------------
# last fm
# -------------------------

def get_lastfm_users():
    return load_json(LASTFM_USERS_FILE)


def set_lastfm_user(discord_user_id: int, username: str):
    data = get_lastfm_users()
    data[str(discord_user_id)] = username
    save_json(LASTFM_USERS_FILE, data)


def get_lastfm_user(discord_user_id: int):
    return get_lastfm_users().get(str(discord_user_id))


async def lastfm_request(params: dict):
    if not LASTFM_API_KEY:
        return None, "LASTFM_API_KEY is missing from Replit Secrets."

    params = params.copy()
    params["api_key"] = LASTFM_API_KEY
    params["format"] = "json"

    async with aiohttp.ClientSession() as session:
        async with session.get("https://ws.audioscrobbler.com/2.0/", params=params, timeout=20) as resp:
            if resp.status != 200:
                return None, f"Last.fm request failed with status {resp.status}."
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                return None, f"Last.fm response could not be parsed: {text[:200]}"
            return data, None


async def fetch_now_playing(username: str):
    data, err = await lastfm_request({
        "method": "user.getrecenttracks",
        "user": username,
        "limit": 1
    })
    if err:
        return None, err

    recenttracks = data.get("recenttracks", {}).get("track", [])
    if isinstance(recenttracks, dict):
        recenttracks = [recenttracks]

    if not recenttracks:
        return None, "No recent tracks found."

    track = recenttracks[0]
    is_now_playing = track.get("@attr", {}).get("nowplaying") == "true"

    return {
        "artist": track.get("artist", {}).get("#text", "Unknown Artist"),
        "name": track.get("name", "Unknown Track"),
        "album": track.get("album", {}).get("#text", "Unknown Album"),
        "url": track.get("url", ""),
        "image": track.get("image", [{}])[-1].get("#text", ""),
        "now_playing": is_now_playing
    }, None


async def fetch_top_artists(username: str, period: str = "7day"):
    data, err = await lastfm_request({
        "method": "user.gettopartists",
        "user": username,
        "period": period,
        "limit": 5
    })
    if err:
        return None, err

    artists = data.get("topartists", {}).get("artist", [])
    if not artists:
        return None, "No top artists found."

    return artists, None


async def fetch_user_info(username: str):
    data, err = await lastfm_request({
        "method": "user.getinfo",
        "user": username
    })
    if err:
        return None, err

    user = data.get("user")
    if not user:
        return None, "No Last.fm user info found."

    return {
        "playcount": user.get("playcount", "0"),
        "country": user.get("country", ""),
        "image": (user.get("image") or [{}])[-1].get("#text", "")
    }, None


async def fetch_track_info(artist: str, track: str, username: str):
    data, err = await lastfm_request({
        "method": "track.getInfo",
        "artist": artist,
        "track": track,
        "username": username,
        "autocorrect": 1
    })
    if err:
        return None, err

    track_data = data.get("track")
    if not track_data:
        return None, "No track info found."

    album = track_data.get("album", {})
    return {
        "userplaycount": track_data.get("userplaycount", "0"),
        "listeners": track_data.get("listeners", "0"),
        "playcount": track_data.get("playcount", "0"),
        "album_image": (album.get("image") or [{}])[-1].get("#text", "")
    }, None



def build_regular_lastfm_embed(guild_id: int, username: str, track: dict, user_info: dict | None = None, track_info: dict | None = None):
    title = "now playing" if track["now_playing"] else "recent track"
    embed = build_embed(title, guild_color(guild_id))
    embed.description = (
        f"**{track['name']}**\\n"
        f"by **{track['artist']}**\\n"
        f"from **{track['album']}**"
    )

    scrobbles = track_info.get("userplaycount", "0") if track_info else "0"
    total_scrobbles = user_info.get("playcount", "0") if user_info else "0"

    embed.add_field(name="account", value=username, inline=True)
    embed.add_field(name="track scrobbles", value=scrobbles, inline=True)
    embed.add_field(name="total scrobbles", value=total_scrobbles, inline=True)

    if track["url"]:
        embed.add_field(name="link", value=f"[open track]({track['url']})", inline=False)

    thumb = ""
    if track_info and track_info.get("album_image"):
        thumb = track_info["album_image"]
    elif track.get("image"):
        thumb = track["image"]

    if thumb:
        embed.set_thumbnail(url=thumb)

    embed.set_footer(text="encore fm")
    return embed


def build_booster_lastfm_embed(member: discord.Member, username: str, track: dict, user_info: dict | None = None, track_info: dict | None = None):
    settings = get_guild_settings(member.guild.id)
    title_template = settings.get("booster_lastfm_title", "now playing")
    footer_template = settings.get("booster_lastfm_footer", "")
    image_url = settings.get("booster_lastfm_image", "").strip()
    thumb_mode = settings.get("booster_lastfm_thumbnail_mode", "album")

    title = format_template(title_template, member=member, guild=member.guild)
    embed = build_embed(title, guild_color(member.guild.id))
    embed.description = (
        f"**[{track['name']}]({track['url']})**\\n"
        f"by **{track['artist']}**\\n"
        f"from **{track['album']}**"
    )

    embed.add_field(name="last.fm", value=username, inline=True)
    embed.add_field(name="member", value=member.mention, inline=True)
    embed.add_field(name="track scrobbles", value=(track_info.get("userplaycount", "0") if track_info else "0"), inline=True)

    if user_info:
        embed.add_field(name="total scrobbles", value=user_info.get("playcount", "0"), inline=True)

    if thumb_mode == "album":
        album_image = track_info.get("album_image", "") if track_info else ""
        if album_image:
            embed.set_thumbnail(url=album_image)
        elif track.get("image"):
            embed.set_thumbnail(url=track["image"])
    elif thumb_mode == "avatar":
        embed.set_thumbnail(url=member.display_avatar.url)
    elif thumb_mode == "server_icon" and member.guild.icon:
        embed.set_thumbnail(url=member.guild.icon.url)

    if image_url:
        embed.set_image(url=image_url)

    if footer_template.strip():
        embed.set_footer(text=format_template(footer_template, member=member, guild=member.guild))
    else:
        embed.set_footer(text=f"booster perk • {member.guild.name}")

    return embed


# -------------------------
# np triggers
# -------------------------

def get_np_triggers():
    return load_json(NP_TRIGGERS_FILE)


def set_np_trigger(guild_id: int, user_id: int, trigger: str):
    data = get_np_triggers()
    gid = str(guild_id)
    uid = str(user_id)

    if gid not in data:
        data[gid] = {}

    data[gid][uid] = trigger.strip().lower()
    save_json(NP_TRIGGERS_FILE, data)


def clear_np_trigger(guild_id: int, user_id: int):
    data = get_np_triggers()
    gid = str(guild_id)
    uid = str(user_id)

    if gid in data and uid in data[gid]:
        del data[gid][uid]
        if not data[gid]:
            del data[gid]
        save_json(NP_TRIGGERS_FILE, data)
        return True
    return False


def get_np_trigger(guild_id: int, user_id: int):
    return get_np_triggers().get(str(guild_id), {}).get(str(user_id))


async def send_member_np_message(channel: discord.abc.Messageable, member: discord.Member):
    username = get_lastfm_user(member.id)
    if not username:
        return False, f"{member.mention} has not set a Last.fm username yet."

    track, err = await fetch_now_playing(username)
    if err:
        return False, err

    user_info, _ = await fetch_user_info(username)
    track_info, _ = await fetch_track_info(track["artist"], track["name"], username)

    settings = get_guild_settings(member.guild.id)
    booster_role_id = settings.get("booster_role_id", 0)
    is_booster = (
        settings.get("booster_lastfm_custom_enabled", False)
        and booster_role_id
        and any(role.id == booster_role_id for role in member.roles)
    )

    if is_booster:
        embed = build_booster_lastfm_embed(member, username, track, user_info, track_info)
    else:
        embed = build_regular_lastfm_embed(member.guild.id, username, track, user_info, track_info)

    await channel.send(embed=embed)
    return True, None


# -------------------------
# role sync helpers
# -------------------------

async def sync_booster_role_for_member(member: discord.Member):
    settings = get_guild_settings(member.guild.id)
    booster_role_id = settings.get("booster_role_id", 0)

    if not booster_role_id:
        return

    booster_role = member.guild.get_role(booster_role_id)
    if booster_role is None:
        return

    is_boosting = member.premium_since is not None
    has_role = booster_role in member.roles

    try:
        if is_boosting and not has_role:
            await member.add_roles(booster_role, reason="Started boosting server")
        elif not is_boosting and has_role:
            await member.remove_roles(booster_role, reason="Stopped boosting server")
    except Exception:
        pass


async def sync_all_boosters(guild: discord.Guild):
    for member in guild.members:
        await sync_booster_role_for_member(member)


# -------------------------
# events
# -------------------------

@bot.event
async def on_ready():
    ensure_files()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Sync failed: {e}")

    if not cleanup_spam_tracker.is_running():
        cleanup_spam_tracker.start()

    print(f"Logged in as {bot.user} ({bot.user.id})")


@bot.event
async def on_member_join(member: discord.Member):
    settings = get_guild_settings(member.guild.id)

    member_role_id = settings.get("member_role_id", 0)
    if member_role_id:
        role = member.guild.get_role(member_role_id)
        if role:
            try:
                await member.add_roles(role, reason="Auto member role")
            except Exception:
                pass

    if settings.get("welcome_enabled", False):
        channel = get_log_channel(member.guild, "welcome_channel_id")
        if channel:
            text = format_template(
                settings.get("welcome_message", ""),
                member=member,
                guild=member.guild
            )
            embed = build_embed("Welcome", guild_color(member.guild.id), text)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    embed = build_embed("Member Joined", guild_color(member.guild.id))
    embed.add_field(name="Member", value=f"{member.mention} ({member.id})", inline=False)
    embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_to_log(member.guild, "join_leave_log_channel_id", embed)

    await sync_booster_role_for_member(member)


@bot.event
async def on_member_remove(member: discord.Member):
    settings = get_guild_settings(member.guild.id)

    if settings.get("goodbye_enabled", False):
        channel = get_log_channel(member.guild, "welcome_channel_id")
        if channel:
            text = format_template(
                settings.get("goodbye_message", ""),
                member=member,
                guild=member.guild
            )
            embed = build_embed("Goodbye", guild_color(member.guild.id), text)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    embed = build_embed("Member Left", guild_color(member.guild.id))
    embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
    await send_to_log(member.guild, "join_leave_log_channel_id", embed)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    before_boost = before.premium_since is not None
    after_boost = after.premium_since is not None

    await sync_booster_role_for_member(after)

    if before_boost != after_boost:
        if after_boost:
            embed = build_embed("Server Boost Started", guild_color(after.guild.id))
            embed.add_field(name="Member", value=f"{after.mention} ({after.id})", inline=False)
            embed.set_thumbnail(url=after.display_avatar.url)
            await send_to_log(after.guild, "boost_log_channel_id", embed)

            settings = get_guild_settings(after.guild.id)
            if settings.get("boost_message_enabled", False):
                channel = get_log_channel(after.guild, "boost_log_channel_id") or get_log_channel(after.guild, "welcome_channel_id")
                if channel:
                    msg_embed = build_boost_message_embed(after)
                    await channel.send(embed=msg_embed)
        else:
            embed = build_embed("Server Boost Ended", guild_color(after.guild.id))
            embed.add_field(name="Member", value=f"{after} ({after.id})", inline=False)
            await send_to_log(after.guild, "boost_log_channel_id", embed)


@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild or message.author.bot:
        return

    save_snipe(message.guild.id, message.channel.id, {
        "type": "delete",
        "author": str(message.author),
        "author_id": message.author.id,
        "content": message.content or "*No text content*",
        "timestamp": utc_now_iso()
    })

    embed = build_embed("Message Deleted", guild_color(message.guild.id), f"Deleted in {message.channel.mention}")
    embed.add_field(name="Author", value=f"{message.author} ({message.author.id})", inline=False)
    embed.add_field(name="Content", value=truncate_text(message.content or "*No text content*"), inline=False)

    if message.attachments:
        attachments = "\n".join(a.url for a in message.attachments[:5])
        embed.add_field(name="Attachments", value=attachments, inline=False)

    await send_to_log(message.guild, "delete_log_channel_id", embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or before.author.bot:
        return
    if before.content == after.content:
        return

    save_snipe(before.guild.id, before.channel.id, {
        "type": "edit",
        "author": str(before.author),
        "author_id": before.author.id,
        "before": before.content or "*No text content*",
        "after": after.content or "*No text content*",
        "timestamp": utc_now_iso()
    })

    embed = build_embed("Message Edited", guild_color(before.guild.id), f"Edited in {before.channel.mention}")
    embed.add_field(name="Author", value=f"{before.author} ({before.author.id})", inline=False)
    embed.add_field(name="Before", value=truncate_text(before.content or "*No text content*"), inline=False)
    embed.add_field(name="After", value=truncate_text(after.content or "*No text content*"), inline=False)
    embed.add_field(name="Jump", value=f"[Go to message]({after.jump_url})", inline=False)
    await send_to_log(before.guild, "edit_log_channel_id", embed)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    settings = get_guild_settings(message.guild.id)

    if settings.get("anti_invite_enabled", False):
        lowered = message.content.lower()
        if "discord.gg/" in lowered or "discord.com/invite/" in lowered:
            if not message.author.guild_permissions.manage_messages:
                try:
                    await message.delete()
                except Exception:
                    pass
                embed = build_embed("AutoMod: Invite Blocked", guild_color(message.guild.id))
                embed.add_field(name="Member", value=f"{message.author} ({message.author.id})", inline=False)
                embed.add_field(name="Channel", value=message.channel.mention, inline=False)
                await send_to_log(message.guild, "mod_log_channel_id", embed)
                return

    if settings.get("anti_link_enabled", False):
        lowered = message.content.lower()
        if ("http://" in lowered or "https://" in lowered or "www." in lowered) and "discord.gg/" not in lowered and "discord.com/invite/" not in lowered:
            if not message.author.guild_permissions.manage_messages:
                try:
                    await message.delete()
                except Exception:
                    pass
                embed = build_embed("AutoMod: Link Blocked", guild_color(message.guild.id))
                embed.add_field(name="Member", value=f"{message.author} ({message.author.id})", inline=False)
                embed.add_field(name="Channel", value=message.channel.mention, inline=False)
                await send_to_log(message.guild, "mod_log_channel_id", embed)
                return

    if settings.get("anti_spam_enabled", False) and not message.author.guild_permissions.manage_messages:
        count = track_user_message(message.guild.id, message.author.id)
        if count >= 6:
            try:
                await message.author.timeout(timedelta(minutes=2), reason="AutoMod spam protection")
            except Exception:
                pass
            embed = build_embed("AutoMod: Spam Timeout", guild_color(message.guild.id))
            embed.add_field(name="Member", value=f"{message.author} ({message.author.id})", inline=False)
            embed.add_field(name="Channel", value=message.channel.mention, inline=False)
            embed.add_field(name="Action", value="Timed out for 2 minutes", inline=False)
            await send_to_log(message.guild, "mod_log_channel_id", embed)
            reset_user_spam(message.guild.id, message.author.id)
            return

    trigger = get_np_trigger(message.guild.id, message.author.id)
    if trigger and message.content.strip().lower() == trigger:
        success, error = await send_member_np_message(message.channel, message.author)
        if not success and error:
            await message.channel.send(error)
        return

    sticky = get_sticky_for_channel(message.guild.id, message.channel.id)
    if sticky:
        old_id = sticky.get("last_message_id", 0)
        if old_id:
            try:
                old_msg = await message.channel.fetch_message(old_id)
                await old_msg.delete()
            except Exception:
                pass

        sent = await message.channel.send(sticky["content"])
        update_sticky_last_message(message.guild.id, message.channel.id, sent.id)

    await bot.process_commands(message)


@tasks.loop(minutes=10)
async def cleanup_spam_tracker():
    data = get_automod_data()
    now = datetime.now(timezone.utc).timestamp()
    changed = False

    for gid, users in list(data.get("spam_tracker", {}).items()):
        for uid, stamps in list(users.items()):
            new_stamps = [s for s in stamps if now - s <= 8]
            if new_stamps:
                data["spam_tracker"][gid][uid] = new_stamps
            else:
                del data["spam_tracker"][gid][uid]
                changed = True

        if not data["spam_tracker"][gid]:
            del data["spam_tracker"][gid]
            changed = True

    if changed:
        save_json(AUTOMOD_FILE, data)


# -------------------------
# checks
# -------------------------

def admin_only():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


# -------------------------
# setup commands
# -------------------------

@bot.tree.command(name="setmodlog", description="Set the moderation log channel.")
@admin_only()
async def setmodlog(interaction: discord.Interaction, channel: discord.TextChannel):
    update_guild_setting(interaction.guild.id, "mod_log_channel_id", channel.id)
    await interaction.response.send_message(f"✅ Mod logs set to {channel.mention}", ephemeral=True)


@bot.tree.command(name="setdeletelog", description="Set the deleted message log channel.")
@admin_only()
async def setdeletelog(interaction: discord.Interaction, channel: discord.TextChannel):
    update_guild_setting(interaction.guild.id, "delete_log_channel_id", channel.id)
    await interaction.response.send_message(f"✅ Delete logs set to {channel.mention}", ephemeral=True)


@bot.tree.command(name="seteditlog", description="Set the edited message log channel.")
@admin_only()
async def seteditlog(interaction: discord.Interaction, channel: discord.TextChannel):
    update_guild_setting(interaction.guild.id, "edit_log_channel_id", channel.id)
    await interaction.response.send_message(f"✅ Edit logs set to {channel.mention}", ephemeral=True)


@bot.tree.command(name="setjoinlog", description="Set the join/leave log channel.")
@admin_only()
async def setjoinlog(interaction: discord.Interaction, channel: discord.TextChannel):
    update_guild_setting(interaction.guild.id, "join_leave_log_channel_id", channel.id)
    await interaction.response.send_message(f"✅ Join/leave logs set to {channel.mention}", ephemeral=True)


@bot.tree.command(name="setboostlog", description="Set the boost log channel.")
@admin_only()
async def setboostlog(interaction: discord.Interaction, channel: discord.TextChannel):
    update_guild_setting(interaction.guild.id, "boost_log_channel_id", channel.id)
    await interaction.response.send_message(f"✅ Boost logs set to {channel.mention}", ephemeral=True)


@bot.tree.command(name="setwelcomechannel", description="Set the welcome and goodbye channel.")
@admin_only()
async def setwelcomechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    update_guild_setting(interaction.guild.id, "welcome_channel_id", channel.id)
    await interaction.response.send_message(f"✅ Welcome/goodbye channel set to {channel.mention}", ephemeral=True)


@bot.tree.command(name="togglewelcome", description="Turn welcome messages on or off.")
@admin_only()
async def togglewelcome(interaction: discord.Interaction, enabled: bool):
    update_guild_setting(interaction.guild.id, "welcome_enabled", enabled)
    await interaction.response.send_message(f"✅ Welcome messages {'enabled' if enabled else 'disabled'}", ephemeral=True)


@bot.tree.command(name="togglegoodbye", description="Turn goodbye messages on or off.")
@admin_only()
async def togglegoodbye(interaction: discord.Interaction, enabled: bool):
    update_guild_setting(interaction.guild.id, "goodbye_enabled", enabled)
    await interaction.response.send_message(f"✅ Goodbye messages {'enabled' if enabled else 'disabled'}", ephemeral=True)


@bot.tree.command(name="toggleboostmsg", description="Turn boost thank-you messages on or off.")
@admin_only()
async def toggleboostmsg(interaction: discord.Interaction, enabled: bool):
    update_guild_setting(interaction.guild.id, "boost_message_enabled", enabled)
    await interaction.response.send_message(f"✅ Boost thank-you messages {'enabled' if enabled else 'disabled'}", ephemeral=True)


@bot.tree.command(name="setwelcomemsg", description="Set the welcome embed message.")
@admin_only()
async def setwelcomemsg(interaction: discord.Interaction, message: str):
    update_guild_setting(interaction.guild.id, "welcome_message", message)
    await interaction.response.send_message("✅ Welcome message updated.", ephemeral=True)


@bot.tree.command(name="setgoodbyemsg", description="Set the goodbye embed message.")
@admin_only()
async def setgoodbyemsg(interaction: discord.Interaction, message: str):
    update_guild_setting(interaction.guild.id, "goodbye_message", message)
    await interaction.response.send_message("✅ Goodbye message updated.", ephemeral=True)


@bot.tree.command(name="setboostmsg", description="Set the boost thank-you embed message.")
@admin_only()
async def setboostmsg(interaction: discord.Interaction, message: str):
    update_guild_setting(interaction.guild.id, "boost_message", message)
    await interaction.response.send_message("✅ Boost message updated.", ephemeral=True)


@bot.tree.command(name="setboosttitle", description="Set the boost embed title.")
@admin_only()
async def setboosttitle(interaction: discord.Interaction, title: str):
    update_guild_setting(interaction.guild.id, "boost_embed_title", title)
    await interaction.response.send_message("✅ Boost embed title updated.", ephemeral=True)


@bot.tree.command(name="setboostfooter", description="Set the boost embed footer.")
@admin_only()
async def setboostfooter(interaction: discord.Interaction, footer: str):
    update_guild_setting(interaction.guild.id, "boost_embed_footer", footer)
    await interaction.response.send_message("✅ Boost embed footer updated.", ephemeral=True)


@bot.tree.command(name="setboostimage", description="Set the boost embed large image URL.")
@admin_only()
async def setboostimage(interaction: discord.Interaction, image_url: str):
    update_guild_setting(interaction.guild.id, "boost_embed_image", image_url)
    await interaction.response.send_message("✅ Boost embed image updated.", ephemeral=True)


@bot.tree.command(name="setboostthumb", description="Set the boost embed thumbnail mode.")
@admin_only()
@app_commands.choices(mode=[
    app_commands.Choice(name="avatar", value="avatar"),
    app_commands.Choice(name="server_icon", value="server_icon"),
    app_commands.Choice(name="none", value="none")
])
async def setboostthumb(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    update_guild_setting(interaction.guild.id, "boost_embed_thumbnail_mode", mode.value)
    await interaction.response.send_message(f"✅ Boost thumbnail mode set to **{mode.value}**.", ephemeral=True)


@bot.tree.command(name="previewboost", description="Preview the current boost embed.")
@admin_only()
async def previewboost(interaction: discord.Interaction):
    embed = build_boost_message_embed(interaction.user)
    embed.set_footer(text=(embed.footer.text or "") + (" • preview" if embed.footer.text else "preview"))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="previewmessages", description="Preview the welcome, goodbye, and boost templates.")
@admin_only()
async def previewmessages(interaction: discord.Interaction):
    settings = get_guild_settings(interaction.guild.id)
    fake = interaction.user
    embed = build_embed("Template Preview", guild_color(interaction.guild.id))
    embed.add_field(name="Welcome", value=format_template(settings["welcome_message"], fake, interaction.guild), inline=False)
    embed.add_field(name="Goodbye", value=format_template(settings["goodbye_message"], fake, interaction.guild), inline=False)
    embed.add_field(name="Boost", value=format_template(settings["boost_message"], fake, interaction.guild), inline=False)
    embed.set_footer(text="Variables: {mention} {user} {server} {member_count}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setboosterrole", description="Set the role given to server boosters.")
@admin_only()
async def setboosterrole(interaction: discord.Interaction, role: discord.Role):
    update_guild_setting(interaction.guild.id, "booster_role_id", role.id)
    await interaction.response.send_message(f"✅ Booster role set to {role.mention}", ephemeral=True)


@bot.tree.command(name="setmemberrole", description="Set the auto role for new members.")
@admin_only()
async def setmemberrole(interaction: discord.Interaction, role: discord.Role):
    update_guild_setting(interaction.guild.id, "member_role_id", role.id)
    await interaction.response.send_message(f"✅ Member role set to {role.mention}", ephemeral=True)


@bot.tree.command(name="setjailrole", description="Set the jail role.")
@admin_only()
async def setjailrole(interaction: discord.Interaction, role: discord.Role):
    update_guild_setting(interaction.guild.id, "jail_role_id", role.id)
    await interaction.response.send_message(f"✅ Jail role set to {role.mention}", ephemeral=True)


@bot.tree.command(name="boosterrefresh", description="Refresh booster roles for everyone.")
@admin_only()
async def boosterrefresh(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await sync_all_boosters(interaction.guild)
    await interaction.followup.send("✅ Refreshed booster roles.", ephemeral=True)


@bot.tree.command(name="automod", description="Toggle anti-link, anti-invite, or anti-spam.")
@admin_only()
@app_commands.describe(feature="Choose a feature", enabled="Turn it on or off")
@app_commands.choices(feature=[
    app_commands.Choice(name="anti_link", value="anti_link_enabled"),
    app_commands.Choice(name="anti_invite", value="anti_invite_enabled"),
    app_commands.Choice(name="anti_spam", value="anti_spam_enabled")
])
async def automod(interaction: discord.Interaction, feature: app_commands.Choice[str], enabled: bool):
    update_guild_setting(interaction.guild.id, feature.value, enabled)
    await interaction.response.send_message(f"✅ {feature.name} {'enabled' if enabled else 'disabled'}", ephemeral=True)


@bot.tree.command(name="setcolor", description="Set embed color with a hex code like FF66C4.")
@admin_only()
async def setcolor(interaction: discord.Interaction, hex_code: str):
    hex_code = hex_code.strip().replace("#", "")
    try:
        color_value = int(hex_code, 16)
    except ValueError:
        await interaction.response.send_message("Invalid hex code.", ephemeral=True)
        return

    update_guild_setting(interaction.guild.id, "embed_color", color_value)
    await interaction.response.send_message(f"✅ Embed color updated to #{hex_code.upper()}", ephemeral=True)


@bot.tree.command(name="config", description="View the current config for this server.")
@admin_only()
async def config(interaction: discord.Interaction):
    settings = get_guild_settings(interaction.guild.id)
    embed = build_embed("Server Config", guild_color(interaction.guild.id))
    for key, value in settings.items():
        embed.add_field(name=key, value=str(value), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(name="toggleboosterfm", description="Turn custom booster Last.fm embeds on or off.")
@admin_only()
async def toggleboosterfm(interaction: discord.Interaction, enabled: bool):
    update_guild_setting(interaction.guild.id, "booster_lastfm_custom_enabled", enabled)
    await interaction.response.send_message(f"✅ Booster Last.fm custom embeds {'enabled' if enabled else 'disabled'}", ephemeral=True)


@bot.tree.command(name="setboosterfmtitle", description="Set the custom Last.fm embed title for boosters.")
@admin_only()
async def setboosterfmtitle(interaction: discord.Interaction, title: str):
    update_guild_setting(interaction.guild.id, "booster_lastfm_title", title)
    await interaction.response.send_message("✅ Booster Last.fm title updated.", ephemeral=True)


@bot.tree.command(name="setboosterfmfooter", description="Set the custom Last.fm embed footer for boosters.")
@admin_only()
async def setboosterfmfooter(interaction: discord.Interaction, footer: str):
    update_guild_setting(interaction.guild.id, "booster_lastfm_footer", footer)
    await interaction.response.send_message("✅ Booster Last.fm footer updated.", ephemeral=True)


@bot.tree.command(name="setboosterfmimage", description="Set the custom Last.fm embed large image for boosters.")
@admin_only()
async def setboosterfmimage(interaction: discord.Interaction, image_url: str):
    update_guild_setting(interaction.guild.id, "booster_lastfm_image", image_url)
    await interaction.response.send_message("✅ Booster Last.fm image updated.", ephemeral=True)


@bot.tree.command(name="setboosterfmthumb", description="Set the thumbnail mode for booster Last.fm embeds.")
@admin_only()
@app_commands.choices(mode=[
    app_commands.Choice(name="album", value="album"),
    app_commands.Choice(name="avatar", value="avatar"),
    app_commands.Choice(name="server_icon", value="server_icon"),
    app_commands.Choice(name="none", value="none")
])
async def setboosterfmthumb(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    update_guild_setting(interaction.guild.id, "booster_lastfm_thumbnail_mode", mode.value)
    await interaction.response.send_message(f"✅ Booster Last.fm thumbnail mode set to **{mode.value}**.", ephemeral=True)


@bot.tree.command(name="previewboosterfm", description="Preview the booster Last.fm embed using your current track.")
@admin_only()
async def previewboosterfm(interaction: discord.Interaction):
    username = get_lastfm_user(interaction.user.id)
    if not username:
        await interaction.response.send_message("Set your Last.fm first with /setfm.", ephemeral=True)
        return

    track, err = await fetch_now_playing(username)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    user_info, _ = await fetch_user_info(username)
    track_info, _ = await fetch_track_info(track["artist"], track["name"], username)

    embed = build_booster_lastfm_embed(interaction.user, username, track, user_info, track_info)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="sendembed", description="Send a custom embed to a channel.")
@admin_only()
async def sendembed(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    description: str,
    footer: str | None = None,
    image_url: str | None = None,
    thumbnail_url: str | None = None
):
    embed = build_embed(title, guild_color(interaction.guild.id), description)
    if footer:
        embed.set_footer(text=footer)
    if image_url:
        embed.set_image(url=image_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Sent embed to {channel.mention}", ephemeral=True)


@bot.tree.command(name="bleedtheme", description="Set the bot to a darker bleed-style theme.")
@admin_only()
async def bleedtheme(interaction: discord.Interaction):
    update_guild_setting(interaction.guild.id, "embed_color", 0x111111)
    await interaction.response.send_message("✅ Bleed-style dark embed theme applied.", ephemeral=True)



@bot.tree.command(name="setnptrigger", description="Set your personal NP text trigger, like naileafm.")
async def setnptrigger(interaction: discord.Interaction, trigger: str):
    trigger = trigger.strip().lower()

    if not trigger:
        await interaction.response.send_message("Give me a trigger to save.", ephemeral=True)
        return

    if len(trigger) > 32:
        await interaction.response.send_message("Keep it under 32 characters.", ephemeral=True)
        return

    if " " in trigger:
        await interaction.response.send_message("Use one word only, no spaces.", ephemeral=True)
        return

    set_np_trigger(interaction.guild.id, interaction.user.id, trigger)
    await interaction.response.send_message(
        f"✅ Your NP trigger is now **{trigger}**. Sending that in chat will post your current track.",
        ephemeral=True
    )


@bot.tree.command(name="mynptrigger", description="View your saved NP trigger.")
async def mynptrigger(interaction: discord.Interaction):
    trigger = get_np_trigger(interaction.guild.id, interaction.user.id)
    if not trigger:
        await interaction.response.send_message("You do not have an NP trigger set yet.", ephemeral=True)
        return

    await interaction.response.send_message(f"Your NP trigger is **{trigger}**.", ephemeral=True)


@bot.tree.command(name="clearnptrigger", description="Clear your saved NP trigger.")
async def clearnptrigger(interaction: discord.Interaction):
    removed = clear_np_trigger(interaction.guild.id, interaction.user.id)
    if not removed:
        await interaction.response.send_message("You do not have an NP trigger set.", ephemeral=True)
        return

    await interaction.response.send_message("✅ Your NP trigger was removed.", ephemeral=True)


# -------------------------
# moderation commands
# -------------------------

@bot.tree.command(name="ban", description="Ban a member.")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"✅ Banned {member.mention}\nReason: {reason}")
        embed = build_embed("Member Banned", guild_color(interaction.guild.id))
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await send_to_log(interaction.guild, "mod_log_channel_id", embed)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="kick", description="Kick a member.")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"✅ Kicked {member.mention}\nReason: {reason}")
        embed = build_embed("Member Kicked", guild_color(interaction.guild.id))
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await send_to_log(interaction.guild, "mod_log_channel_id", embed)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="timeout", description="Timeout a member.")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    try:
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await interaction.response.send_message(f"✅ Timed out {member.mention} for {minutes} minute(s)\nReason: {reason}")
        embed = build_embed("Member Timed Out", guild_color(interaction.guild.id))
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Duration", value=f"{minutes} minute(s)", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        await send_to_log(interaction.guild, "mod_log_channel_id", embed)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="untimeout", description="Remove a timeout.")
async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    try:
        await member.timeout(None, reason=reason)
        await interaction.response.send_message(f"✅ Removed timeout from {member.mention}")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="warn", description="Warn a member.")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    add_warn(interaction.guild.id, member.id, interaction.user.id, reason)
    total = len(get_warns(interaction.guild.id, member.id))
    await interaction.response.send_message(f"⚠️ Warned {member.mention}\nReason: {reason}\nTotal warns: {total}")
    embed = build_embed("Member Warned", guild_color(interaction.guild.id))
    embed.add_field(name="Member", value=f"{member.mention} ({member.id})", inline=False)
    embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warns", value=str(total), inline=False)
    await send_to_log(interaction.guild, "mod_log_channel_id", embed)


@bot.tree.command(name="warnings", description="View a member's warnings.")
async def warnings(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    warns = get_warns(interaction.guild.id, member.id)
    if not warns:
        await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
        return
    embed = build_embed(f"Warnings for {member}", guild_color(interaction.guild.id))
    for i, warn in enumerate(warns[:10], start=1):
        embed.add_field(name=f"Warn {i}", value=f"Moderator ID: {warn['moderator_id']}\nReason: {warn['reason']}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member.")
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need Administrator for this.", ephemeral=True)
        return
    removed = clear_warns(interaction.guild.id, member.id)
    if not removed:
        await interaction.response.send_message(f"{member.mention} has no warnings to clear.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Cleared warnings for {member.mention}")


@bot.tree.command(name="purge", description="Delete recent messages.")
async def purge(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=max(1, min(amount, 100)))
    await interaction.followup.send(f"✅ Deleted {len(deleted)} message(s).", ephemeral=True)


@bot.tree.command(name="jail", description="Jail a member with the configured jail role.")
async def jail(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    jail_role_id = get_guild_settings(interaction.guild.id).get("jail_role_id", 0)
    role = interaction.guild.get_role(jail_role_id) if jail_role_id else None
    if not role:
        await interaction.response.send_message("Set a jail role first with /setjailrole.", ephemeral=True)
        return
    try:
        await member.add_roles(role, reason=reason)
        await interaction.response.send_message(f"🔒 Jailed {member.mention}\nReason: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="unjail", description="Remove the jail role from a member.")
async def unjail(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    jail_role_id = get_guild_settings(interaction.guild.id).get("jail_role_id", 0)
    role = interaction.guild.get_role(jail_role_id) if jail_role_id else None
    if not role:
        await interaction.response.send_message("Set a jail role first with /setjailrole.", ephemeral=True)
        return
    try:
        await member.remove_roles(role)
        await interaction.response.send_message(f"✅ Unjailed {member.mention}")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="lock", description="Lock the current channel.")
async def lock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔒 Channel locked.")


@bot.tree.command(name="unlock", description="Unlock the current channel.")
async def unlock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔓 Channel unlocked.")


@bot.tree.command(name="slowmode", description="Set slowmode for the current channel.")
async def slowmode(interaction: discord.Interaction, seconds: int):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You do not have permission to use this.", ephemeral=True)
        return
    await interaction.channel.edit(slowmode_delay=max(0, min(seconds, 21600)))
    await interaction.response.send_message(f"⏱️ Slowmode set to {seconds} second(s).")


@bot.tree.command(name="snipe", description="Show the last deleted or edited message in this channel.")
async def snipe(interaction: discord.Interaction):
    data = get_snipe(interaction.guild.id, interaction.channel.id)
    if not data:
        await interaction.response.send_message("Nothing to snipe here.", ephemeral=True)
        return

    embed = build_embed("Snipe", guild_color(interaction.guild.id))
    embed.add_field(name="Author", value=f"{data['author']} ({data['author_id']})", inline=False)
    embed.add_field(name="Type", value=data["type"], inline=False)

    if data["type"] == "delete":
        embed.add_field(name="Content", value=truncate_text(data["content"]), inline=False)
    else:
        embed.add_field(name="Before", value=truncate_text(data["before"]), inline=False)
        embed.add_field(name="After", value=truncate_text(data["after"]), inline=False)

    embed.set_footer(text=data["timestamp"])
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setsticky", description="Set a sticky message for this channel.")
@admin_only()
async def setsticky(interaction: discord.Interaction, message: str):
    set_sticky(interaction.guild.id, interaction.channel.id, message)
    await interaction.response.send_message("✅ Sticky message set for this channel.", ephemeral=True)


@bot.tree.command(name="clearsticky", description="Clear the sticky message for this channel.")
@admin_only()
async def clearsticky_cmd(interaction: discord.Interaction):
    removed = clear_sticky(interaction.guild.id, interaction.channel.id)
    if not removed:
        await interaction.response.send_message("No sticky message set here.", ephemeral=True)
        return
    await interaction.response.send_message("✅ Sticky message cleared.", ephemeral=True)


# -------------------------
# info commands
# -------------------------

@bot.tree.command(name="userinfo", description="Show info about a member.")
async def userinfo(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    embed = build_embed(f"User Info: {member}", guild_color(interaction.guild.id))
    embed.add_field(name="ID", value=str(member.id), inline=False)
    embed.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:F>", inline=False)
    embed.add_field(name="Created", value=f"<t:{int(member.created_at.timestamp())}:F>", inline=False)
    embed.add_field(name="Boosting", value="Yes" if member.premium_since else "No", inline=False)
    roles = [r.mention for r in member.roles[1:]][:15]
    embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="Show server info.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = build_embed(f"Server Info: {guild.name}", guild_color(guild.id))
    embed.add_field(name="Members", value=str(guild.member_count), inline=False)
    embed.add_field(name="Boosts", value=str(guild.premium_subscription_count or 0), inline=False)
    embed.add_field(name="Boost Tier", value=str(guild.premium_tier), inline=False)
    embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=False)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="Show a user's avatar.")
async def avatar(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    embed = build_embed(f"{member}'s Avatar", guild_color(interaction.guild.id))
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="membercount", description="Show the server member count.")
async def membercount(interaction: discord.Interaction):
    await interaction.response.send_message(f"**{interaction.guild.name}** has **{interaction.guild.member_count}** members.")


@bot.tree.command(name="boosters", description="Show current boosters.")
async def boosters(interaction: discord.Interaction):
    boosters = [m.mention for m in interaction.guild.members if m.premium_since]
    if not boosters:
        await interaction.response.send_message("No active boosters right now.")
        return
    embed = build_embed("Current Boosters", guild_color(interaction.guild.id))
    embed.description = "\n".join(boosters[:30])
    if len(boosters) > 30:
        embed.set_footer(text=f"Showing 30 of {len(boosters)} boosters")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stafflist", description="Show members with Manage Server or Administrator.")
async def stafflist(interaction: discord.Interaction):
    staff = [m.mention for m in interaction.guild.members if m.guild_permissions.manage_guild or m.guild_permissions.administrator]
    if not staff:
        await interaction.response.send_message("No staff found.")
        return
    embed = build_embed("Staff List", guild_color(interaction.guild.id))
    embed.description = "\n".join(staff[:40])
    await interaction.response.send_message(embed=embed)


# -------------------------
# last.fm commands
# -------------------------

@bot.tree.command(name="setfm", description="Save your Last.fm username.")
async def setfm(interaction: discord.Interaction, username: str):
    set_lastfm_user(interaction.user.id, username)
    await interaction.response.send_message(f"✅ Saved your Last.fm as **{username}**.", ephemeral=True)


@bot.tree.command(name="fm", description="Show your or someone else's current Last.fm track.")
async def fm(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    username = get_lastfm_user(member.id)
    if not username:
        await interaction.response.send_message(f"{member.mention} has not set a Last.fm username yet.", ephemeral=True)
        return

    track, err = await fetch_now_playing(username)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    title = "Now Playing" if track["now_playing"] else "Most Recent Track"
    embed = build_embed(f"{title} — {username}", guild_color(interaction.guild.id))
    embed.add_field(name="Track", value=track["name"], inline=False)
    embed.add_field(name="Artist", value=track["artist"], inline=False)
    embed.add_field(name="Album", value=track["album"], inline=False)
    if track["url"]:
        embed.add_field(name="Link", value=track["url"], inline=False)
    if track["image"]:
        embed.set_thumbnail(url=track["image"])
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="previewfm", description="Preview your regular Last.fm embed.")
async def previewfm(interaction: discord.Interaction):
    username = get_lastfm_user(interaction.user.id)
    if not username:
        await interaction.response.send_message("Set your Last.fm first with /setfm.", ephemeral=True)
        return

    track, err = await fetch_now_playing(username)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    user_info, _ = await fetch_user_info(username)
    track_info, _ = await fetch_track_info(track["artist"], track["name"], username)
    embed = build_regular_lastfm_embed(interaction.guild.id, username, track, user_info, track_info)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="fmtop", description="Show top artists from Last.fm.")
@app_commands.choices(period=[
    app_commands.Choice(name="7 days", value="7day"),
    app_commands.Choice(name="1 month", value="1month"),
    app_commands.Choice(name="3 months", value="3month"),
    app_commands.Choice(name="6 months", value="6month"),
    app_commands.Choice(name="12 months", value="12month"),
    app_commands.Choice(name="overall", value="overall")
])
async def fmtop(interaction: discord.Interaction, period: app_commands.Choice[str], member: discord.Member | None = None):
    member = member or interaction.user
    username = get_lastfm_user(member.id)
    if not username:
        await interaction.response.send_message(f"{member.mention} has not set a Last.fm username yet.", ephemeral=True)
        return

    artists, err = await fetch_top_artists(username, period.value)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return

    embed = build_embed(f"Top Artists — {username}", guild_color(interaction.guild.id))
    lines = []
    for i, artist in enumerate(artists, start=1):
        lines.append(f"**{i}.** {artist.get('name', 'Unknown')} — {artist.get('playcount', '0')} plays")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Period: {period.name}")
    await interaction.response.send_message(embed=embed)


ensure_files()

if not TOKEN:
    raise ValueError("DISCORD_TOKEN is missing. Add it in Replit Secrets.")

bot.run(TOKEN)
