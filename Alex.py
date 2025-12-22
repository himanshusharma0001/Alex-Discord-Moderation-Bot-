import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
import asyncio
import ssl
import certifi
import token

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)  # Change "!" to your preferred prefix

# Data storage files
WARNINGS_FILE = "warnings.json"
MUTES_FILE = "mutes.json"
LOGS_CHANNEL_FILE = "log_channels.json"

# Helper functions for data persistence
def load_data(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}

def save_data(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

warnings_data = load_data(WARNINGS_FILE)
mutes_data = load_data(MUTES_FILE)
log_channels = load_data(LOGS_CHANNEL_FILE)

# Logging function
async def log_action(guild, action_type, moderator, target, reason, duration=None):
    guild_id = str(guild.id)
    if guild_id not in log_channels:
        return
    
    channel = guild.get_channel(int(log_channels[guild_id]))
    if not channel:
        return
    
    embed = discord.Embed(
        title=f"🔨 {action_type}",
        color=discord.Color.red() if action_type in ["Ban", "Kick"] else discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="👤 Target", value=f"{target.mention} ({target.id})", inline=True)
    embed.add_field(name="👮 Moderator", value=f"{moderator.mention}", inline=True)
    embed.add_field(name="📝 Reason", value=reason or "No reason provided", inline=False)
    
    if duration:
        embed.add_field(name="⏰ Duration", value=duration, inline=True)
    
    embed.set_footer(text=f"User ID: {target.id}")
    
    await channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f'{bot.user} is now online!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Set log channel command
@bot.hybrid_command(name="setlogchannel", description="Set the channel for moderation logs")
@commands.has_permissions(administrator=True)
async def set_log_channel(ctx, channel: discord.TextChannel):
    log_channels[str(ctx.guild.id)] = channel.id
    save_data(LOGS_CHANNEL_FILE, log_channels)
    await ctx.send(f"✅ Log channel set to {channel.mention}")

# Warn command
@bot.hybrid_command(name="warn", description="Warn a user")
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You cannot warn someone with equal or higher role!")
        return
    
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    if guild_id not in warnings_data:
        warnings_data[guild_id] = {}
    if user_id not in warnings_data[guild_id]:
        warnings_data[guild_id][user_id] = []
    
    warning = {
        "reason": reason,
        "moderator": str(ctx.author.id),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    warnings_data[guild_id][user_id].append(warning)
    save_data(WARNINGS_FILE, warnings_data)
    
    warning_count = len(warnings_data[guild_id][user_id])
    
    embed = discord.Embed(
        title="⚠️ User Warned",
        color=discord.Color.yellow(),
        description=f"{member.mention} has been warned!"
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=f"{warning_count}", inline=True)
    
    await ctx.send(embed=embed)
    await log_action(ctx.guild, "Warning", ctx.author, member, reason)
    
    try:
        await member.send(f"⚠️ You have been warned in **{ctx.guild.name}**\n**Reason:** {reason}\n**Total Warnings:** {warning_count}")
    except:
        pass

# Check warnings command
@bot.hybrid_command(name="warnings", description="Check warnings for a user")
@commands.has_permissions(kick_members=True)
async def warnings(ctx, member: discord.Member):
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    if guild_id not in warnings_data or user_id not in warnings_data[guild_id]:
        await ctx.send(f"{member.mention} has no warnings.")
        return
    
    user_warnings = warnings_data[guild_id][user_id]
    
    embed = discord.Embed(
        title=f"⚠️ Warnings for {member.name}",
        color=discord.Color.yellow(),
        description=f"Total warnings: {len(user_warnings)}"
    )
    
    for i, warn in enumerate(user_warnings[-5:], 1):  # Show last 5 warnings
        mod = ctx.guild.get_member(int(warn["moderator"]))
        mod_name = mod.name if mod else "Unknown"
        timestamp = datetime.fromisoformat(warn["timestamp"]).strftime("%Y-%m-%d %H:%M")
        embed.add_field(
            name=f"Warning #{i}",
            value=f"**Reason:** {warn['reason']}\n**By:** {mod_name}\n**Date:** {timestamp}",
            inline=False
        )
    
    await ctx.send(embed=embed)

# Clear warnings command
@bot.hybrid_command(name="clearwarnings", description="Clear all warnings for a user")
@commands.has_permissions(administrator=True)
async def clear_warnings(ctx, member: discord.Member):
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    if guild_id in warnings_data and user_id in warnings_data[guild_id]:
        del warnings_data[guild_id][user_id]
        save_data(WARNINGS_FILE, warnings_data)
        await ctx.send(f"✅ Cleared all warnings for {member.mention}")
    else:
        await ctx.send(f"{member.mention} has no warnings to clear.")

# Mute command
@bot.hybrid_command(name="mute", description="Timeout a user")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration: str = "10m", *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You cannot mute someone with equal or higher role!")
        return
    
    # Parse duration
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = duration[-1]
    
    if unit not in time_units:
        await ctx.send("❌ Invalid duration format! Use: 10s, 10m, 10h, or 10d")
        return
    
    try:
        amount = int(duration[:-1])
        seconds = amount * time_units[unit]
    except ValueError:
        await ctx.send("❌ Invalid duration format!")
        return
    
    if seconds > 2419200:  # 28 days max
        await ctx.send("❌ Maximum timeout duration is 28 days!")
        return
    
    try:
        await member.timeout(timedelta(seconds=seconds), reason=reason)
        
        embed = discord.Embed(
            title="🔇 User Muted",
            color=discord.Color.orange(),
            description=f"{member.mention} has been muted!"
        )
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        await ctx.send(embed=embed)
        await log_action(ctx.guild, "Mute", ctx.author, member, reason, duration)
        
        try:
            await member.send(f"🔇 You have been muted in **{ctx.guild.name}** for {duration}\n**Reason:** {reason}")
        except:
            pass
            
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to timeout this user!")
    except Exception as e:
        await ctx.send(f"❌ An error occurred: {str(e)}")

# Unmute command
@bot.hybrid_command(name="unmute", description="Remove timeout from a user")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.send(f"✅ {member.mention} has been unmuted!")
        await log_action(ctx.guild, "Unmute", ctx.author, member, "Unmuted by moderator")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove timeout from this user!")

# Kick command
@bot.hybrid_command(name="kick", description="Kick a user from the server")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You cannot kick someone with equal or higher role!")
        return
    
    try:
        await member.send(f"👢 You have been kicked from **{ctx.guild.name}**\n**Reason:** {reason}")
    except:
        pass
    
    try:
        await member.kick(reason=reason)
        
        embed = discord.Embed(
            title="👢 User Kicked",
            color=discord.Color.red(),
            description=f"{member.mention} has been kicked!"
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        
        await ctx.send(embed=embed)
        await log_action(ctx.guild, "Kick", ctx.author, member, reason)
        
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to kick this user!")

# Ban command
@bot.hybrid_command(name="ban", description="Ban a user from the server")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You cannot ban someone with equal or higher role!")
        return
    
    try:
        await member.send(f"🔨 You have been banned from **{ctx.guild.name}**\n**Reason:** {reason}")
    except:
        pass
    
    try:
        await member.ban(reason=reason, delete_message_days=1)
        
        embed = discord.Embed(
            title="🔨 User Banned",
            color=discord.Color.dark_red(),
            description=f"{member.mention} has been banned!"
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        
        await ctx.send(embed=embed)
        await log_action(ctx.guild, "Ban", ctx.author, member, reason)
        
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to ban this user!")

# Unban command
@bot.hybrid_command(name="unban", description="Unban a user")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user)
        await ctx.send(f"✅ {user.mention} has been unbanned!")
        await log_action(ctx.guild, "Unban", ctx.author, user, "Unbanned by moderator")
    except discord.NotFound:
        await ctx.send("❌ User not found or not banned!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unban users!")
    except ValueError:
        await ctx.send("❌ Invalid user ID!")

# Purge command
@bot.hybrid_command(name="purge", description="Delete multiple messages")
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 100:
        await ctx.send("❌ Please specify a number between 1 and 100!")
        return
    
    deleted = await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"✅ Deleted {len(deleted) - 1} messages!")
    await asyncio.sleep(3)
    await msg.delete()
    
    await log_action(ctx.guild, "Purge", ctx.author, ctx.channel, f"Deleted {len(deleted) - 1} messages")

# Ping command
@bot.hybrid_command(name="ping", description="Check the bot's latency")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green(),
        description=f"Bot latency: **{latency}ms**"
    )
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Help command - Remove default help and create custom one
bot.remove_command('help')

@bot.hybrid_command(name="help", description="View all bot commands")
async def help_command(ctx, category: str = None):
    prefix = bot.command_prefix
    
    if category is None:
        # Main help menu
        embed = discord.Embed(
            title="🤖 Bot Commands Help",
            description=f"Use `{prefix}help <category>` for detailed info about a category\nOr use slash commands: `/command`",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📚 Categories",
            value=(
                "**moderation** - Moderation commands\n"
                "**info** - Information commands\n"
                "**server** - Server-related commands\n"
                "**utility** - Utility commands"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 How to Use",
            value=f"Slash commands: `/ping`\nText commands: `{prefix}ping`",
            inline=False
        )
        
        embed.set_footer(text=f"Requested by {ctx.author.name} | Prefix: {prefix}")
        
    elif category.lower() == "moderation":
        embed = discord.Embed(
            title="🔨 Moderation Commands",
            description="Commands for server moderation",
            color=discord.Color.red()
        )
        
        embed.add_field(name=f"`{prefix}warn <user> [reason]`", 
                       value="Warn a user", inline=False)
        embed.add_field(name=f"`{prefix}warnings <user>`", 
                       value="View user's warnings", inline=False)
        embed.add_field(name=f"`{prefix}clearwarnings <user>`", 
                       value="Clear all warnings for a user", inline=False)
        embed.add_field(name=f"`{prefix}mute <user> [duration] [reason]`", 
                       value="Timeout a user (e.g., 10m, 1h, 1d)", inline=False)
        embed.add_field(name=f"`{prefix}unmute <user>`", 
                       value="Remove timeout from a user", inline=False)
        embed.add_field(name=f"`{prefix}kick <user> [reason]`", 
                       value="Kick a user from server", inline=False)
        embed.add_field(name=f"`{prefix}ban <user> [reason]`", 
                       value="Ban a user from server", inline=False)
        embed.add_field(name=f"`{prefix}unban <user_id>`", 
                       value="Unban a user by ID", inline=False)
        embed.add_field(name=f"`{prefix}purge <amount>`", 
                       value="Delete multiple messages (1-100)", inline=False)
        
        embed.set_footer(text="Requires: Appropriate permissions")
        
    elif category.lower() == "info":
        embed = discord.Embed(
            title="📊 Information Commands",
            description="Commands to view user information",
            color=discord.Color.blue()
        )
        
        embed.add_field(name=f"`{prefix}avatar [user]`", 
                       value="View a user's avatar", inline=False)
        embed.add_field(name=f"`{prefix}banner [user]`", 
                       value="View a user's banner", inline=False)
        embed.add_field(name=f"`{prefix}userinfo [user]`", 
                       value="View detailed user information", inline=False)
        
        embed.set_footer(text="Anyone can use these commands")
        
    elif category.lower() == "server":
        embed = discord.Embed(
            title="🏠 Server Commands",
            description="Commands to view server information",
            color=discord.Color.green()
        )
        
        embed.add_field(name=f"`{prefix}servericon`", 
                       value="View the server's icon", inline=False)
        embed.add_field(name=f"`{prefix}serverbanner`", 
                       value="View the server's banner", inline=False)
        embed.add_field(name=f"`{prefix}emojicount`", 
                       value="Count total emojis in server", inline=False)
        embed.add_field(name=f"`{prefix}membercount`", 
                       value="Count total members in server", inline=False)
        embed.add_field(name=f"`{prefix}serverinfo`", 
                       value="View detailed server information", inline=False)
        
        embed.set_footer(text="Anyone can use these commands")
        
    elif category.lower() == "utility":
        embed = discord.Embed(
            title="🔧 Utility Commands",
            description="General utility commands",
            color=discord.Color.purple()
        )
        
        embed.add_field(name=f"`{prefix}ping`", 
                       value="Check bot's latency", inline=False)
        embed.add_field(name=f"`{prefix}setlogchannel <channel>`", 
                       value="Set moderation log channel", inline=False)
        embed.add_field(name=f"`{prefix}help [category]`", 
                       value="View this help menu", inline=False)
        
        embed.set_footer(text="Anyone can use ping and help")
        
    else:
        embed = discord.Embed(
            title="❌ Invalid Category",
            description=f"Available categories: `moderation`, `info`, `server`, `utility`\nUse `{prefix}help` to see all categories",
            color=discord.Color.red()
        )
    
    await ctx.send(embed=embed)

# Server Icon command
@bot.hybrid_command(name="servericon", description="View the server's icon")
async def servericon(ctx):
    if ctx.guild.icon is None:
        await ctx.send("❌ This server doesn't have an icon set.")
        return
    
    embed = discord.Embed(
        title=f"{ctx.guild.name}'s Icon",
        color=discord.Color.blue()
    )
    
    icon_url = ctx.guild.icon.url
    
    embed.set_image(url=icon_url)
    embed.add_field(name="🔗 Links", value=f"[PNG]({ctx.guild.icon.replace(format='png', size=4096).url}) | "
                                           f"[JPG]({ctx.guild.icon.replace(format='jpg', size=4096).url}) | "
                                           f"[WEBP]({ctx.guild.icon.replace(format='webp', size=4096).url})",
                    inline=False)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Server Banner command
@bot.hybrid_command(name="serverbanner", description="View the server's banner")
async def serverbanner(ctx):
    if ctx.guild.banner is None:
        await ctx.send("❌ This server doesn't have a banner set.")
        return
    
    embed = discord.Embed(
        title=f"{ctx.guild.name}'s Banner",
        color=discord.Color.blue()
    )
    
    banner_url = ctx.guild.banner.url
    
    embed.set_image(url=banner_url)
    embed.add_field(name="🔗 Links", value=f"[PNG]({ctx.guild.banner.replace(format='png', size=4096).url}) | "
                                           f"[JPG]({ctx.guild.banner.replace(format='jpg', size=4096).url}) | "
                                           f"[WEBP]({ctx.guild.banner.replace(format='webp', size=4096).url})",
                    inline=False)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Emoji Count command
@bot.hybrid_command(name="emojicount", description="Count total emojis in the server")
async def emojicount(ctx):
    static_emojis = [e for e in ctx.guild.emojis if not e.animated]
    animated_emojis = [e for e in ctx.guild.emojis if e.animated]
    total_emojis = len(ctx.guild.emojis)
    
    embed = discord.Embed(
        title=f"😀 {ctx.guild.name}'s Emoji Count",
        color=discord.Color.gold()
    )
    
    embed.add_field(name="📊 Total Emojis", value=f"**{total_emojis}**", inline=False)
    embed.add_field(name="🖼️ Static Emojis", value=f"{len(static_emojis)}", inline=True)
    embed.add_field(name="✨ Animated Emojis", value=f"{len(animated_emojis)}", inline=True)
    
    # Show emoji limit based on server boost level
    emoji_limit = 50
    animated_limit = 50
    
    if ctx.guild.premium_tier == 1:
        emoji_limit = animated_limit = 100
    elif ctx.guild.premium_tier == 2:
        emoji_limit = animated_limit = 150
    elif ctx.guild.premium_tier >= 3:
        emoji_limit = animated_limit = 250
    
    embed.add_field(name="📈 Emoji Slots", 
                   value=f"Static: {len(static_emojis)}/{emoji_limit}\nAnimated: {len(animated_emojis)}/{animated_limit}", 
                   inline=False)
    
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Member Count command
@bot.hybrid_command(name="membercount", description="Count total members in the server")
async def membercount(ctx):
    total_members = ctx.guild.member_count
    
    # Count humans and bots
    humans = len([m for m in ctx.guild.members if not m.bot])
    bots = len([m for m in ctx.guild.members if m.bot])
    
    # Count online members
    online = len([m for m in ctx.guild.members if m.status == discord.Status.online])
    idle = len([m for m in ctx.guild.members if m.status == discord.Status.idle])
    dnd = len([m for m in ctx.guild.members if m.status == discord.Status.dnd])
    offline = len([m for m in ctx.guild.members if m.status == discord.Status.offline])
    
    embed = discord.Embed(
        title=f"👥 {ctx.guild.name}'s Member Count",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="📊 Total Members", value=f"**{total_members}**", inline=False)
    embed.add_field(name="👤 Humans", value=f"{humans}", inline=True)
    embed.add_field(name="🤖 Bots", value=f"{bots}", inline=True)
    
    embed.add_field(name="📡 Status Breakdown", 
                   value=f"🟢 Online: {online}\n🟡 Idle: {idle}\n🔴 DND: {dnd}\n⚫ Offline: {offline}", 
                   inline=False)
    
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Server Info command (bonus - comprehensive server info)
@bot.hybrid_command(name="serverinfo", description="View detailed server information")
async def serverinfo(ctx):
    guild = ctx.guild
    
    embed = discord.Embed(
        title=f"📋 {guild.name}",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    
    # Basic info
    embed.add_field(name="🆔 Server ID", value=f"{guild.id}", inline=True)
    embed.add_field(name="👑 Owner", value=f"{guild.owner.mention}", inline=True)
    embed.add_field(name="📅 Created", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=True)
    
    # Member stats
    total_members = guild.member_count
    humans = len([m for m in guild.members if not m.bot])
    bots = len([m for m in guild.members if m.bot])
    
    embed.add_field(name="👥 Members", value=f"Total: {total_members}\nHumans: {humans}\nBots: {bots}", inline=True)
    
    # Channel stats
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    
    embed.add_field(name="📺 Channels", 
                   value=f"Text: {text_channels}\nVoice: {voice_channels}\nCategories: {categories}", 
                   inline=True)
    
    # Other stats
    embed.add_field(name="😀 Emojis", value=f"{len(guild.emojis)}", inline=True)
    embed.add_field(name="🎭 Roles", value=f"{len(guild.roles)}", inline=True)
    
    # Boost info
    boost_level = guild.premium_tier
    boost_count = guild.premium_subscription_count
    
    embed.add_field(name="💎 Boost Status", 
                   value=f"Level: {boost_level}\nBoosts: {boost_count}", 
                   inline=True)
    
    # Verification level
    verification = str(guild.verification_level).replace("_", " ").title()
    embed.add_field(name="🔒 Verification", value=verification, inline=True)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Avatar command
@bot.hybrid_command(name="avatar", description="View a user's avatar")
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    
    embed = discord.Embed(
        title=f"{member.name}'s Avatar",
        color=member.color
    )
    
    # Get avatar URL (supports both server-specific and global avatars)
    avatar_url = member.display_avatar.url
    
    embed.set_image(url=avatar_url)
    embed.add_field(name="🔗 Links", value=f"[PNG]({member.display_avatar.replace(format='png', size=4096).url}) | "
                                           f"[JPG]({member.display_avatar.replace(format='jpg', size=4096).url}) | "
                                           f"[WEBP]({member.display_avatar.replace(format='webp', size=4096).url})",
                    inline=False)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Banner command
@bot.hybrid_command(name="banner", description="View a user's banner")
async def banner(ctx, member: discord.Member = None):
    member = member or ctx.author
    
    # Fetch the user to get banner info (Member object doesn't include banner)
    user = await bot.fetch_user(member.id)
    
    if user.banner is None:
        embed = discord.Embed(
            title="❌ No Banner",
            description=f"{member.mention} doesn't have a banner set.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title=f"{member.name}'s Banner",
        color=member.color
    )
    
    banner_url = user.banner.url
    
    embed.set_image(url=banner_url)
    embed.add_field(name="🔗 Links", value=f"[PNG]({user.banner.replace(format='png', size=4096).url}) | "
                                           f"[JPG]({user.banner.replace(format='jpg', size=4096).url}) | "
                                           f"[WEBP]({user.banner.replace(format='webp', size=4096).url})",
                    inline=False)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# User Info command (bonus - shows avatar, banner, and other info)
@bot.hybrid_command(name="userinfo", description="View detailed information about a user")
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    user = await bot.fetch_user(member.id)
    
    embed = discord.Embed(
        title=f"User Information - {member.name}",
        color=member.color,
        timestamp=datetime.utcnow()
    )
    
    embed.set_thumbnail(url=member.display_avatar.url)
    
    if user.banner:
        embed.set_image(url=user.banner.url)
    
    # Basic info
    embed.add_field(name="👤 Username", value=f"{member.name}", inline=True)
    embed.add_field(name="🆔 User ID", value=f"{member.id}", inline=True)
    embed.add_field(name="🤖 Bot?", value="Yes" if member.bot else "No", inline=True)
    
    # Dates
    embed.add_field(name="📅 Account Created", 
                    value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
    embed.add_field(name="📥 Joined Server", 
                    value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
    
    # Roles
    roles = [role.mention for role in member.roles[1:]]  # Skip @everyone
    if roles:
        embed.add_field(name=f"🎭 Roles ({len(roles)})", 
                       value=" ".join(roles) if len(roles) <= 10 else f"{' '.join(roles[:10])} and {len(roles)-10} more...", 
                       inline=False)
    
    # Status
    status_emoji = {
        discord.Status.online: "🟢",
        discord.Status.idle: "🟡",
        discord.Status.dnd: "🔴",
        discord.Status.offline: "⚫"
    }
    embed.add_field(name="📡 Status", 
                   value=f"{status_emoji.get(member.status, '⚫')} {str(member.status).title()}", 
                   inline=True)
    
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    
    await ctx.send(embed=embed)

# Replace 'YOUR_BOT_TOKEN' with your actual bot token
bot.run(token.TOKEN)