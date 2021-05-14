import asyncio
import os
import configparser
from datetime import datetime, timedelta

import discord
from discord.ext import tasks


config = configparser.ConfigParser()
config.read('config.ini', 'UTF-8')
token = os.environ.get('DISCORD_TOKEN') or config.get('discord', 'bot_token')
idea_channel_id = config.getint('discord', 'from_channel_id')
reaction_channel_id = config.getint('discord', 'to_channel_id')
super_to_channel_id = config.getint('discord', 'super_to_channel_id')
super_from_channels_id = config.get('discord', 'super_from_channels_id').replace(' ', '').split(',')
super_users_id = config.get('discord', 'super_users_id').replace(' ', '').split(',')
archive_to_channel_id = config.getint('discord', 'archive_to_channel_id')
archive_from_channels_id = config.get('discord', 'archive_from_channels_id').replace(' ', '').split(',')
archive_users_id = config.get('discord', 'archive_users_id').replace(' ', '').split(',')
good = config.get('discord', 'good')
bad = config.get('discord', 'bad')
info = config.get('discord', 'info')
archive = config.get('discord', 'archive')


class BotClient(discord.Client):
    good_channel = ''
    super_from_channels = []
    super_to_channel = ''
    archive_from_channels = []
    archive_to_channel = ''
    on_edit_dm = {}
    on_edit_message = {}
    on_edit_member = {}
    bumped_message = {}
    use_super = True
    use_archive = True

    async def on_ready(self):
        BotClient.good_channel = BotClient.get_channel(self, reaction_channel_id)
        if not super_from_channels_id[0] == 0:
            for super_from in super_from_channels_id:
                BotClient.super_from_channels.append(BotClient.get_channel(self, int(super_from)))
        else:
            BotClient.use_super = False
        if super_users_id[0] == 0:
            BotClient.use_super = False
        if not super_to_channel_id == 0:
            BotClient.super_to_channel = BotClient.get_channel(self, super_to_channel_id)
        else:
            BotClient.use_super = False
        if not archive_to_channel_id == 0:
            BotClient.archive_to_channel = BotClient.get_channel(self, archive_to_channel_id)
        if not archive_from_channels_id[0] == 0:
            for archive_from in archive_from_channels_id:
                BotClient.archive_from_channels.append(BotClient.get_channel(self, int(archive_from)))
        print("Botが起動しました")
        BotClient.check_expired_post.start(BotClient)

    # 2週間経過したメッセージを消去する（1日ごとに実行）
    @tasks.loop(hours=24)
    async def check_expired_post(self):
        today = datetime.now()
        two_weeks = today - timedelta(weeks=2)
        async for message in BotClient.good_channel.history(before=two_weeks):
            await message.delete()

    # リアクションされたとき
    async def on_raw_reaction_add(self, reaction):
        channel_id = reaction.channel_id
        # 補足に対してのキャンセル機能
        if reaction.user_id in BotClient.on_edit_dm.keys():
            if reaction.message_id == BotClient.on_edit_dm[reaction.user_id].id and \
                    reaction.emoji.name == bad:
                message = BotClient.on_edit_dm[reaction.user_id]
                await message.delete()
                member = BotClient.on_edit_member[reaction.user_id]
                BotClient.on_edit_dm.pop(reaction.user_id)
                content = '企画案への補足を中止しました'
                await member.send(content=content)
                return
        if reaction.member is None or reaction.member.bot:
            return
        if channel_id == idea_channel_id or\
                (channel_id != reaction_channel_id and
                 channel_id != super_to_channel_id and
                 str(channel_id) in super_from_channels_id):
            await BotClient.on_from_channel(self, reaction)
        elif channel_id == reaction_channel_id:
            await BotClient.on_reaction_channel(self, reaction)
        if str(channel_id) in archive_from_channels_id and\
                str(reaction.member.id) in archive_users_id:
            await BotClient.on_archive_channel(self, reaction)

    # アイデアチャンネルでいいねが押された時の処理
    async def on_from_channel(self, reaction):
        emoji = reaction.emoji.name
        channel = BotClient.get_channel(self, reaction.channel_id)
        if emoji != good:
            return
        message_id = reaction.message_id
        message = await channel.fetch_message(message_id)
        member = await message.guild.fetch_member(message.author.id)
        author_id = member.id
        message_url = message.jump_url

        async for msg in BotClient.good_channel.history():
            if not msg.embeds:
                continue
            embed = msg.embeds[0]
            if not embed.fields:
                continue
            supporter_field_pos = len(embed.fields) - 1
            if not supporter_field_pos > 0:
                continue
            if message_url in embed.fields[supporter_field_pos].value:
                await BotClient.send_good(self, msg.id, reaction.member)
                return
        date = message.created_at.strftime('%Y/%m/%d')
        attachment_files = []
        for attachment in message.attachments:
            attachment_files.append(await attachment.to_file())

        embed = discord.Embed(title=member.display_name + ' の企画案',
                              description=message.content,
                              color=discord.Colour.green())
        embed.add_field(name='👍 いいね',
                        value='<@' + str(reaction.member.id) + '>',
                        inline=False)
        embed.add_field(name='💡 元ネタ',
                        value='<@' + str(author_id) + '> [' + date + ' の企画](' + message_url + ')より',
                        inline=False)
        if BotClient.use_super and str(reaction.member.id) in super_users_id:
            if str(reaction.channel_id) in super_from_channels_id:
                await BotClient.super_to_channel.send(embed=embed, files=attachment_files)
                return
        sent_message = await BotClient.good_channel.send(embed=embed, files=attachment_files)
        await sent_message.add_reaction(good)
        await sent_message.add_reaction(bad)
        await sent_message.add_reaction(info)

    # リアクションチャンネルでリアクションが押された時の処理
    async def on_reaction_channel(self, reaction):
        emoji = reaction.emoji.name
        if emoji == good:
            await BotClient.on_good_reaction(self, reaction)
        elif emoji == bad:
            await BotClient.on_bad_reaction(self, reaction)
        elif emoji == info:
            await BotClient.on_info_reaction(self, reaction)

    # いいね時の処理
    async def send_good(self, message_id, member):
        message = await BotClient.good_channel.fetch_message(message_id)
        member_id = str(member.id)
        is_newest = False
        has_name = False
        embed = message.embeds[0]
        link_pos = len(embed.fields) - 1
        pos_fix = 1
        damedane_pos = link_pos - 1
        damedane = ''
        damedaname = ''
        if 'だめだね' in embed.fields[damedane_pos].name:
            damedane = embed.fields[damedane_pos].value
            damedaname = embed.fields[damedane_pos].name
            pos_fix = 2
        supporter_pos = link_pos - pos_fix
        supporter = embed.fields[supporter_pos].value
        if member_id not in supporter:
            if member_id in damedane:
                damedane = damedane.replace('<@' + member_id + '>', '')
                embed.remove_field(damedane_pos)
                if len(damedane) != 0:
                    embed.insert_field_at(damedane_pos,
                                          name=damedaname,
                                          value=damedane,
                                          inline=False)
                await message.edit(embed=embed)
                await message.remove_reaction(good, member)
                return
            else:
                embed.remove_field(supporter_pos)
                supporter += '<@' + member_id + '>'
                embed.insert_field_at(supporter_pos,
                                      name='👍 いいね',
                                      value=supporter,
                                      inline=False)
        else:
            has_name = True
        attachment_files = []
        for attachment in message.attachments:
            attachment_files.append(await attachment.to_file())
        if BotClient.use_super:
            if member_id in super_users_id:
                await BotClient.super_to_channel.send(embed=embed, files=attachment_files)
                await message.delete()
                return

        # 最新の投稿チェック
        async for msg in BotClient.good_channel.history(limit=1, oldest_first=False):
            if msg.id == message_id:
                is_newest = True
        if is_newest:
            if not has_name:
                await message.edit(embed=embed)
            await message.remove_reaction(good, member)
        else:
            sent_message = await BotClient.good_channel.send(embed=embed, files=attachment_files)
            await sent_message.add_reaction(good)
            await sent_message.add_reaction(bad)
            await sent_message.add_reaction(info)
            BotClient.bumped_message[message_id] = sent_message.id
            keys = [k for k, v in BotClient.on_edit_message.items() if v == message]
            if len(keys) > 0:
                for key in keys:
                    BotClient.on_edit_message[key] = sent_message
            await message.delete()

    # いいねのリアクションがいいねチャンネルでされたとき
    async def on_good_reaction(self, reaction):
        message_id = reaction.message_id
        await BotClient.send_good(self, message_id, reaction.member)

    # バッドリアクションがいいねチャンネルでされたとき
    async def on_bad_reaction(self, reaction):
        emoji = reaction.emoji.name
        member_id = str(reaction.member.id)
        message_id = reaction.message_id
        message = await BotClient.good_channel.fetch_message(message_id)
        embed = message.embeds[0]
        link_pos = len(embed.fields) - 1
        pos_fix = 1
        damedane_pos = link_pos - pos_fix
        damedane = ''
        if 'だめだね' in embed.fields[damedane_pos].name:
            pos_fix = 2
            damedane = embed.fields[damedane_pos].value
        supporter_pos = link_pos - pos_fix

        # スーパーユーザーの処理
        if BotClient.use_super and member_id in super_users_id:
            content = '<@' + str(reaction.member.id) + '>によって没になりました'
            await message.remove_reaction(emoji, reaction.member)
            title = '~~' + embed.title + '~~'
            bad_embed = discord.Embed(title=title,
                                      description=embed.description,
                                      color=discord.Colour.red())
            bad_embed.add_field(name=embed.fields[supporter_pos].name,
                                value=embed.fields[supporter_pos].value,
                                inline=False)
            if 'だめだね' in embed.fields[link_pos].name:
                bad_embed.add_field(name=embed.fields[link_pos].name,
                                    value=embed.fields[link_pos].value,
                                    inline=False)
            bad_embed.add_field(name=embed.fields[link_pos].name,
                                value=embed.fields[link_pos].value,
                                inline=False)
            await message.delete()
            await BotClient.good_channel.send(content=content, embed=bad_embed)
            return

        supporter = embed.fields[supporter_pos].value
        if member_id in supporter:
            field_name = embed.fields[supporter_pos].name
            embed.remove_field(supporter_pos)
            supporter = supporter.replace('<@' + member_id + '>', '')
            if len(supporter) == 0:
                await message.delete()
            else:
                emoji = reaction.emoji.name
                embed.insert_field_at(supporter_pos,
                                      name=field_name,
                                      value=supporter,
                                      inline=False)
                await message.edit(embed=embed)
                await message.remove_reaction(emoji, reaction.member)
        else:
            if len(damedane) != 0:
                embed.remove_field(damedane_pos)
                damedane_pos = damedane_pos - 1
            if member_id not in damedane:
                damedane += '<@' + member_id + '>'
                embed.insert_field_at(damedane_pos + 1,
                                      name='👎 だめだね～',
                                      value=damedane,
                                      inline=False)
                await message.edit(embed=embed)
            await message.remove_reaction(emoji, reaction.member)

    # 補足追加処理
    async def on_info_reaction(self, reaction):
        explanation_wait_time = 1.0 * 60.0 * 10.0
        emoji = reaction.emoji.name
        content = '企画案の補足説明を10分以内に記載して送信してください(画像も添付できます)\n' \
                  '補足を中止したい場合は「' + bad + '」のリアクションをすると中止されます。'
        exp = ''
        old_attachment_files = []
        new_attachment_files = []
        attachments = []
        message_id = reaction.message_id
        message = await BotClient.good_channel.fetch_message(message_id)
        await message.remove_reaction(emoji, reaction.member)
        for attachment in message.attachments:
            attachments.append(attachment)
            old_attachment_files.append(await attachment.to_file())
        embed = message.embeds[0]

        # DM関連の処理
        if reaction.member.id in BotClient.on_edit_dm.keys():
            old_dm = BotClient.on_edit_dm[reaction.member.id]
            try:
                await old_dm.delete()
            except discord.errors.NotFound:
                pass
            BotClient.on_edit_dm.pop(reaction.member.id)
        if reaction.member.id in BotClient.on_edit_message.keys():
            BotClient.on_edit_message.pop(reaction.member.id)
        if reaction.member.id in BotClient.on_edit_member.keys():
            BotClient.on_edit_member.pop(reaction.member.id)

        dm = await reaction.member.send(content=content, embed=embed, files=old_attachment_files)
        await dm.add_reaction(bad)

        # 編集中メッセージとしてdictに追加
        BotClient.on_edit_dm[reaction.member.id] = dm
        BotClient.on_edit_message[reaction.member.id] = message
        BotClient.on_edit_member[reaction.member.id] = reaction.member

        # 補足追加時のメッセージ待ち処理
        def add_explanation(msg):
            if not msg.author.bot \
                    and msg.channel.type == discord.ChannelType.private \
                    and msg.author.id == reaction.member.id:
                nonlocal exp, attachments
                exp = msg.content + ' by <@' + str(reaction.member.id) + '>'
                for attach in msg.attachments:
                    attachments.append(attach)
                return True
        try:
            await self.wait_for('message', timeout=explanation_wait_time, check=add_explanation)
        except asyncio.TimeoutError:
            if dm == BotClient.on_edit_dm[reaction.user_id]:
                await dm.delete()
        else:
            if message_id == BotClient.on_edit_message[reaction.member.id].id or\
               BotClient.bumped_message[message_id] == BotClient.on_edit_message[reaction.member.id].id:
                embed.insert_field_at(0, name='✏ 補足', value=exp, inline=False)
                for attachment in attachments:
                    new_attachment_files.append(await attachment.to_file())
                content = '企画案の補足を追記しました👍'

                try:
                    if message_id not in BotClient.bumped_message.keys():
                        await message.delete()
                    else:
                        await BotClient.on_edit_message[reaction.member.id].delete()
                        BotClient.bumped_message.pop(message_id)
                    await dm.delete()
                    sent_message = await BotClient.good_channel.send(embed=embed, files=new_attachment_files)
                    await sent_message.add_reaction(good)
                    await sent_message.add_reaction(bad)
                    await sent_message.add_reaction(info)
                    BotClient.on_edit_dm.pop(reaction.member.id)
                    BotClient.on_edit_member.pop(reaction.member.id)
                    BotClient.on_edit_message.pop(reaction.member.id)
                except discord.errors.NotFound:
                    content = '上記の企画案の補足に失敗しました。\n' \
                              '補足を書いている最中に誰かが企画案を移動させたか、消された可能性があります。\n' \
                              'もう一度、補足したい企画案に「' + info + '」リアクションを付けて試してください。'
                await reaction.member.send(content=content)

    # 完了チャンネルでアーカイブが押された時の処理
    async def on_archive_channel(self, reaction):
        emoji = reaction.emoji.name
        channel = BotClient.get_channel(self, reaction.channel_id)
        if emoji != archive:
            return
        message_id = reaction.message_id
        message = await channel.fetch_message(message_id)

        date = message.created_at.strftime('%Y/%m/%d')
        attachment_files = []
        for attachment in message.attachments:
            attachment_files.append(await attachment.to_file())

        embed = discord.Embed(description=message.content,
                              color=discord.Colour.green())
        embed.add_field(name='💡 投稿日時',
                        value='[' + date + ' の投稿]',
                        inline=False)

        await BotClient.archive_to_channel.send(embed=embed, files=attachment_files)
        await message.delete()


client = BotClient()
client.run(token)

