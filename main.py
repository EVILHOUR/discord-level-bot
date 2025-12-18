import discord
from discord.ext import commands, tasks
import psycopg2
import math
import time
import os
from urllib.parse import urlparse

# =========================
# CONFIG
# =========================

BOT_PREFIX = "!"
XP_PER_MESSAGE = 10
XP_PER_VOICE_INTERVAL = 15

MESSAGE_COOLDOWN_SECONDS = 60
VOICE_XP_INTERVAL_SECONDS = 60

LEVEL_UP_CHANNEL_ID = 1449164944376467578  # <-- your channel ID

# =========================
# INTENTS
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# =========================
# DATABASE (PostgreSQL)
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")

url = urlparse(DATABASE_URL)

conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port,
    sslmode="require"
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    xp INTEGER NOT NULL,
    level INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS cooldowns (
    user_id BIGINT PRIMARY KEY,
    last_message DOUBLE PRECISION
)
""")

conn.commit()

# =========================
# LEVEL FUNCTIONS
# =========================

def calculate_level(xp: int) -> int:
    return int(math.sqrt(xp // 100))

def xp_for_level(level: int) -> int:
    return (level ** 2) * 100

def xp_progress_bar(current_xp, level, bar_length=10):
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)

    xp_into_level = current_xp - current_level_xp
    xp_needed = next_level_xp - current_level_xp

    progress = max(0, min(xp_into_level / xp_needed, 1))
    filled = int(bar_length * progress)
    empty = bar_length - filled

    bar = "🟦" * filled + "⬜" * empty
    percent = int(progress * 100)
    xp_remaining = xp_needed - xp_into_level

    return bar, percent, xp_remaining, next_level_xp

# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    await bot.tree.sync()
    voice_xp_loop.start()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    now = time.time()

    cursor.execute(
        "SELECT last_message FROM cooldowns WHERE user_id=%s",
        (user_id,)
    )
    cooldown = cursor.fetchone()

    if cooldown and now - cooldown[0] < MESSAGE_COOLDOWN_SECONDS:
        await bot.process_commands(message)
        return

    cursor.execute("""
        INSERT INTO cooldowns (user_id, last_message)
        VALUES (%s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET last_message = EXCLUDED.last_message
    """, (user_id, now))

    cursor.execute(
        "SELECT xp, level FROM users WHERE user_id=%s",
        (user_id,)
    )
    data = cursor.fetchone()

    if data is None:
        xp = XP_PER_MESSAGE
        level = 0
        cursor.execute(
            "INSERT INTO users (user_id, xp, level) VALUES (%s, %s, %s)",
            (user_id, xp, level)
        )
    else:
        xp, level = data
        xp += XP_PER_MESSAGE
        new_level = calculate_level(xp)

        if new_level > level:
            level = new_level
            channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
            if channel:
                await channel.send(
                    f"🎉 {message.author.mention} reached **Level {level}**!"
                )

        cursor.execute(
            "UPDATE users SET xp=%s, level=%s WHERE user_id=%s",
            (xp, level, user_id)
        )

    conn.commit()
    await bot.process_commands(message)

# =========================
# VOICE XP LOOP
# =========================

@tasks.loop(seconds=VOICE_XP_INTERVAL_SECONDS)
async def voice_xp_loop():
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            if member.voice and member.voice.channel:

                cursor.execute(
                    "SELECT xp, level FROM users WHERE user_id=%s",
                    (member.id,)
                )
                data = cursor.fetchone()

                if data is None:
                    cursor.execute(
                        "INSERT INTO users (user_id, xp, level) VALUES (%s, %s, %s)",
                        (member.id, XP_PER_VOICE_INTERVAL, 0)
                    )
                else:
                    xp, level = data
                    xp += XP_PER_VOICE_INTERVAL
                    new_level = calculate_level(xp)

                    if new_level > level:
                        level = new_level
                        channel = bot.get_channel(LEVEL_UP_CHANNEL_ID)
                        if channel:
                            await channel.send(
                                f"🎉 {member.mention} reached **Level {level}** from voice!"
                            )

                    cursor.execute(
                        "UPDATE users SET xp=%s, level=%s WHERE user_id=%s",
                        (xp, level, member.id)
                    )

    conn.commit()

# =========================
# COMMANDS
# =========================

@bot.command()
async def level(ctx):
    cursor.execute(
        "SELECT xp, level FROM users WHERE user_id=%s",
        (ctx.author.id,)
    )
    data = cursor.fetchone()

    if not data:
        await ctx.send("You have no level yet.")
        return

    xp, level = data
    bar, percent, xp_remaining, next_xp = xp_progress_bar(xp, level)

    await ctx.send(
        f"⭐ **Level {level}**\n"
        f"{bar} **{percent}%**\n"
        f"XP: **{xp} / {next_xp}**"
    )

# =========================
# START BOT
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
