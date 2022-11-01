from aiogram import Dispatcher
from aiogram.types import Message


async def user_start(message: Message):
    await message.reply(f"Hey, {message.from_user.first_name}!")
    await message.answer('Send me a photo and I will upload it to telegra.ph')
    await message.answer('Created by @HeavyWay')


def register_user(dp: Dispatcher):
    dp.register_message_handler(user_start, commands=["start"], state="*")
