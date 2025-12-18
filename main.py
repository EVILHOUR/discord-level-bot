import discord
from discord.ext import commands, tasks
import sqlite3
import math
import time
import os

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
# DATABASE
# =========================

conn = sqlite3.connect("levels.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER,
    level INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS cooldowns (
    user_id INTEGER PRIMARY KEY,
    last_message REAL
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

    cursor.execute("SELECT last_message FROM cooldowns WHERE user_id=?", (user_id,))
    cooldown = cursor.fetchone()

    if cooldown and now - cooldown[0] < MESSAGE_COOLDOWN_SECONDS:
        await bot.process_commands(message)
        return

    cursor.execute(
        "INSERT OR REPLACE INTO cooldowns (user_id, last_message) VALUES (?, ?)",
        (user_id, now)
    )

    cursor.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,))
    data = cursor.fetchone()

    if data is None:
        xp = XP_PER_MESSAGE
        level = 0
        cursor.execute(
            "INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)",
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
                    f"🎉 {message.author.mention} reached **Level {level}**!\n"
                    f"➡️ Next level at **{xp_for_level(level + 1)} XP**"
                )

        cursor.execute(
            "UPDATE users SET xp=?, level=? WHERE user_id=?",
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
            if (
                member.voice
                and member.voice.channel
                and not member.voice.self_mute
                and not member.voice.self_deaf
            ):
                cursor.execute(
                    "SELECT xp, level FROM users WHERE user_id=?", (member.id,)
                )
                data = cursor.fetchone()

                if data is None:
                    cursor.execute(
                        "INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)",
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
                                f"🎉 {member.mention} reached **Level {level}** from voice chat!"
                            )

                    cursor.execute(
                        "UPDATE users SET xp=?, level=? WHERE user_id=?",
                        (xp, level, member.id)
                    )

    conn.commit()

# =========================
# PREFIX COMMAND
# =========================

@bot.command()
async def level(ctx):
    cursor.execute("SELECT xp, level FROM users WHERE user_id=?", (ctx.author.id,))
    data = cursor.fetchone()

    if data is None:
        await ctx.send("You have no level yet.")
        return

    xp, level = data
    bar, percent, xp_remaining, next_xp = xp_progress_bar(xp, level)

    await ctx.send(
        f"⭐ **Level {level}**\n"
        f"{bar} **{percent}%**\n"
        f"XP: **{xp} / {next_xp}**\n"
        f"➡️ **{xp_remaining} XP** to next level"
    )

# =========================
# SLASH COMMANDS
# =========================

@bot.tree.command(name="level", description="Check your level and XP")
async def slash_level(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    cursor.execute("SELECT xp, level FROM users WHERE user_id=?", (interaction.user.id,))
    data = cursor.fetchone()

    if data is None:
        await interaction.followup.send("You have no level yet.", ephemeral=True)
        return

    xp, level = data
    bar, percent, xp_remaining, next_xp = xp_progress_bar(xp, level)

    await interaction.followup.send(
        f"⭐ **Level {level}**\n"
        f"{bar} **{percent}%**\n"
        f"XP: **{xp} / {next_xp}**\n"
        f"➡️ **{xp_remaining} XP** to next level"
    )

@bot.tree.command(name="leaderboard", description="View the XP leaderboard")
async def slash_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    cursor.execute(
        "SELECT user_id, xp, level FROM users ORDER BY xp DESC LIMIT 10"
    )
    rows = cursor.fetchall()

    text = "🏆 **Leaderboard**\n\n"
    for i, (user_id, xp, level) in enumerate(rows, start=1):
        user = bot.get_user(user_id)
        name = user.name if user else "Unknown"
        text += f"**{i}.** {name} — Level {level} ({xp} XP)\n"

    await interaction.followup.send(text)

# =========================
# START BOT
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)


