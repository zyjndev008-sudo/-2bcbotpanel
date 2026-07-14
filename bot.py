import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands

BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"
PREFIX = "!"
VERIFIED_USER_IDS = [123456789012345678]
DATA_FILE = Path(__file__).with_name('data.json')
BLACK_COLOR = 0x000000

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

if not DATA_FILE.exists():
    DATA_FILE.write_text(json.dumps({"guilds": {}}, indent=2), encoding='utf-8')

with DATA_FILE.open('r', encoding='utf-8') as f:
    try:
        data = json.load(f)
    except json.JSONDecodeError:
        data = {"guilds": {}}


def save_data():
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


def ensure_guild(guild_id: int):
    guild_id = str(guild_id)
    if guild_id not in data['guilds']:
        data['guilds'][guild_id] = {
            'support_role_ids': [],
            'ticket_log_channel_id': None,
            'ticket_counter': 0,
            'panels': {},
            'tickets': {},
        }
        save_data()
    return data['guilds'][guild_id]


def is_support(member: discord.Member, guild_data: dict) -> bool:
    if not member or not guild_data:
        return False
    return any(role.id in guild_data['support_role_ids'] for role in member.roles)


def has_verified_permission(user_id: int) -> bool:
    return user_id in VERIFIED_USER_IDS


def format_age(created_at: datetime) -> str:
    if not created_at:
        return 'Unknown'
    diff = datetime.utcnow() - created_at
    days = diff.days
    years, days = divmod(days, 365)
    if years > 0:
        return f'{years} year(s) {days} day(s)'
    return f'{days} day(s)'


def build_embed(title: str = None, description: str = None, fields: list = None, footer: str = None, image: str = None, author: dict = None):
    embed = discord.Embed(color=BLACK_COLOR)
    if title:
        embed.title = title
    if description:
        embed.description = description
    if fields:
        embed.add_fields(*fields)
    if footer:
        embed.set_footer(text=footer)
    if image:
        embed.set_image(url=image)
    if author:
        embed.set_author(name=author.get('name'), icon_url=author.get('icon_url'))
    embed.timestamp = datetime.utcnow()
    return embed


def sanitize_channel_name(value: str) -> str:
    sanitized = re.sub(r'[^a-z0-9-]', '-', value.lower())
    sanitized = re.sub(r'-{2,}', '-', sanitized).strip('-')
    return sanitized[:90] or 'ticket'


def parse_role(argument: str, guild: discord.Guild):
    if not argument:
        return None
    mention = re.match(r'<@&([0-9]+)>', argument)
    role_id = int(mention.group(1)) if mention else int(re.sub(r'[^0-9]', '', argument)) if argument else None
    if role_id:
        return guild.get_role(role_id)
    return None


def parse_member(argument: str, guild: discord.Guild):
    if not argument:
        return None
    mention = re.match(r'<@!?(\d+)>', argument)
    member_id = int(mention.group(1)) if mention else int(re.sub(r'[^0-9]', '', argument)) if argument else None
    if member_id:
        return guild.get_member(member_id)
    return None


async def ask_text(ctx: commands.Context, prompt: str, optional: bool = False):
    await ctx.send(embed=build_embed(title=prompt))

    def check(message: discord.Message):
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        answer = await bot.wait_for('message', timeout=120.0, check=check)
    except asyncio.TimeoutError:
        await ctx.send(embed=build_embed(title='Setup timed out', description='Please run the setup command again.'))
        return None

    content = answer.content.strip()
    if optional and content.lower() == 'none':
        return None
    return content


class TicketPanelView(discord.ui.View):
    def __init__(self, guild_id: int, panel_name: str, panel_data: dict):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.panel_name = panel_name
        self.panel_data = panel_data

        if panel_data['type'] == 'button':
            self.add_item(discord.ui.Button(label='Open ticket', style=discord.ButtonStyle.primary, custom_id=f'ticket_panel_button|{guild_id}|{panel_name}'))
        else:
            options = [discord.SelectOption(label=opt[:25], value=opt) for opt in panel_data['options']]
            self.add_item(discord.ui.Select(placeholder='Choose a ticket option', options=options, custom_id=f'ticket_panel_select|{guild_id}|{panel_name}'))


class ConfirmCloseView(discord.ui.View):
    def __init__(self, guild_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel_id = channel_id

    @discord.ui.button(label='Yes', style=discord.ButtonStyle.danger, custom_id='ticket_close_yes')
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_data = ensure_guild(interaction.guild.id)
        ticket = guild_data['tickets'].get(str(self.channel_id))
        if not ticket:
            await interaction.response.send_message('No ticket data found.', ephemeral=True)
            return
        if not is_support(interaction.user, guild_data):
            await interaction.response.send_message('Only support staff may confirm closure.', ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.set_permissions(interaction.user, view=True, send_messages=True, read_message_history=True)
            await channel.set_permissions(interaction.guild.default_role, view=False)
            for role_id in guild_data['support_role_ids']:
                await channel.set_permissions(interaction.guild.get_role(role_id), view=False, send_messages=False, read_message_history=False)

        await interaction.response.edit_message(embed=build_embed(title='Ticket closed', description=f'Ticket closed by <@{interaction.user.id}>.'), view=None)
        if channel:
            await send_ticket_log(interaction.guild, guild_data, ticket, channel, f'<@{interaction.user.id}>')
        guild_data['tickets'].pop(str(self.channel_id), None)
        save_data()

    @discord.ui.button(label='No', style=discord.ButtonStyle.secondary, custom_id='ticket_close_no')
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=build_embed(title='Ticket closure cancelled', description='No changes were made.'), view=None)


class TranscriptView(discord.ui.View):
    def __init__(self, ticket_channel_id: int):
        super().__init__(timeout=None)
        self.ticket_channel_id = ticket_channel_id

    @discord.ui.button(label='Transcript', style=discord.ButtonStyle.secondary, custom_id='ticket_transcript')
    async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_data = ensure_guild(interaction.guild.id)
        ticket = guild_data['tickets'].get(str(self.ticket_channel_id))
        if not ticket:
            await interaction.response.send_message('Transcript unavailable.', ephemeral=True)
            return
        if ticket['opener_id'] != interaction.user.id and not is_support(interaction.user, guild_data):
            await interaction.response.send_message('You may not request this transcript.', ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.ticket_channel_id)
        if not channel:
            await interaction.response.send_message('Ticket channel no longer exists.', ephemeral=True)
            return

        messages = await channel.history(limit=200, oldest_first=True).flatten()
        lines = [f'[{msg.created_at.isoformat()}] {msg.author}: {msg.content}' for msg in messages]
        transcript = '\n'.join(lines) or 'No transcript available.'
        file = discord.File(fp=transcript.encode('utf-8'), filename=f'ticket-{self.ticket_channel_id}-transcript.txt')
        try:
            await interaction.user.send(file=file)
            await interaction.response.send_message('Transcript sent by DM.', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message('Could not send DM. Please enable messages from this server.', ephemeral=True)


async def create_ticket_channel(interaction: discord.Interaction, panel_name: str, option_name: str):
    guild = interaction.guild
    guild_data = ensure_guild(guild.id)
    panel = guild_data['panels'].get(panel_name.lower())
    if not panel:
        await interaction.response.send_message('Ticket panel no longer exists.', ephemeral=True)
        return

    guild_data['ticket_counter'] += 1
    ticket_number = guild_data['ticket_counter']
    save_data()

    channel_name = sanitize_channel_name(f'{option_name}-{ticket_number}')
    category = interaction.channel.category if interaction.channel else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    for role_id in guild_data['support_role_ids']:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    ticket_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites, reason='Ticket opened')

    member = guild.get_member(interaction.user.id)
    embed = build_embed(
        title=f'Ticket opened: {option_name}',
        description='A support staff member will be with you shortly.',
        fields=[
            {'name': 'Created by', 'value': str(interaction.user), 'inline': True},
            {'name': 'Creator ID', 'value': str(interaction.user.id), 'inline': True},
            {'name': 'Account age', 'value': format_age(interaction.user.created_at), 'inline': True},
            {'name': 'Server join age', 'value': format_age(member.joined_at) if member and member.joined_at else 'Unknown', 'inline': True},
            {'name': 'Ticket type', 'value': option_name, 'inline': True},
        ],
        author={'name': str(interaction.user), 'icon_url': interaction.user.display_avatar.url if interaction.user.display_avatar else None},
    )

    support_mentions = ' '.join(f'<@&{role_id}>' for role_id in guild_data['support_role_ids'] if guild.get_role(role_id)) or None
    await ticket_channel.send(content=support_mentions, embed=embed)

    guild_data['tickets'][str(ticket_channel.id)] = {
        'opener_id': interaction.user.id,
        'option_name': option_name,
        'panel_name': panel['name'],
        'claimed_by': None,
        'created_at': datetime.utcnow().isoformat(),
    }
    save_data()
    await interaction.response.send_message(f'Ticket created: {ticket_channel.mention}', ephemeral=True)


async def send_ticket_log(guild: discord.Guild, guild_data: dict, ticket: dict, channel: discord.TextChannel, closed_by: str):
    log_channel_id = guild_data.get('ticket_log_channel_id')
    if not log_channel_id:
        return
    log_channel = guild.get_channel(log_channel_id)
    if not log_channel or not isinstance(log_channel, discord.TextChannel):
        return

    embed = build_embed(
        title='Ticket Closed',
        description=f'Ticket channel {channel.mention} was closed by {closed_by}.',
        fields=[
            {'name': 'Ticket Topic', 'value': ticket['option_name'], 'inline': True},
            {'name': 'Opened by', 'value': f'<@{ticket["opener_id"]}>', 'inline': True},
            {'name': 'Ticket channel', 'value': channel.name, 'inline': True},
        ],
        footer='Ticket log channel',
    )
    view = TranscriptView(ticket_channel_id=channel.id)
    await log_channel.send(embed=embed, view=view)


@bot.event
async def on_ready():
    print(f'Bot ready as {bot.user}')


@bot.command(name='setup')
@commands.has_permissions(manage_guild=True)
async def setup(ctx: commands.Context):
    guild_data = ensure_guild(ctx.guild.id)
    await ctx.send(embed=build_embed(title='Ticket setup starting', description='I will ask for the panel details.'))

    panel_name = await ask_text(ctx, 'Panel name')
    if not panel_name:
        return
    panel_key = panel_name.lower()
    if panel_key in guild_data['panels']:
        await ctx.send(embed=build_embed(title='Panel exists', description='A panel with that name already exists.'))
        return

    title = await ask_text(ctx, 'Embed title')
    if title is None:
        return
    description = await ask_text(ctx, 'Embed description', optional=True)
    if description is None:
        return
    color_input = await ask_text(ctx, 'Embed color HEX (example: #000000)')
    if not color_input:
        return
    color = int(color_input.lstrip('#'), 16) if re.match(r'^#?[0-9A-Fa-f]{6}$', color_input) else BLACK_COLOR
    image = await ask_text(ctx, 'Image URL or type none', optional=True)
    footer = await ask_text(ctx, 'Footer text or type none', optional=True)
    panel_type_input = await ask_text(ctx, 'Panel type: button or dropdown')
    if not panel_type_input:
        return
    panel_type = 'dropdown' if 'drop' in panel_type_input.lower() else 'button'
    options = []
    if panel_type == 'dropdown':
        count_input = await ask_text(ctx, 'How many dropdown options? (1-5)')
        if not count_input:
            return
        count = max(1, min(5, int(count_input)))
        for i in range(count):
            opt = await ask_text(ctx, f'Option {i+1} name')
            if not opt:
                return
            options.append(opt)

    guild_data['panels'][panel_key] = {
        'name': panel_name,
        'title': title,
        'description': description,
        'color': color,
        'image': image,
        'footer': footer,
        'type': panel_type,
        'options': options,
    }
    save_data()
    await ctx.send(embed=build_embed(title='Panel saved', description=f'Use `{PREFIX}sendpanel {panel_name} #channel` to deploy it.'))


@bot.command(name='sendpanel')
@commands.has_permissions(manage_guild=True)
async def sendpanel(ctx: commands.Context, panel_name: str, channel: discord.TextChannel):
    guild_data = ensure_guild(ctx.guild.id)
    panel = guild_data['panels'].get(panel_name.lower())
    if not panel:
        await ctx.send(embed=build_embed(title='Unknown panel', description='That panel name was not found.'))
        return

    embed = build_embed(
        title=panel['title'],
        description=panel['description'],
        footer=panel['footer'],
        image=panel['image'],
    )
    view = TicketPanelView(ctx.guild.id, panel_name.lower(), panel)
    await channel.send(embed=embed, view=view)
    await ctx.send(embed=build_embed(title='Panel sent', description=f'Panel sent to {channel.mention}.'))


@bot.group(name='support', invoke_without_command=True)
async def support(ctx: commands.Context):
    await ctx.send(embed=build_embed(title='Usage', description=f'{PREFIX}support add @role or {PREFIX}support remove @role'))


@support.command(name='add')
async def support_add(ctx: commands.Context, *, role_arg: str):
    if not has_verified_permission(ctx.author.id):
        await ctx.send(embed=build_embed(title='Unauthorized', description='You are not allowed to manage support roles.'))
        return
    role = parse_role(role_arg, ctx.guild)
    if not role:
        await ctx.send(embed=build_embed(title='Invalid role', description='Please mention a role or provide a role ID.'))
        return
    guild_data = ensure_guild(ctx.guild.id)
    if role.id not in guild_data['support_role_ids']:
        guild_data['support_role_ids'].append(role.id)
        save_data()
    await ctx.send(embed=build_embed(title='Support role added', description=f'Role {role.mention} is now support.'))


@support.command(name='remove')
async def support_remove(ctx: commands.Context, *, role_arg: str):
    if not has_verified_permission(ctx.author.id):
        await ctx.send(embed=build_embed(title='Unauthorized', description='You are not allowed to manage support roles.'))
        return
    role = parse_role(role_arg, ctx.guild)
    if not role:
        await ctx.send(embed=build_embed(title='Invalid role', description='Please mention a role or provide a role ID.'))
        return
    guild_data = ensure_guild(ctx.guild.id)
    guild_data['support_role_ids'] = [rid for rid in guild_data['support_role_ids'] if rid != role.id]
    save_data()
    await ctx.send(embed=build_embed(title='Support role removed', description=f'Role {role.mention} removed from support.'))


@bot.command(name='removesupport')
async def removesupport(ctx: commands.Context, *, role_arg: str):
    await support_remove.callback(ctx, role_arg=role_arg)


@bot.command(name='setticketlog')
@commands.has_permissions(manage_guild=True)
async def setticketlog(ctx: commands.Context, channel: discord.TextChannel):
    guild_data = ensure_guild(ctx.guild.id)
    guild_data['ticket_log_channel_id'] = channel.id
    save_data()
    await ctx.send(embed=build_embed(title='Ticket log set', description=f'Logs will be sent to {channel.mention}.'))


@bot.command(name='close')
async def close_ticket(ctx: commands.Context):
    guild_data = ensure_guild(ctx.guild.id)
    ticket = guild_data['tickets'].get(str(ctx.channel.id))
    if not ticket:
        await ctx.send(embed=build_embed(title='Not a ticket channel', description='This channel is not registered as a ticket.'))
        return

    if not is_support(ctx.author, guild_data):
        support_mentions = ' '.join(f'<@&{rid}>' for rid in guild_data['support_role_ids'] if ctx.guild.get_role(rid)) or 'support staff'
        await ctx.send(embed=build_embed(title='Support requested', description=f'{support_mentions} have been notified.'))
        for role_id in guild_data['support_role_ids']:
            role = ctx.guild.get_role(role_id)
            if not role:
                continue
            for member in role.members:
                try:
                    await member.send(embed=build_embed(title='Ticket requires support', description=f'Ticket channel: {ctx.channel.mention}\nOpened by: <@{ticket["opener_id"]}>'))
                except discord.Forbidden:
                    pass
        return

    view = ConfirmCloseView(ctx.guild.id, ctx.channel.id)
    await ctx.send(embed=build_embed(title='Confirm close', description='Are you sure you want to close this ticket?'), view=view)


@bot.command(name='add')
async def add_user(ctx: commands.Context, *, user_arg: str):
    guild_data = ensure_guild(ctx.guild.id)
    ticket = guild_data['tickets'].get(str(ctx.channel.id))
    if not ticket:
        await ctx.send(embed=build_embed(title='Not a ticket channel', description='This channel is not registered as a ticket.'))
        return
    if not is_support(ctx.author, guild_data):
        await ctx.send(embed=build_embed(title='Unauthorized', description='Only support staff can add users to tickets.'))
        return
    member = parse_member(user_arg, ctx.guild)
    if not member:
        await ctx.send(embed=build_embed(title='Invalid user', description='Mention a user or provide a valid user ID.'))
        return
    await ctx.channel.set_permissions(member, view=True, send_messages=True, read_message_history=True)
    await ctx.send(embed=build_embed(title='User added', description=f'<@{member.id}> can now see the ticket.'))


@bot.command(name='remove')
async def remove_user(ctx: commands.Context, *, user_arg: str):
    guild_data = ensure_guild(ctx.guild.id)
    ticket = guild_data['tickets'].get(str(ctx.channel.id))
    if not ticket:
        await ctx.send(embed=build_embed(title='Not a ticket channel', description='This channel is not registered as a ticket.'))
        return
    if not is_support(ctx.author, guild_data):
        await ctx.send(embed=build_embed(title='Unauthorized', description='Only support staff can remove users from tickets.'))
        return
    member = parse_member(user_arg, ctx.guild)
    if not member:
        await ctx.send(embed=build_embed(title='Invalid user', description='Mention a user or provide a valid user ID.'))
        return
    await ctx.channel.set_permissions(member, overwrite=discord.PermissionOverwrite(view_channel=False, send_messages=False, read_message_history=False))
    await ctx.send(embed=build_embed(title='User removed', description=f'<@{member.id}> has been removed from the ticket.'))


@bot.command(name='claim')
async def claim_ticket(ctx: commands.Context):
    guild_data = ensure_guild(ctx.guild.id)
    ticket = guild_data['tickets'].get(str(ctx.channel.id))
    if not ticket:
        await ctx.send(embed=build_embed(title='Not a ticket channel', description='This channel is not registered as a ticket.'))
        return
    if not is_support(ctx.author, guild_data):
        await ctx.send(embed=build_embed(title='Unauthorized', description='Only support staff can claim tickets.'))
        return
    if ticket.get('claimed_by'):
        await ctx.send(embed=build_embed(title='Already claimed', description='This ticket is already claimed.'))
        return

    ticket['claimed_by'] = ctx.author.id
    save_data()
    for role_id in guild_data['support_role_ids']:
        role = ctx.guild.get_role(role_id)
        if role and role != ctx.author.top_role:
            await ctx.channel.set_permissions(role, view=False, send_messages=False, read_message_history=False)
    await ctx.channel.set_permissions(ctx.author, view=True, send_messages=True, read_message_history=True)
    await ctx.send(embed=build_embed(title='Ticket claimed', description=f'Ticket claimed by <@{ctx.author.id}>. The channel is now private to this staff member and the requester.'))


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.guild:
        return
    if not interaction.data:
        return
    custom_id = interaction.data.get('custom_id')
    if not custom_id:
        return
    parts = custom_id.split('|')
    if len(parts) < 3:
        return
    action, guild_id_str, panel_name = parts
    if int(guild_id_str) != interaction.guild.id:
        return

    if action == 'ticket_panel_button':
        await create_ticket_channel(interaction, panel_name, panel_name)
    elif action == 'ticket_panel_select':
        selected = interaction.data.get('values', [None])[0]
        if not selected:
            await interaction.response.send_message('No option selected.', ephemeral=True)
            return
        await create_ticket_channel(interaction, panel_name, selected)


bot.run(BOT_TOKEN)
