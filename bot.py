import discord
import os
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
from typing import Optional

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("SupportBot")

# 환경변수에서 토큰 및 ID 가져오기
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
SUPPORT_ROLE_ID = int(os.getenv("SUPPORT_ROLE_ID", 0))
SUPPORT_CATEGORY_ID = int(os.getenv("SUPPORT_CATEGORY_ID", 0))

# 봇 생성
class SupportBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        
        super().__init__(command_prefix='!', intents=intents)
        self.active_tickets = {}
        
    async def setup_hook(self):
        logger.info("봇 설정 중...")
        await self.tree.sync()
        logger.info("명령어가 동기화되었습니다.")

    async def on_ready(self):
        logger.info(f"{self.user.name}(으)로 로그인했습니다!")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, 
            name="문의 티켓"
        ))

    async def on_guild_channel_create(self, channel):
        if not isinstance(channel, discord.TextChannel):
            return
        if channel.category_id != SUPPORT_CATEGORY_ID:
            return
        logger.info(f"문의 카테고리에 새 채널 생성됨: {channel.name}")
        
        support_role = channel.guild.get_role(SUPPORT_ROLE_ID)
        if not support_role:
            logger.warning("문의담당자 역할을 찾을 수 없습니다.")
            return
        try:
            await channel.set_permissions(channel.guild.default_role, view_channel=False)
            await channel.set_permissions(support_role, 
                view_channel=True, send_messages=True, 
                read_message_history=True, manage_messages=True)
            
            embed = discord.Embed(
                title="📋 문의 티켓",
                description="이 채널은 문의 처리를 위해 생성되었습니다.\n"
                            "문의가 완료되면 `/문의_종료` 명령어를 사용하여 채널을 닫을 수 있습니다.",
                color=discord.Color.blue()
            )
            embed.set_footer(text="문의 시스템")
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"채널 권한 설정 중 오류: {e}")

class SupportCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="문의_담당자", description="문의 담당자만 사용할 수 있는 명령어")
    @app_commands.describe(유저="응답할 유저", 응답="문의에 대한 응답 내용")
    async def support_response(self, interaction: discord.Interaction, 유저: discord.Member, 응답: str):
        if not interaction.user.get_role(SUPPORT_ROLE_ID):
            await interaction.response.send_message("이 명령어는 문의담당자만 사용할 수 있습니다.", ephemeral=True)
            return
        if interaction.channel.category_id != SUPPORT_CATEGORY_ID:
            await interaction.response.send_message("이 명령어는 문의 카테고리 내에서만 사용할 수 있습니다.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📌 문의 응답",
            description=응답,
            color=discord.Color.green()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"{유저.display_name}님의 문의에 대한 응답")
        
        await interaction.response.send_message(content=f"{유저.mention}", embed=embed)

    @app_commands.command(name="문의_시작", description="새로운 문의 채널을 생성합니다")
    @app_commands.describe(제목="문의 제목")
    async def start_inquiry(self, interaction: discord.Interaction, 제목: str):
        channel_name = f"문의-{제목.replace(' ', '-').lower()}"
        try:
            category = interaction.guild.get_channel(SUPPORT_CATEGORY_ID)
            if not category:
                await interaction.response.send_message("문의 카테고리를 찾을 수 없습니다.", ephemeral=True)
                return

            channel = await interaction.guild.create_text_channel(name=channel_name, category=category)
            support_role = interaction.guild.get_role(SUPPORT_ROLE_ID)
            await channel.set_permissions(interaction.guild.default_role, view_channel=False)
            await channel.set_permissions(support_role, view_channel=True, send_messages=True, read_message_history=True)
            await channel.set_permissions(interaction.user, view_channel=True, send_messages=True, read_message_history=True)

            embed = discord.Embed(
                title=f"📋 문의: {제목}",
                description=f"{interaction.user.mention}님이 문의를 시작했습니다.\n"
                            f"문의가 완료되면 `/문의_종료` 명령어를 사용해 채널을 닫을 수 있습니다.",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed)

            await interaction.response.send_message(f"문의 채널 {channel.mention}이 생성되었습니다.", ephemeral=True)
            self.bot.active_tickets[channel.id] = {
                "creator": interaction.user.id,
                "title": 제목,
                "created_at": discord.utils.utcnow()
            }

        except Exception as e:
            logger.error(f"문의 채널 생성 오류: {e}")
            await interaction.response.send_message("채널 생성 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="문의_종료", description="현재 문의 채널을 종료하고 삭제합니다")
    async def close_inquiry(self, interaction: discord.Interaction):
        is_support = interaction.user.get_role(SUPPORT_ROLE_ID) is not None
        is_creator = interaction.channel.id in self.bot.active_tickets and \
                     self.bot.active_tickets[interaction.channel.id]["creator"] == interaction.user.id
        if not (is_support or is_creator):
            await interaction.response.send_message("문의담당자나 문의 생성자만 사용할 수 있습니다.", ephemeral=True)
            return
        if interaction.channel.category_id != SUPPORT_CATEGORY_ID:
            await interaction.response.send_message("문의 카테고리 내의 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🗑️ 문의 종료",
            description="이 문의 채널은 5초 후에 삭제됩니다.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)

        await asyncio.sleep(5)
        try:
            if interaction.channel.id in self.bot.active_tickets:
                del self.bot.active_tickets[interaction.channel.id]
            await interaction.channel.delete(reason=f"문의 종료 - {interaction.user}")
        except Exception as e:
            logger.error(f"채널 삭제 중 오류: {e}")

async def setup(bot):
    await bot.add_cog(SupportCommands(bot))

bot = SupportBot()

@bot.event
async def on_ready():
    await setup(bot)
    print(f"{bot.user.name}이(가) 준비되었습니다!")

bot.run(BOT_TOKEN)
