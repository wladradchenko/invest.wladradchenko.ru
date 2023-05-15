[![Price](https://img.shields.io/badge/price-FREE-0098f7.svg)](https://github.com/wladradchenko/invest.wladradchenko.ru/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/aiohttp.svg)](https://badge.fury.io/py/aiohttp)
[![GitHub package version](https://img.shields.io/github/v/release/wladradchenko/invest.wladradchenko.ru?display_name=tag&sort=semver)](https://github.com/wladradchenko/invest.wladradchenko.ru)
[![License: MIT v1.0](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wladradchenko/invest.wladradchenko.ru/blob/main/LICENSE)

<div id="top"></div>

<br />
<div align="center">
  <a href="https://github.com/wladradchenko/invest.wladradchenko.ru">
    <img src="logo/main.png" alt="Logo" width="150" height="150">
  </a>

  <h3 align="center">Tinkoff Pie Calculator</h3>

  <p align="center">
    Документация о проекте
    <br/>
    <br/>
    <br/>
    <a href="https://github.com/wladradchenko/invest.wladradchenko.ru/issues">Сообщить об ошибке</a>
    ·
    <a href="https://github.com/wladradchenko/invest.wladradchenko.ru/issues">Запросить функцию</a>
  </p>
</div>


<!-- ABOUT THE PROJECT -->
## О проекте / About The Project

Веб-сервис на Aiohttp созданный для работы с [Tinkoff Invest](https://github.com/Tinkoff/invest-python), при помощи AsyncClient.
Позволяет распределить указанный капитал на пирог выбранного индекса Московской биржи из открытого API. Работает сервис с акциями Т+: Акции и ДР - безадрес в RUB.

Если происходит работа со счетом Тинькофф, тогда распределение капитала учитывает бумаги, которые находятся в портфеле. Если они не входят в индекс, тогда учитываются к продаже.

Возможности открытой версии:
* Распределение капитала на пирог,
* Перераспределение акций на пирог (продажа / покупка),
* История сделок счёта,
* Создание пользовательского индекса,
* Фоновые задачи для получения исторических свечей и работы с ними (применение стратегии трейдинга/создание графиков/расчет индикаторов),
* Управление приложением через Telegram чат.

<hr>

An Aiohttp web service built to work with [Tinkoff Invest](https://github.com/Tinkoff/invest-python) using AsyncClient.
Allows you to allocate capital to the pie of the selected Moscow Exchange index from the open API. The service works with T + shares: Shares and DR - no address in RUB.

Features of the open version:
* Distribution of capital per pie,
* Redistribution of shares per pie (sale / purchase),
* Account transaction history,
* Creating a custom index,
* Background tasks for obtaining historical candles and working with them (using a trading strategy / creating charts / calculating indicators),
* Application control via Telegram chat.

<p align="right">(<a href="#top">вернуться наверх / back to top</a>)</p>

<!-- FEATURES -->
## Запуск / Setup

```
pip install -r requirements.txt
```

В conf.toml
```
database="sqlite.db"

[tinkoff]
readonly = "TOKEN"  # token Tinkoff readonly

[telegram]
token = "TOKEN"  # token telegram bot
chat_id = 0  # chat for messages from bot
```

Как получить Tinkoff [токен](https://tinkoff.github.io/investAPI/token/).
Как получить Telegram [токен](https://core.telegram.org/bots/api#authorizing-your-bot).
Как узнать [Chat ID](https://core.telegram.org/bots/api#getchatmember).

Запуск
```
python run.py
```

<hr>

```
pip install -r requirements.txt
```

In conf.toml
```
database="sqlite.db"

[tink off]
readonly = "TOKEN" # token Tinkoff readonly

[telegram]
token = "TOKEN" # token telegram bot
chat_id = 0 # chat for messages from bot
```

How to get Tinkoff [token](https://tinkoff.github.io/investAPI/token/).
How to get Telegram [token](https://core.telegram.org/bots/api#authorizing-your-bot).
How to find out [Chat ID](https://core.telegram.org/bots/api#getchatmember).

launch
```
python run.py
```

<!-- DIFFERENCES -->
## Различия / Differences

| | Открытый репозиторий | Закрытый репозиторий | Как реализовать самому |
| ------------- | ------------- | ------------- | ------------- |
| БД / DB  | SQLite  | MariaDB  | [MariaDB](https://github.com/aio-libs/aiomysql) |
| Расчет индикаторов / Calculation of indicators | -  | + | [Ta-Lib](https://github.com/TA-Lib/ta-lib-python) |
| Анализ временных рядов / Time series analysis | -  | + | [Прогнозирование временных рядов с помощью рекуррентных нейронных сетей](https://habr.com/ru/post/495884/) |
| Автоматический трейдинг / Automatic trading | -  | + | [Algorithmic Trading Using Python](https://www.youtube.com/watch?v=xfzGZB4HhEE) |
| Оповещение в Telegram / Notification in Telegram | -  | + | [sendMessage](https://core.telegram.org/bots/api#sendmessage) |

<!-- VIDEO -->
## Видео / Video

[![Watch the video](https://img.youtube.com/vi/KvgMHC8Wfgk/maxresdefault.jpg)](https://youtu.be/KvgMHC8Wfgk)

<!-- CONTACT -->
## Контакт / Contact

Автор / Owner: [Wladislav Radchenko](https://github.com/wladradchenko/)

Почта / Email: [i@wladradchenko.ru](i@wladradchenko.ru)

Проект / Code: [https://github.com/wladradchenko/invest.wladradchenko.ru](https://github.com/wladradchenko/invest.wladradchenko.ru)

Сайт проекта / Project web-site: [invest.wladradchenko.ru](https://invest.wladradchenko.ru)

Мобильное приложение / Mobile app: [Google Play](https://play.google.com/store/apps/details?id=ru.wladradchenko)

<p align="right">(<a href="#top">вернуться наверх / back to top</a>)</p>
