import os
import discord


class Client(discord.Client):
    async def on_ready(self):
        print(f'[ready] user={self.user} user_id={self.user.id}')

    async def on_message(self, message):
        channel_name = getattr(message.channel, 'name', str(message.channel))
        guild_name = getattr(message.guild, 'name', 'DM')
        print(
            f'[seen] author={message.author} '
            f'author_id={message.author.id} '
            f'is_bot={message.author.bot} '
            f'guild={guild_name} '
            f'channel={channel_name} '
            f'content={message.content!r}'
        )


intents = discord.Intents.default()
intents.message_content = True

client = Client(intents=intents)
client.run(os.environ['DISCORD_TOKEN'])
