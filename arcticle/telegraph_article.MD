![](https://telegra.ph/file/b761c26d98a7b56b59160.png)

В этой статье мы с вами напишем бота, который будет загружать картинку пользователя на telegra.ph и
возвращать прямую ссылку на фото. Это может быть полезно, например, для создания скрытых
c [preview](https://telegram.org/blog/link-preview), ссылок на фото или добавления thumb_url
к [InlineQueryResultArticle](https://core.telegram.org/bots/api#inlinequeryresultarticle).

**Статья условно поделена на две части, в первой части мы просто встраиваем пакет для работы с
телеграфом в нашего бота, а во второй мы с нуля напишем свой сервис для работы с телеграфом
используя `aiohttp` и `pydantic`(этот же сервис был использован в первой части). Вы можете
пропустить вторую часть, если она вам не интересна и сразу же взять готовый код с репозитория.**

---

# Результат работы

![Результат работы](https://telegra.ph/file/071825eeb0f329b588774.png)

Как мы видим, после того, как мы отправляем боту картинку, бот генерирует и возвращает нам ссылку на
эту самую картинку на telegra.ph, которая имеет удобный предпросмотр.

В нашем хендлере обработка будет ну уж очень лаконичная🙃:

```python
from aiogram import types

from tgbot.integrations.telegraph.abstract import FileUploader


async def handle_photo_upload(message: types.Message, file_uploader: FileUploader):
    photo = message.photo[-1]
    await message.bot.send_chat_action(message.chat.id, 'upload_photo')
    uploaded_photo = await file_uploader.upload_photo(photo)
    await message.answer(text=uploaded_photo.link)
```

# Подключение сервиса для работы с телеграфом в новый шаблон

Итак, давайте подключим сервис для работы с телеграфом, подробности реализации которого раскрыты
позже в статье. Для интеграций давайте создадим новый middleware, поместим его
в `middlewares/integration.py` и назовем его `IntegrationMiddleware`, в котором вы можете создавать
и передавать в хендлеры не только классы для интеграции с телеграфом, а так же компоненты(классы)
для работы с различными сервисами, CRM, платежными системами и другим, а реализации помещать в
пакет `integrations/<название интеграции>`, что несомненно будет хорошей практикой. Готовый код вы
можете найти в конце этой статьи.

```python
from typing import Dict, Any

from aiogram.dispatcher.middlewares import LifetimeControllerMiddleware
from aiogram.types.base import TelegramObject

from tgbot.integrations.telegraph.abstract import FileUploader


class IntegrationMiddleware(LifetimeControllerMiddleware):
    skip_patterns = ["error", "update"]

    def __init__(self, uploader: FileUploader):
        super().__init__()
        self._uploader = uploader

    async def pre_process(self, obj: TelegramObject, data: Dict[Any, Any], *args: Any):
        data["file_uploader"] = self._uploader
```

Так же теперь нам нужно создать объект `TelegraphService` и передать его в
конструктор `IntegrationMiddleware`:

```python
file_uploader = TelegraphService()
dp.middleware.setup(IntegrationMiddleware(file_uploader))
```

Однако, это ещё не всё😁 Нам потребуется закрывать сессию с помощью метода `close`, который есть
у `TelegraphClient`, но в мидлвари не самое подходящее место, так как сессию бы желательно не
закрывать после каждого апдейта. Хорошим решением будет передать `FileUploader` не только в
конструктор middleware, а так же в объект бота, чтобы далее можно было получить его в
функции `on_shutdown`

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.fsm_storage.redis import RedisStorage2

from tgbot.config import load_config
from tgbot.filters.admin import AdminFilter
from tgbot.handlers.admin import register_admin
from tgbot.handlers.photos import register_photo_handlers
from tgbot.handlers.user import register_user
from tgbot.integrations.telegraph import TelegraphService, FileUploader
from tgbot.middlewares.db import DbMiddleware
from tgbot.middlewares.integration import IntegrationMiddleware

logger = logging.getLogger(__name__)


async def on_shutdown(dp: Dispatcher):
    file_uploader: FileUploader = dp.bot["file_uploader"]
    await file_uploader.close()


def register_all_middlewares(dp):
    dp.setup_middleware(DbMiddleware())


def register_all_filters(dp):
    dp.filters_factory.bind(AdminFilter)


def register_all_handlers(dp):
    register_admin(dp)
    register_user(dp)
    register_photo_handlers(dp)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format=u'%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s',
    )
    logger.info("Starting bot")
    config = load_config(".env")

    storage = RedisStorage2() if config.tg_bot.use_redis else MemoryStorage()
    bot = Bot(token=config.tg_bot.token, parse_mode='HTML')
    file_uploader = TelegraphService()
    dp = Dispatcher(bot, storage=storage)
    dp.middleware.setup(IntegrationMiddleware(file_uploader))

    bot["file_uploader"] = file_uploader
    bot['config'] = config

    register_all_middlewares(dp)
    register_all_filters(dp)
    register_all_handlers(dp)

    # start
    try:
        await dp.start_polling()
    finally:
        await dp.storage.close()
        await dp.storage.wait_closed()
        await bot.session.close()
        await on_shutdown(dp)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.error("Bot stopped!")
```

---

# Реализация собственного модуля для работы с Telegraph API

Итак, теперь давайте кратко обсудим как мы можем написать такую обвертку и шаг за шагом попробуем
написать что-то своё😎

## Полезно знать

При реализации сервиса для работы с телеграфом мы так или иначе будем стыкаться с различными
понятиями и фишками. Хотелось бы сразу объяснить их суть, что бы вы не входили в ступор.

### Зачем нужны абстракции?

* Мы абстрагируемся от реальной реализации класса и всего что связано с этим сервисом собственной
  абстракцией, которая поможет нам легко изменить сервис для загрузки файлов, если вам по каким-то
  причинам не подошёл телеграф, к примеру на популярный среди разработчиков `AWS S3` или любое
  другое хранилище файлов, просто унаследовав абстрактный класс и имлементировав все нужные методы.

### Небольшие советы по работе с `aiohttp`

* Следуя документации `aiohttp` и [прислушиваясь к рекомендациям её разработчика](https://www.youtube.com/watch?v=5NrnBu1vcKo) не следует создавать
  сессию  `aiohttp.ClientSession` на каждый запрос, собственно использовать контекстные менеджеры,
  лучше хранить её в единичном экземпляре где-то в классе. С помощью функций данная рекомендация не
  может быть корректно реализована. Однако утверждение про контекстные менеджеры не всегда является
  верным, например для единичных скриптов-парсеров, где не так важен жизненный цикл нашей сессии.
* Не нужно создавать экземпляр `aiohttp.ClientSession` вне асинхронных функций, это приводит к
  проблемам и непредвиденным ошибкам

## Реализация абстракции для загрузки фотографий

Начнем с написания собственной абстракции, в новом шаблоне мы можем написать данную обвертку и
поместить её в папку `integrations`, которой в шаблоне нет, однако мы же всегда можем её создать😉.
Давайте создадим абстрактный класс и там напишем 2 абстрактных метода:

```python
import abc

from aiogram.types import PhotoSize

from tgbot.integrations.telegraph.types import UploadedFile


class FileUploader(abc.ABC):

    async def upload_photo(self, photo: PhotoSize) -> UploadedFile:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError
```

Выглядит достаточно красиво и лаконично, метод `upload_photo` принимает фотографию и загружает её на
какой-то сервис(в нашем случае телеграф).

## Модели нашей обертки

Далее, стоило бы понять, что это за странный класс `UploadedFile`, в нашем случае это `pydantic`
модель, которая валидирует ответ от телеграфа и конструирует нам ссылку к загруженной фотографии.

### Небольшое отступление про библиотеку `pydantic`

[Pydantic](https://pydantic-docs.helpmanual.io/), в общем и целом, помогает нам распарсить `json`,
поддерживает древовидные структуры, валидацию по аннотациям аттрибутов а также кастомные валидаторы
и многое другое. В нашем случае мы задеклалировали 1 аттрибут `link`, который должен быть строкой, в
ином случае pydantic пробросит ошибку валидации `ValidationError`.

Что же такое `alias` и зачем он нужен?

Alias - это "псевдоним для поля", то есть к примеру API отдает нам ответ `{"src": "some_data"}`, и
мы не хотим чтобы имя аттрибута модели было `src`, потому что оно кажется нам каким-то странным и
абстрактным или просто по каким-то другим причинам, поэтому дефолтным значением для аттрибута будет
некий `Field`, куда мы передаем параметр `alias`, чтобы дать понять pydantic, что мы хотим данные по
ключу `src` распарсить и занести в аттрибут `link`.

Валидатор `link_validator` в нашем случае просто формирует ссылку.

```python
from pydantic import Field, BaseModel, validator

from tgbot.integrations.telegraph.config import BASE_TELEGRAPH_API_LINK


class UploadedFile(BaseModel):
    link: str = Field(..., alias="src")

    @validator("link")
    def link_validator(cls, value: str):
        return BASE_TELEGRAPH_API_LINK.format(endpoint=value)
```

## Реализация клиента для работы с телеграфом

```python
import secrets
from io import BytesIO
from typing import Optional

import aiohttp
from aiogram.types import PhotoSize

from tgbot.integrations.telegraph.abstract import FileUploader
from tgbot.integrations.telegraph.config import BASE_TELEGRAPH_API_LINK
from tgbot.integrations.telegraph.exceptions import TelegraphAPIError
from tgbot.integrations.telegraph.types import UploadedFile


class Telegraph(FileUploader):
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def upload_photo(self, photo: PhotoSize) -> UploadedFile:
        form = aiohttp.FormData(quote_fields=False)
        downloaded_photo = await photo.download(destination_file=BytesIO())
        form.add_field(secrets.token_urlsafe(8), downloaded_photo)

        session = await self.get_session()
        response = await session.post(
            BASE_TELEGRAPH_API_LINK.format(endpoint="upload"),
            data=form
        )
        if not response.ok:
            raise TelegraphAPIError(
                "Something went wrong, response from telegraph is not successful. "
                f"Response: {response}"
            )
        json_response = await response.json()
        return UploadedFile.parse_obj(json_response)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            new_session = aiohttp.ClientSession()
            self._session = new_session
        return self._session

    async def close(self) -> None:
        if self._session is None:
            return None
        await self._session.close()
```

Давайте разберемся с этой реализаций поподробнее. Сразу же может возникнуть вопрос, почему мы сразу
же не инициализируем сессию прямо в конструкторе? Мы это делаем не из-за того, что нам просто так
захотелось, а потому что сессия `aiohttp.ClientSession` должна быть создана в корутине, то есть в
функции с приставкой `async`, иначе мы получим кучу ошибок и проблем в дальнейшем, поэтому мы
реализовываем метод `get_session`, который будет создавать новую сессию, если она ещё не создана.

Теперь рассмотрим метод `upload_photo`, он получает объект `PhotoSize`, который мы импортировали из
aiogram и в самом методе скачивает эту фотографию и добавляет её в некую форму, чтобы отправить
запрос к API. Так же мы видим проверку `if not response.ok` и если что-то пошло не так и телеграф
вернул нам статус код, который не равен 200 и последующий парсинг `json` ответа. Давайте поместим
нашу реализацию в модуль `integrations/telegraph/client.py`.

## Ошибки и константные значения нашего сервиса

Отлично, осталось разобраться только с непонятной ошибкой `TelegraphAPIError` и
константой `BASE_TELEGRAPH_API_LINK`. Их реализации уж очень просты, различные ошибки работы сервиса
мы поместим в модуль `integrations/telegraph/exceptions.py`, а константные значения по
пути `integrations/telegraph/config.py`.

Содержимое модуля `integrations/telegraph/exceptions.py`:

```python
class TelegraphAPIError(Exception):
    ...
```

Содержимое модуля `integrations/telegraph/config.py`:

```python
BASE_TELEGRAPH_API_LINK = "https://telegra.ph/{endpoint}"
```

# Заключение

Получение прямой ссылки на изображение, отправленное пользователем — частая задача, решение которой
не кажется таким уж интуитивным. Такие ссылки могут использоваться для миниатюры в статье инлайн
ответа, для того, чтобы спрятать невидимую ссылку с картинкой в сообщении или просто отправить
картинку в чат без права на отправку фото 🌚.

В этой статье мы разобрались, как можно реализовать отправку изображения пользователя на telegra.ph,
и получение прямой ссылки на него, а так же немного затронули тему разработки собственного пакета
для работы с сервисом телеграф.

**Код данной статьи вы можете найти в
нашем** [github репозитории](https://github.com/GLEF1X/botfather_articles).

В статье за основу
взята [новая структура для написания телеграм ботов на базе aiogram](https://github.com/Latand/tgbot_template)
.

