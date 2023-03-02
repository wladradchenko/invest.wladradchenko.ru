"""
Run application
"""
"""
Web and baseline
"""
from datetime import datetime
from aiohttp import web
import asyncio
import aiosqlite
import requests
import toml
"""
Logger
"""
import logging
import logging.handlers as handlers

"""
Tinkoff
"""
import socketio
from tinkoff.invest.utils import now, timedelta
from tinkoff.invest.retrying.settings import RetryClientSettings
from tinkoff.invest.retrying.aio.client import AsyncRetryingClient
from tinkoff.invest import AsyncClient, GetOperationsByCursorRequest, CandleInterval, AioRequestError


class Logger:
    """
    Logger for Tinkoff background task
    """
    MAX_BYTES = 30  # max bytes size of log file
    BACKUP_COUNT = 0  # num backup lof files if get limit size

    def __init__(self) -> None:
        """
        Initialization
        """
        formatter = logging.Formatter('%(asctime)s [%(process)d] %(levelname)s - %(message)s')

        logger = logging.getLogger("logger")
        logger.setLevel(logging.INFO)

        logger_handler = logging.handlers.RotatingFileHandler(
            filename="logger.log",
            mode='a',
            maxBytes=self.MAX_BYTES,
            backupCount=self.BACKUP_COUNT
        )

        logger_handler.setFormatter(formatter)
        logger_handler.setLevel(logging.INFO)
        logger.addHandler(logger_handler)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(logging.INFO)
        logger.addHandler(console)

        self.logger = logger


class Tinkoff:
    """
    Tinkoff API
    """
    CANDLE_INTERVAL = CandleInterval.CANDLE_INTERVAL_15_MIN  # interval for candles
    CANDLE_DAYS = 30
    EXCHANGE_OPEN_HOUR = 9  # hour than exchange opened for user
    EXCHANGE_CLOSE_HOUR = 20  # hour than exchange closed for user
    INDICATOR_PERIOD = 0  # INDICATOR_PERIOD = 0: DAY, INDICATOR_PERIOD = 1: WEEK

    def __init__(self) -> None:
        """
        Initialization
        """
        self.sio = socketio.AsyncServer(async_mode='aiohttp')
        self.token = None
        self.logger = None
        self.accounts = None
        self.portfolio = None
        self.database = None
        self.candle_interval = {1: 1, 2: 5, 3: 15, 4: 60}  # from 1 minute to 1 hour (without nothing and day)

    def setup(self, application: web.Application) -> None:
        """
        Setup startup and cleanup connection
        :param application: web application
        :return:
        """
        self.sio.attach(application)
        self.sio.start_background_task(self._background_task, application)
        application.on_cleanup.append(self._on_disconnect)

    """REAL ACCOUNT"""

    async def _on_connect(self, application: web.Application):
        """
        Async connection to Tinkoff on
        :param application: web application
        :return:
        """
        self.logger = application["logger"].logger
        self.token = application["config"]["tinkoff"]["readonly"]
        self.database = application["database"]
        async with AsyncClient(self.token) as client:
            self.accounts = await client.users.get_accounts()
            self.accounts = self.accounts.accounts

    async def _background_task(self, application: web.Application) -> None:
        """
        Background task # https://python-socketio.readthedocs.io/en/latest/client.html
        :return:
        """
        auction_close = datetime(1970, 1, 1, self.EXCHANGE_CLOSE_HOUR, 0).time()
        auction_open = datetime(1970, 1, 1, self.EXCHANGE_OPEN_HOUR, 0).time()
        await self._on_connect(application)  # application.on_startup.append(self._on_connect)
        accounts = [accounts.id for accounts in self.accounts if int(accounts.access_level) not in [0, 3]]
        print("", flush=True)
        self.logger.info(msg='Background task start!')
        # info user that is week now

        while True:
            self.logger.info(msg='Listen parameters')
            await application["telegram"].listen(application=application)

            if auction_open <= datetime.now().time() <= auction_close:
                self.logger.info(msg='Get current securities for accounts...')
                portfolio = []
                for account in accounts:
                    # get only position and find uniq
                    *_, positions = await self.get_portfolio(account_id=account)
                    positions = [(p.figi, p.quantity.units,
                                  self.float_convert(p.average_position_price.units, p.average_position_price.nano),
                                  self.float_convert(p.current_price.units, p.current_price.nano)) for p in positions]
                    portfolio += positions
                portfolio = [t for i, t in enumerate(portfolio) if not any(t[0] == p[0] for p in portfolio[:i])]
                self.logger.info(msg="Get candles...waiting")
                """
                HISTORICAL CANDLES
                """
                candles = asyncio.gather(*[self.get_candles(figi=p[0], days=self.CANDLE_DAYS, interval=self.CANDLE_INTERVAL) for p in portfolio])
                """
                INPUT YOUR FINANCE STRATEGY/INDICATORS/ACTIONS FOR BACKGROUND MESSAGES IN TG
                """

            await self.sio.sleep(60 * 60 * 4)  # sleep 4 hours

    """
    ADD YOUR INDICATORS OR TRADE ALGORITHM
    """

    """
    ACTION TO TINKOFF API
    """
    async def get_portfolio(self, account_id):
        """
        Get account capital. All operration I planned to do in rub
        :param account_id: account id
        :return:
        """
        async with AsyncRetryingClient(self.token,
                                       settings=RetryClientSettings(use_retry=True, max_retry_attempt=2)) as client:
            try:
                portfolio = await client.operations.get_portfolio(account_id=account_id)
            except AioRequestError as err:
                self.logger.warning(msg="Limit on portfolio finish. Use prev data: %s" % err)
                portfolio = self.portfolio

            total_amount_shares = self.float_convert(portfolio.total_amount_shares.units,
                                                     portfolio.total_amount_shares.nano)  # shares

            total_amount_bonds = self.float_convert(portfolio.total_amount_bonds.units,
                                                    portfolio.total_amount_bonds.nano)  # bonds

            total_amount_currencies = self.float_convert(portfolio.total_amount_currencies.units,
                                                         portfolio.total_amount_currencies.nano)  # currencies

            expected_yield = self.float_convert(portfolio.expected_yield.units,
                                                portfolio.expected_yield.nano)  # относительная доходность портфеля в %

            positions = portfolio.positions

        self.portfolio = portfolio  # update
        return total_amount_shares, total_amount_bonds, total_amount_currencies, expected_yield, positions

    async def find_figi(self, query: str, method: str) -> tuple:
        """
        Get figi of securities
        :param query: register number or figi
        :param method: wich param need to get
        :return: figi or None
        """
        async with AsyncRetryingClient(self.token,
                                       settings=RetryClientSettings(use_retry=True, max_retry_attempt=2)) as client:
            try:
                response = await client.instruments.find_instrument(query=query)
                response = response.instruments
            except AioRequestError as err:
                self.logger.error(msg="Problem with find instrument: %s" % err)
                return query, None
            for r in response:
                if r.class_code == 'TQBR':
                    return query, getattr(r, method)
        return query, None

    async def get_last_prices(self, figi: tuple) -> tuple:
        """
        Get last price from tinkoff
        :param figi: figi id
        :return: information about price
        """
        if figi:
            isin, figis = list(zip(*figi))
        else:
            return None, None
        async with AsyncRetryingClient(self.token,
                                       settings=RetryClientSettings(use_retry=True, max_retry_attempt=2)) as client:
            try:
                response = await client.market_data.get_last_prices(figi=figis)
                response = response.last_prices
            except AioRequestError as err:
                self.logger.error(msg="Problem with get last price: %s" % err)
                return None, None
        prices = [self.float_convert(r.price.units, r.price.nano) for r in response]
        return tuple(zip(isin, prices))  # :todo secid and price need return

    async def get_instrument(self, position) -> dict:
        """
        Get parameters by figi and class type TQBR
        :param position: position
        :return: parameters
        """
        figi = position.figi
        async with AsyncRetryingClient(self.token,
                                       settings=RetryClientSettings(use_retry=True, max_retry_attempt=2)) as client:
            try:
                response = await client.instruments.get_instrument_by(id_type=1, class_code='TQBR', id=figi)
            except AioRequestError as err:
                self.logger.error(msg="Problem with get instrument: %s" % err)
                return {}

        response = response.instrument
        if response.class_code != 'TQBR':
            # hidden information about valutes
            return {}
        instrument_type_moex = {"share": 1, "bond": 6}
        parameters = {"SECID": response.ticker, "FIGI": figi, "DB LOTS": position.quantity.units,
                      "DB PRICE": self.float_convert(position.average_position_price.units,
                                                     position.average_position_price.nano),
                      "PREVPRICE": self.float_convert(position.current_price.units, position.current_price.nano),
                      "EXPECTED": self.float_convert(position.expected_yield.units, position.expected_yield.nano),
                      "ISIN": response.isin, "SECNAME": response.name, "CURRENCYID": "RUB",
                      "SECTYPE": instrument_type_moex.get(response.instrument_type)}
        return parameters

    async def get_operations(self, account_id: str, limit: int = 100, cursor: str = '') -> list:
        """
        Get user operations on account with pagination (cursor)
        :param account_id: account id
        :param limit: limit records
        :param cursor: id pagination
        :return:
        """
        async with AsyncRetryingClient(self.token,
                                       settings=RetryClientSettings(use_retry=True, max_retry_attempt=2)) as client:
            try:
                response = await client.operations.get_operations_by_cursor(
                    GetOperationsByCursorRequest(account_id=account_id, limit=limit, cursor=cursor))
            except AioRequestError as err:
                self.logger.error(msg="Problem with get operations: %s" % err)
                return []
        """
        PAGINATION
        has_next = response.has_next
        next_cursor = response.next_cursor
        """
        items = response.items
        return items

    async def get_candles(self, figi: str, days: int, interval: CandleInterval):
        """
        Get candles of figi from set days to now. Need to do sync because limit thread
        :param figi: figi id
        :param days: minus days from now
        :param interval: CandleInterval CANDLE_INTERVAL_1_MIN = 1, CANDLE_INTERVAL_5_MIN = 2
                         CANDLE_INTERVAL_15_MIN = 3, CANDLE_INTERVAL_HOUR = 4, CANDLE_INTERVAL_DAY = 5 (work int)
        :return:
        """
        candles = []
        async with AsyncRetryingClient(self.token,
                                       settings=RetryClientSettings(use_retry=True, max_retry_attempt=2)) as client:
            try:
                async for candle in client.get_all_candles(figi=figi, from_=now() - timedelta(days=days),
                                                           interval=interval):
                    if candle.is_complete:  # признак завершённости свечи, false значит, свеча за текущие интервал ещё сформирована не полностью.
                        candle_open = self.float_convert(candle.open.units, candle.open.nano)
                        candle_close = self.float_convert(candle.close.units, candle.close.nano)
                        candle_low = self.float_convert(candle.low.units, candle.low.nano)
                        candle_high = self.float_convert(candle.high.units, candle.high.nano)
                        candle_volume = candle.volume
                        candle_time = candle.time
                        candles += [
                            (figi, candle_open, candle_close, candle_low, candle_high, candle_volume, candle_time)]
                        # await asyncio.sleep(0.2)
            except AioRequestError as err:
                self.logger.warning(msg=f"Problem with get operations: [{figi}] {err}")
                return []
        return candles

    """
    ACTION TO TINKOFF API
    """
    """REAL ACCOUNT"""

    @staticmethod
    def float_convert(units: int, nano: int) -> float:
        """
        Convert units.nano to float
        :param units: int part
        :param nano: double part
        :return:
        """
        if nano < 0 or units < 0:
            return -float(f"{abs(units)}.{abs(nano)}")
        return float(f"{units}.{nano}")

    async def _on_disconnect(self, application: web.Application) -> None:
        """
        Connection to Tinkoff off
        :param application: web application
        :return:
        """
        await self.sio.disconnect(application)
        self.logger.info(msg='Background task of sio is disconnected')


class Telegram:
    """
    Telegram bot messenger
    FAQ
    Изменяемые параметры:
        Выводить индексы за период,ввести INDICATOR_PERIOD и значение int:
            ДЕНЬ = 0;
            НЕДЕЛЯ = 1.
        Интервал исторических свечей по бумагам, ввести CANDLE_INTERVAL и значение int:
            ИНТЕРВАЛ В 1 МИН = 1;
            ИНТЕРВАЛ В 5 МИН = 2;
            ИНТЕРВАЛ В 15 МИН = 3;
            ИНТЕРВАЛ В 1 ЧАС = 4;
            ИНТЕРВАЛ В 1 ДЕНЬ = 5.
        Исторические свечи промежуток времени, ввести CANDLE_DAYS и значение int.
    """

    def __init__(self) -> None:
        """
        Initialization
        """
        self.token = None
        self.chat = None

    def setup(self, application: web.Application) -> None:
        """
        Setup startup for session
        :param application: web application
        :return:
        """
        application.on_startup.append(self._on_connect)

    async def _on_connect(self, application: web.Application) -> None:
        """
        Initialization bot token and chat id
        :param application: web application
        :return:
        """
        self.token = application["config"]["telegram"]["token"]
        self.chat = application["config"]["telegram"]["chat_id"]

    async def query(self, method: str, **kwargs) -> dict:
        """
        Query to Telegram bot
        :param method: method of API
        :param kwargs: parameters dict (other use for not standard keys)
        :return: response
        """
        url = f"https://api.telegram.org/bot{self.token}/%s?chat_id={self.chat}" % method
        try:
            # action with bot
            response = requests.get(url, params=kwargs).json()
        except requests.exceptions.RequestException as err:
            print("Problem with send message in telegram: ", err)
            return {}
        return response

    async def message(self, text: str) -> None:
        """
        Send message in chat
        :param text: text to send in chat
        :return:
        """
        await self.query(method="sendMessage", text=text)

    async def listen(self, application: web.Application) -> None:
        """
        Listen chat to change parameters
        :param application: web application
        :return:
        """
        response = await self.query(method="getUpdates", offset=-1)
        if not response.get("result") or not isinstance(response.get("result"), list):
            return
        if response["result"][0].get("message") is None:
            return
        if response["result"][0]["message"].get("text"):
            text = response["result"][0]["message"]["text"]

            commands = [t for t in text.split()]
            if "INDICATOR_PERIOD" in text:
                param = "".join(str(commands[i + 1]) if commands[i + 1].isdigit() else str(application["tinkoff"].INDICATOR_PERIOD) for i in range(len(commands)) if "INDICATOR_PERIOD" in commands[i])
                print("New INDICATOR_PERIOD param", param)
                if 0 <= int(param) <= 1:
                    application["tinkoff"].INDICATOR_PERIOD = int(param)
            """YOU CAN ADD ADDITIONAL MESSAGES OR CONTROL PARAMETERS"""


class SQLAccessor:
    """
    SQLite Accessor
    """

    def __init__(self) -> None:
        """
        Initialization
        """
        self.session = None

    def setup(self, application: web.Application) -> None:
        """
        Setup startup and cleanup connection for session
        :param application: web application
        :return:
        """
        application.on_startup.append(self._on_connect)
        application.on_startup.append(self._create_table)  # create tables
        application.on_cleanup.append(self._on_disconnect)

    @staticmethod
    async def insert(session: aiosqlite.connect, table: str, line: dict) -> None:
        """
        Insert line in table
        :param session: open session
        :param table: table name
        :param line: record line
        :return:
        """
        columns = ', '.join(line.keys())
        placeholders = ', '.join('?' * len(line))
        query = f'INSERT INTO {table} ' + '({}) VALUES ({})'.format(columns, placeholders)
        await session.execute(query, tuple(line.values()))
        await session.commit()

    @staticmethod
    async def update(session: aiosqlite.connect, table: str, condition: dict, line: dict) -> None:
        """
        Update lines in table
        :param session: open session
        :param table: table name
        :param condition: condition
        :param line: record line
        :return:
        """
        #:TODO test ones
        sql = f"UPDATE {table}"
        sql += " SET " + ", ".join(f"{k}='{v}'" for k, v in line.items())
        sql += " WHERE " + " AND ".join(f"{k}='{v}'" for k, v in condition.items())
        await session.execute(sql)
        await session.commit()

    async def _on_connect(self, application: web.Application):
        """
        Connection to SQLite on
        :param application: web application
        :return:
        """
        self.config = application["config"]["database"]
        self.session = await aiosqlite.connect(self.config)

    async def _create_table(self, application: web.Application):
        """
        Create table if not exist on create
        :return:
        """
        # secids -eq ticker
        await self.session.execute(
            f'CREATE TABLE IF NOT EXISTS pie (id INTEGER PRIMARY KEY AUTOINCREMENT, indexid CHAR(36) NOT NULL, secids CHAR(36) NOT NULL, shortname CHAR(189) NOT NULL, weight FLOAT NOT NULL,account CHAR(36))')
        await self.session.execute(
            f'CREATE TABLE IF NOT EXISTS indexes (id INTEGER PRIMARY KEY AUTOINCREMENT, indexid CHAR(36) NOT NULL, shortname CHAR(189) NOT NULL, `from` DATE NOT NULL,`till` DATE NOT NULL)')
        await self.session.execute(
            f'CREATE TABLE IF NOT EXISTS securities (id INTEGER PRIMARY KEY AUTOINCREMENT, INDEXID CHAR(36) NOT NULL, SECID CHAR(36) NOT NULL, SECNAME CHAR(90), ISSUESIZE INT, ISIN CHAR(36) NOT NULL, REGNUMBER CHAR(90), CURRENCYID CHAR(12), SECTYPE CHAR(3), LISTLEVEL INT, PREVPRICE FLOAT NOT NULL, PREVWAPRICE FLOAT, LOTSIZE INT NOT NULL, PREVDATE DATE NOT NULL)')
        await self.session.execute(
            f'CREATE TABLE IF NOT EXISTS timeseries (id INTEGER PRIMARY KEY AUTOINCREMENT, dates DATE NOT NULL, figi CHAR(36) NOT NULL, indicators CHAR(36) NOT NULL, action CHAR(10) NOT NULL, price FLOAT NOT NULL, interval INTEGER NOT NULL)')

    async def _on_disconnect(self, _) -> None:
        """
        Connection to SQLite off
        :param _: async off
        :return:
        """
        # delete all empty tables
        if self.session is not None:
            await self.session.close()
            print("Session SQLite is None")


class MOEX:
    """
    MOEX request
    """

    def __init__(self) -> None:
        """
        Initialization
        """
        pass
        # self.indices = ["IMOEX", "MOEX10", "RTSI", "MOEXBMI", "MOEXFN", "MOEXOG", "MOEXMM", "MCXSM", "MOEXCN", "MOEXIT", "MOEXEU", "MOEXCH", "MOEXTL", "MOEXTN", "MOEXINN", "RTSMM", "RTSOG", "RTSCH", "RTSCR", "RTSEU", "RTSIT", "RTSRE", "RTSTL", "RTSTN"]

    @staticmethod
    async def query(method: str, **kwargs):
        """
        Query to ISS MOEX
        :param method: method of API
        :param kwargs: parameters dict (other use for not standard keys)
        :return:
        """
        url = "https://iss.moex.com/iss/%s.json" % method
        try:
            request = requests.get(url, params=kwargs, timeout=1)  #
        except:
            return None
        request.encoding = 'utf-8'
        parse = request.json()
        request.close()  # test this line
        return parse

    @staticmethod
    def flatten(parse: dict, blockname: str):
        """
        Query result to json
        :param parse: query result
        :param blockname: method of API which used
        :return:
        """
        if parse is None:
            return [{}]
        return [{k: r[i] for i, k in enumerate(parse[blockname]['columns'])} for r in parse[blockname]['data']]


class Routes(web.View):
    """
    Pages
    """
    __slots__ = ("name", "types")

    def __init__(self, request: web.Request = None) -> None:
        """
        Initialization
        :param request: request
        """
        super().__init__(request)

    async def main(self, request: web.Request) -> web.Response:
        """
        Main page
        :param request: request
        :return: responce
        """
        session = request.app["database"].session
        post = await request.post()
        account = request.match_info.get('account', None)
        capital = post.get("capital")  # user capital
        indices = post.get("indices")  # user indices
        update = post.get("update")
        history = []

        # access_level 0 - not defined, 3 - unavailable
        try:
            accounts = [{"id": accounts.id, "type": int(accounts.type), "status": int(accounts.status)} for accounts in request.app["tinkoff"].accounts if int(accounts.access_level) not in [0, 3]]
        except:
            accounts = []

        account_cols = {
            "type": {0: "Тип аккаунта не определён.", 1: "Брокерский счёт.", 2: "ИИС счёт.", 3: "Инвесткопилка."},
            "status": {0: "Статус счёта не определён.", 1: "Новый, в процессе открытия.",
                       2: "Открытый и активный счёт.", 3: "Закрытый счёт."}}

        account_info = [
            {"type": account_cols["type"].get(a.get("type")), "status": account_cols["status"].get(a.get("status"))} for
            a in accounts if a.get("id") == account]

        if account:
            # get portfolio about account
            total_amount_shares, total_amount_bonds, total_amount_currencies, expected_yield, positions = await \
            request.app["tinkoff"].get_portfolio(account_id=account)
            history = asyncio.gather(
                *[request.app["tinkoff"].get_instrument(position=position) for position in positions])
            history = await history  # del
            history = [h for h in history if h != {}]

            # all account indices
            cursor = await session.execute(
                f"""SELECT indexid, account FROM pie WHERE account == '{account}' GROUP BY indexid, account""")
            indexes_cols = list(map(lambda x: x[0], cursor.description))
            indexes_rows = await cursor.fetchall()
            indexes_account = [dict(zip(indexes_cols, row)) for row in indexes_rows]
            indexes_account = [{**ind, **{"shortname": ind.get("indexid"),
                                          "till": f"{datetime.today().strftime('%Y-%m-%d')} (пользовательский)"}} for
                               ind in indexes_account]
            # get one uniq account indices
            cursor = await session.execute(
                f"""SELECT * FROM pie WHERE account == '{account}' AND indexid == '{indices}'""")
            indices_cols = list(map(lambda x: x[0], cursor.description))
            indices_rows = await cursor.fetchall()
            indices_account = [dict(zip(indices_cols, row)) for row in indices_rows]
            # all history
            all_history = await request.app["tinkoff"].get_operations(account_id=account)
            all_history = [{"FIGI": ah.figi, "SECNAME": ah.name, "DECRIPTION": ah.description, "STATE": ah.state,
                            "SECTYPE": ah.instrument_type,
                            "PAYMENT": request.app["tinkoff"].float_convert(ah.payment.units, ah.payment.nano),
                            "CURRENCYID": "RUB", "DB DATE": ah.date} for ah in all_history]
            all_history_cols = {"FIGI": "Тинькофф идентификатор", "SECNAME": "Наименование", "DECRIPTION": "Описание",
                                "STATE": "Статус", "SECTYPE": "Тип ценной бумаги", "PAYMENT": "Сумма операции",
                                "CURRENCYID": "Валюта", 'DB DATE': "Дата сделки"}
            all_history = [{v: h.get(k) for k, v in all_history_cols.items()} for h in all_history]

            # close connection
            await cursor.close()
        else:
            indexes_account = []
            indices_account = []
            total_amount_shares, total_amount_bonds, total_amount_currencies, expected_yield = 0, 0, 0, 0
            all_history = []
            all_history_cols = {}

        secids = post.getall("secids") if post.get("secids") else []  # exclude id
        """INDEXES"""
        indexes_msg = False
        if update:
            # if update indexes, than use moex api to get current info
            indexes = await request.app["moex"].query(
                "statistics/engines/stock/markets/index/analytics")  # current indexes
            indexes = request.app["moex"].flatten(indexes, "indices")
            if indexes != [{}]:  # if get data from api
                # update if not empty
                await session.execute(f"DELETE FROM indexes")
                await session.commit()
                [await request.app["database"].insert(session=session, table='indexes',
                                                      line={"indexid": ind.get("indexid"),
                                                            "shortname": ind.get("shortname"),
                                                            "`from`": ind.get("from"), "`till`": ind.get("till")}) for
                 ind in indexes]
            else:
                update = None  # ip blocked turn off update
                indexes_msg = True  # show msg
                cursor = await session.execute(f"""SELECT * FROM indexes;""")
                indexes_cols = list(map(lambda x: x[0], cursor.description))
                indexes_rows = await cursor.fetchall()
                indexes = [dict(zip(indexes_cols, row)) for row in indexes_rows]
                if not indexes:
                    indexes = [{}]
        else:
            cursor = await session.execute(f"""SELECT * FROM indexes;""")
            indexes_cols = list(map(lambda x: x[0], cursor.description))
            indexes_rows = await cursor.fetchall()
            indexes = [dict(zip(indexes_cols, row)) for row in indexes_rows]
            if not indexes:
                # if not db info, get from api
                indexes = await request.app["moex"].query(
                    "statistics/engines/stock/markets/index/analytics")  # current indexes
                indexes = request.app["moex"].flatten(indexes, "indices")
                if indexes != [{}]:  # if get data from api
                    # update empty
                    [await request.app["database"].insert(session=session, table='indexes',
                                                          line={"indexid": ind.get("indexid"),
                                                                "shortname": ind.get("shortname"),
                                                                "`from`": ind.get("from"), "`till`": ind.get("till")})
                     for ind in indexes]
                else:
                    indexes_msg = True

        indexes += indexes_account
        """INDEXES"""

        # get weights for indexes or []
        if indices_account:
            # weight from database (uniq indices)
            pie = indices_account
            securities = [await request.app["moex"].query(
                f"engines/stock/markets/shares/boards/TQBR/securities/{p.get('secids')}") for p in pie]
            securities = [request.app["moex"].flatten(s, "securities") for s in securities]
            securities = sum(securities, [])
            securities = [s for s in securities if s != {}]
            if securities != [{}] and securities != []:
                # update if not empty
                await session.execute(f"DELETE FROM securities WHERE INDEXID='{indices}'")
                await session.commit()
                [await request.app["database"].insert(session=session, table='securities',
                                                      line={"INDEXID": str(indices), "SECID": s.get("SECID"),
                                                            "SECNAME": s.get("SECNAME"),
                                                            "ISSUESIZE": s.get("ISSUESIZE"), "ISIN": s.get("ISIN"),
                                                            "REGNUMBER": s.get("REGNUMBER"),
                                                            "CURRENCYID": s.get("CURRENCYID"),
                                                            "SECTYPE": s.get("SECTYPE"),
                                                            "LISTLEVEL": s.get("LISTLEVEL"),
                                                            "PREVPRICE": s.get("PREVPRICE"),
                                                            "PREVWAPRICE": s.get("PREVWAPRICE"),
                                                            "LOTSIZE": s.get("LOTSIZE"), "PREVDATE": s.get("PREVDATE")})
                 for s in securities]
                # if date change
                securities_curdate = [s.get("PREVDATE") for s in securities]
                securities_curdate = set(securities_curdate)
                sql = " OR ".join(f"SECID='{s.get('SECID')}'" for s in securities)
                securities_prevdate = await session.execute(f"""SELECT PREVDATE FROM securities WHERE {sql}""")
                securities_prevdate = await securities_prevdate.fetchall()
                securities_prevdate = set([sp[0] for sp in securities_prevdate])
                if securities_curdate != securities_prevdate:  # curdate one, but in db can be more diff, than update
                    print("Update data")
                    [await request.app["database"].update(session=session, table='securities',
                                                          condition={"SECID": s.get("SECID")},
                                                          line={"PREVPRICE": s.get("PREVPRICE"),
                                                                "PREVWAPRICE": s.get("PREVWAPRICE"),
                                                                "LOTSIZE": s.get("LOTSIZE"),
                                                                "PREVDATE": s.get("PREVDATE")}) for s in securities]
            else:
                cursor = await session.execute(f"""SELECT * FROM securities WHERE INDEXID = '{indices}';""")
                securities_cols = list(map(lambda x: x[0], cursor.description))
                securities_rows = await cursor.fetchall()
                securities = [dict(zip(securities_cols, row)) for row in securities_rows]
        else:
            """PIE"""
            if update:
                # if update indexes, than use moex api to get current info
                # weight from moex
                pie = await request.app["moex"].query(f"statistics/engines/stock/markets/index/analytics/{indices}",
                                                      limit=100)
                pie = request.app["moex"].flatten(pie, "analytics")
                if pie != [{}]:  # if get data from api
                    # update if not empty
                    await session.execute(f"DELETE FROM pie WHERE account IS NULL AND indexid = '{indices}';")
                    await session.commit()
                    [await request.app["database"].insert(session=session, table='pie',
                                                          line={"indexid": p.get("indexid"), "secids": p.get("secids"),
                                                                "shortname": p.get("shortnames"),
                                                                "weight": p.get("weight")}) for p in pie]
            else:
                cursor = await session.execute(
                    f"""SELECT * FROM pie WHERE account IS NULL AND indexid = '{indices}';""")
                pie_cols = list(map(lambda x: x[0], cursor.description))
                pie_rows = await cursor.fetchall()
                pie = [dict(zip(pie_cols, row)) for row in pie_rows]
                if not pie:
                    # use api if db empty
                    pie = await request.app["moex"].query(f"statistics/engines/stock/markets/index/analytics/{indices}",
                                                          limit=100)
                    pie = request.app["moex"].flatten(pie, "analytics")
                    if pie != [{}]:  # if get data from api
                        # update empty
                        [await request.app["database"].insert(session=session, table='pie',
                                                              line={"indexid": p.get("indexid"),
                                                                    "secids": p.get("secids"),
                                                                    "shortname": p.get("shortnames"),
                                                                    "weight": p.get("weight")}) for p in pie]
            """PIE"""

            """SECURITIES"""
            securities = await request.app["moex"].query(f"engines/stock/markets/shares/boards/TQBR/securities",
                                                         index=str(indices))
            securities = request.app["moex"].flatten(securities, "securities")
            if securities != [{}] and securities != []:
                # update if not empty
                await session.execute(f"DELETE FROM securities WHERE INDEXID='{indices}'")
                await session.commit()
                [await request.app["database"].insert(session=session, table='securities',
                                                      line={"INDEXID": str(indices), "SECID": s.get("SECID"),
                                                            "SECNAME": s.get("SECNAME"),
                                                            "ISSUESIZE": s.get("ISSUESIZE"), "ISIN": s.get("ISIN"),
                                                            "REGNUMBER": s.get("REGNUMBER"),
                                                            "CURRENCYID": s.get("CURRENCYID"),
                                                            "SECTYPE": s.get("SECTYPE"),
                                                            "LISTLEVEL": s.get("LISTLEVEL"),
                                                            "PREVPRICE": s.get("PREVPRICE"),
                                                            "PREVWAPRICE": s.get("PREVWAPRICE"),
                                                            "LOTSIZE": s.get("LOTSIZE"), "PREVDATE": s.get("PREVDATE")})
                 for s in securities]
                # if date change
                securities_curdate = [s.get("PREVDATE") for s in securities]
                securities_curdate = set(securities_curdate)
                sql = " OR ".join(f"SECID='{s.get('SECID')}'" for s in securities)
                securities_prevdate = await session.execute(f"""SELECT PREVDATE FROM securities WHERE {sql}""")
                securities_prevdate = await securities_prevdate.fetchall()
                securities_prevdate = set([sp[0] for sp in securities_prevdate])
                if securities_curdate != securities_prevdate:  # curdate one, but in db can be more diff, than update
                    print("Update data")
                    [await request.app["database"].update(session=session, table='securities',
                                                          condition={"SECID": s.get("SECID")},
                                                          line={"PREVPRICE": s.get("PREVPRICE"),
                                                                "PREVWAPRICE": s.get("PREVWAPRICE"),
                                                                "LOTSIZE": s.get("LOTSIZE"),
                                                                "PREVDATE": s.get("PREVDATE")}) for s in securities]
            else:
                cursor = await session.execute(f"""SELECT * FROM securities WHERE INDEXID = '{indices}';""")
                securities_cols = list(map(lambda x: x[0], cursor.description))
                securities_rows = await cursor.fetchall()
                securities = [dict(zip(securities_cols, row)) for row in securities_rows]

        """SECURITIES"""

        # combine indexes info and securities
        exclude = [p.get("weight") for p in pie if p.get("secids") in secids]
        exclude_weight = sum(exclude) / (len(pie) - len(secids)) if (len(pie) - len(secids)) != 0 else 0
        exclude_combination = [s for s in securities if s.get("SECID") in secids]
        combination = [{**p, **s, **{"weight": round(p.get("weight") + exclude_weight, 2)}} for s in securities for p in
                       pie if s.get("SECID") == p.get("secids") and s.get("SECID") not in secids and p.get("secids")]
        include_secids = [c.get("SECID") for c in combination if c.get("SECID") not in secids]  # secids by index
        history_secids = [h.get("SECID") for h in history]  # :TODO change from db on api operations? test api
        # calculate money
        history_capital = [h.get("DB LOTS") * h.get("PREVPRICE") for h in history if h.get("SECID") not in secids]
        if not history_capital:
            history_capital = 0  # without history capital
        else:
            history_capital = sum(history_capital)
        # merge history and current index
        history_combination = [{**c, **h} for h in history for c in combination if c.get("SECID") == h.get("SECID")]
        combination = [c for c in combination if c.get("SECID") not in history_secids]
        combination += history_combination

        figis = await asyncio.gather(*[request.app["tinkoff"].find_figi(query=c.get("ISIN"), method="figi") for c in combination])
        figis = [f for f in figis if f[1]]  # remove none figi
        prices = await request.app["tinkoff"].get_last_prices(figi=figis)
        # combination
        combination = [{**c, "PREVPRICE": p[1]} for p in prices for c in combination if p[0] == c.get("ISIN")]

        cols = {}
        portfel_id = "exchange"
        if isinstance(capital, str) and combination:
            capital = int(float(capital))
            # sell some stock
            return_capital = history_capital - capital
            combination = sorted(combination, key=lambda d: d['weight'], reverse=True)  # sort from high weight
            # get budget by weight
            budget = [{c.get("SECID"): {"PRICE": (capital * (c.get("weight") / 100)), "LOTS": c.get("DB LOTS")}} if c.get("DB PRICE") else {c.get("SECID"): {"PRICE": capital * (c.get("weight") / 100), "LOTS": 0}} for c in combination]
            budget = dict(j for i in budget for j in i.items())

            for c in combination:
                c["FINAL LOTS"] = c.get("DB LOTS") if c.get("DB LOTS") else None  # set default val
                # inspect that user can but stock
                if budget.get(c.get("SECID"))["PRICE"] <= capital and c.get("PREVPRICE") <= capital:
                    attitude = int(budget.get(c.get("SECID"))["PRICE"] // c.get("PREVPRICE"))  # get whole part of float
                    # if 0, than user can buy stock, but in budget not enough capital for lot
                    # change this one priority weights
                    attitude = 1 if attitude == 0 else attitude
                    if abs(attitude) >= c.get("LOTSIZE"):
                        attitude = attitude // c.get("LOTSIZE")  # get buy or sell
                        cost = attitude * c.get("LOTSIZE") * c.get("PREVPRICE")
                        c["LOTS"] = attitude * c.get("LOTSIZE") - c.get("DB LOTS") if c.get(
                            "DB LOTS") else attitude * c.get("LOTSIZE")
                        c["LOTS"] = None if c["LOTS"] == 0 else c["LOTS"]  # hidden 0
                        c["FINAL LOTS"] = attitude * c.get("LOTSIZE")
                        c["COST"] = -round(cost - c.get("DB LOTS") * c.get("PREVPRICE"), 2) if c.get(
                            "DB LOTS") else -round(cost, 2)
                        c["COST"] = None if c["COST"] == 0 else c["COST"]  # hidden 0
                        capital -= cost
                    elif c.get("DB LOTS"):
                        c["LOTS"] = -c.get("DB LOTS")
                        c["LOTS"] = None if c["LOTS"] == 0 else c["LOTS"]  # hidden 0
                        c["FINAL LOTS"] = 0
                        c["COST"] = round(c.get("DB LOTS") * c.get("PREVPRICE", 2))
                        c["COST"] = None if c["COST"] == 0 else c["COST"]  # hidden 0
                elif c.get("DB LOTS"):
                    c["LOTS"] = -c.get("DB LOTS")
                    c["LOTS"] = None if c["LOTS"] == 0 else c["LOTS"]  # hidden 0
                    c["FINAL LOTS"] = 0
                    c["COST"] = round(c.get("DB LOTS") * c.get("PREVPRICE", 2))
                    c["COST"] = None if c["COST"] == 0 else c["COST"]  # hidden 0
            else:  # end for
                capital += return_capital
                # add sell stocks from db which not in index
                combination += [{**h, **{"LOTS": -h.get("DB LOTS"), "FINAL LOTS": 0,
                                         "COST": round(h.get("DB PRICE"), 2) * h.get("DB LOTS")}} if h.get(
                    "SECID") not in secids else {**h, **{"FINAL LOTS": h.get("DB LOTS"),
                                                         "COST": round(h.get("DB PRICE"), 2) * h.get("DB LOTS")}} for h
                                in history if h.get("SECID") not in include_secids]
                # filter and rename columns
                cols = {"SECID": "Идентификатор", "SECNAME": "Наименование", "ISSUESIZE": "Кол. ценных бумаг в выпуске",
                        "ISIN": "ISIN код", "CURRENCYID": "Идентификатор валюты", "SECTYPE": "Тип ценной бумаги",
                        "weight": "Вес, %", "DB PRICE": "Цена пред. покупки одной ценной бумаги",
                        "DB LOTS": "Кол. купл. лотов", "PREVPRICE": "Цена одной ценной бумаги",
                        "PREVWAPRICE": "Прогноз. цена одной ценной бумаги", "LOTSIZE": "Мин. размер лота",
                        "PREVDATE": "Дата информации по ценной бумаге", "LOTS": "Лотов к покупке/продаже",
                        "COST": "Покупка/продажа", "FINAL LOTS": "Итого станет лотов"}
                combination += exclude_combination  # add exclude combination
                combination = [{v: c.get(k) for k, v in cols.items()} for c in combination]
                # link to MOEX
                combination = [{**c, **{
                    "Идентификатор": f"<a target='_blank' rel='noopener noreferrer' href=https://www.moex.com/ru/issue.aspx?board=TQBR&code={c.get('Идентификатор')}>{c.get('Идентификатор')}</a>"}}
                               for c in combination]
        else:
            if account and history:
                indices = "Портфель пользователя"
                cols = {"SECID": "Идентификатор", "SECNAME": "Наименование", "ISIN": "ISIN код", "CURRENCYID": "Валюта",
                        "SECTYPE": "Тип ценной бумаги", "DB PRICE": "Ср. цена покупки", "PREVPRICE": "Текущая цена",
                        "EXPECTED": "Доходность позиции, в руб", "DB LOTS": "Кол. лотов"}
                combination = [{v: h.get(k) for k, v in cols.items()} for h in history]
                # link to MOEX
                combination = [{**c, **{
                    "Идентификатор": f"<a target='_blank' rel='noopener noreferrer' href=https://www.moex.com/ru/issue.aspx?board=TQBR&code={c.get('Идентификатор')}>{c.get('Идентификатор')}</a>"}}
                               for c in combination]
                portfel_id = "portfel"

        name_indicators = ["EMA", "ADX", "Bolinger", "RSI", "MACD", "ADI"]

        head = f"""
                  <meta charset="utf-8">
                  <meta name="viewport" content="width=device-width, initial-scale=1">
                  <link rel="icon" href="data:;base64,iVBORw0KGgo=">
                  <title>Индексы</title>
                  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.4/css/bulma.min.css">
                  <script src="https://kit.fontawesome.com/ec9b915338.js" crossorigin="anonymous"></script>
                  <style>th{'{text-align: center !important;vertical-align: middle !important;}'} input[type=checkbox] {'{transform: scale(1.5);}'}
                  td[data-monetary-amount^="-"] {'{color: red;}'} #portfel {'{display: none;}'} .tooltip {'{position: relative;display: inline-block;border-bottom: 1px dotted black;}'}
                  .tooltip .tooltiptext {'{visibility: hidden;width: 120px;background-color: black;color: #fff;text-align: center;border-radius: 6px;padding: 5px 0;position: absolute;z-index: 1;top: -5px;right: 110%;}'}
                  .tooltip .tooltiptext::after {'{content: "";position: absolute;top: 50%;left: 100%;margin-top: -5px;border-width: 5px;border-style: solid;border-color: transparent transparent transparent black;}'}
                  .tooltip:hover .tooltiptext {'{visibility: visible;}'}
                  </style>
               """

        body = f"""
                  <body>
                  <nav class="navbar" role="navigation" aria-label="dropdown navigation">
                      <div class="navbar-brand">
                          <a class="navbar-item" href="/">
                            <i class="fa-solid fa-house"></i>
                          </a>
                      </div>
                      <div class="navbar-item has-dropdown is-hoverable">
                        <a class="navbar-link">
                          Счета
                        </a>
                        <div class="navbar-dropdown">
                          {"".join(f'<a href="/{a.get("id")}" class="navbar-item">{a.get("id")}</a>' for a in accounts)}
                        </div>
                      </div>
                      {'<div class="navbar-item has-dropdown is-hoverable"><a class="navbar-link">Индексы счёта</a><div class="navbar-dropdown">' + "".join(f"<a class='navbar-item' href='/{ind.get('account')}/indices/{ind.get('indexid')}'>{ind.get('indexid')}</a>" for ind in indexes_account) + f'<hr class="navbar-divider"><a class="navbar-item" href="/{account}/indices">Создать индекс</a></div></div>' if account else ''}
                  </nav>
                  <section class="section">
                  <div class="columns is-desktop">
                  <div class="column" style="display: flex;justify-content: center;align-items: center;text-align: center;">
                        <div class='rows'>
                            <div class='row is-full'><h1 class="title is-size-2-desktop" style="max-width: 99%;">{f'Счёт {account}</h1></div><div class"row is-full"><ul clas="is-size-5" style="color: #485fc7;">{"".join("<li>" + str(a.get("type", "Тип аккаунта не определён.")) + "</li><li>" + str(a.get("status", "Статус счёта не определён.") + "</li>") for a in account_info)}</ul></div>' if account else 'Свободный режим</h1></div>'}
                        </div>
                  </div>
                  <div class="column">
                      <form id="form" method="post" class="box" action="">
                      <div style="justify-content: end;display: flex;">
                          <div>
                                <button title="show account operations" class="button is-primary" type="button" onclick="document.querySelector('#moex-group').style.display = 'none';document.querySelector('#history-group').style.display = 'block';"><i class="fa-solid fa-database"></i></button>
                          </div>
                          <div style="margin-left: 10px;">
                               <button title="show moex calculation" class="button is-primary" type="button" onclick="document.querySelector('#history-group').style.display = 'none';document.querySelector('#moex-group').style.display = 'block';"><i class="fa-solid fa-briefcase"></i></button>
                          </div>
                          <div style="margin-left: 10px;">
                               <button title="update database data from moex" class="button is-primary" type="submit" name="update"><i class="fa-solid fa-arrows-rotate"></i></button>
                          </div>
                      </div>
                      <div class="field">
                      <br>
                      <div class="columns is-desktop">
                          <div class="column is-2"><label for="indices-select">Капитал:</label></div>
                          <div class="column"><a>Общее: {round(total_amount_shares + total_amount_bonds + total_amount_currencies, 2)} руб.</a></div>
                          <div class="column"><a>Акции: {round(total_amount_shares, 2)} руб.</a></div>
                          <div class="column"><a>Облигации: {round(total_amount_bonds, 2)} руб.</a></div>
                          <div class="column"><a>Валюта: {round(total_amount_currencies, 2)} руб.</a></div>
                      </div>
                      <div class="columns is-desktop">
                          <div class="column is-2"><label for="indices-select">Показатели:</label></div>
                          <div class="column"><a>Доходность: {round(expected_yield, 2)} %</a></div>
                      </div>
                      <hr>
                      <label for="indices-select">Сумма для инвестирования в руб. (+/-):</label>
                      <br>
                      <input class="input is-primary" type="number" name="capital" min='0' step="1" value={post.get("capital") if post.get("capital") else 0} placeholder="Инвестировать">
                      <br><br>
                      <label for="indices-select">Индексы фондовой биржи:</label>
                      <br>
                      <div class="select" style="width: 100%;">
                          <select class="input is-primary" name="indices" id="indices-select">
                              {''.join(f"<option value='{inds.get('indexid')}'>{inds.get('shortname')}, Действителен {inds.get('till')}</option>" if inds else '<option>Нет подключения к MOEX</option>' for inds in indexes)}
                          </select>
                      </div>
                      <br><br>
                      {'<article class="message is-danger"><div class="message-header"><p>Данные не обновлены</p><button class="delete" onClick="return this.parentNode.parentNode.remove();" type="button"></button></div><div class="message-body">Нет подключения к MOEX. <strong>Вероятно доступ заблокирован.</strong></div></article>' if indexes_msg else ''}
                      
                      <label for="engines-select">Доступные торговые системы:</label>
                      <br>
                      <a>Фондовый рынок и рынок депозитов</a>
                      <br><br>
                      <label for="markets-select">Рынки торговой системы:</label>
                      <br>
                      <a>Рынок акций</a>
                      <br><br>
                      <label for="boards-select">Режимы торгов рынка:</label>
                      <br>
                      <a>Т+: Акции и ДР - безадрес.</a>
                      <br><br>
                      <div class="columns is-mobile">
                        <div class='column'>
                          <input style='width: 100%;' class="button is-primary" id='submit' type='submit' value='Отправить'>
                        </div>
                        <div class='column'>
                          <input style='width: 100%;' class="button is-danger is-outlined" onClick="window.location.href=window.location.href" value='Сбросить'>
                        </div>
                      </div>
                      </div>
                      </form>
                  </div>
                  </div>
                  <br><br>
                  <div id="moex-group">
                  {f"<h2 class='subtitle is-size-2-desktop' style='display: flex;justify-content: center;'><a target='_blank' rel='noopener noreferrer' href='https://www.moex.com/ru/index/{indices}/technical/'>{indices}</a></h2>" if indices else ''}
                  <div class="table-container">
                       {'<div class="card-content" style="text-align: left;"><a>Выбор индекса для рассчета: </a>' + "".join('<label class="checkbox"><input style="margin-left: 10px;margin-right: 10px;" class="nameindicators" name=' + f"'{n}'" + f' type="checkbox">{n}</label>' for n in name_indicators) + '</div>' if request.rel_url.query.get('finance') == "on" else ""}
                      <form id="form" method="post" action="">
                      <table class="table is-bordered is-hoverable has-text-centered is-size-7-desktop" style="width: 100%;">
                            <thead>
                                {''.join(f"<tr class='th is-selected'><th id='{portfel_id}'><button style='background-color: transparent;background-repeat: no-repeat;border: none;cursor: pointer;overflow: hidden;outline: none;transform: scale(1.5);' title='exclude chosen securities' aria-label='delete'><i style='color:white;' class='fa-solid fa-trash-arrow-up'></i></button></th>{''.join(f'<th>{k}</th>' for k in cols.values())}</tr>") if cols else ''}
                            </thead>
                            <tbody>
                                {''.join(f"<tr><th id='{portfel_id}'><input name='secids' value='{c.get('Идентификатор')[c.get('Идентификатор').find('>') + 1:c.get('Идентификатор').find('</a>')]}' type='checkbox' {'checked' if c.get('Идентификатор')[c.get('Идентификатор').find('>') + 1:c.get('Идентификатор').find('</a>')] in secids else ''}></th>{''.join(f'<td data-monetary-amount={v if isinstance(v, int) or isinstance(v, float) else None}>{v}</td>' if v is not None else f'<td>-</td>' for v in c.values())}</tr>" for c in combination)}
                            </tbody>
                            <tfoot>
                                <tr>
                                {f'<th></th><th>Затраты / прибыль:</th><th>{round(int(capital), 2)} РУБ.</th>' if capital else ""}
                                </tr>
                            </tfoot>
                      </table>
                      <input class="input" style='visibility: hidden;' type="text" name='indices' value="{indices}" readonly>
                      <input class="input" style='visibility: hidden;' type="text" name='capital' value="{post.get("capital")}" readonly>
                      </form>
                  </div>
                  </div>
                  <div id="history-group" style="display: none;">
                  <h2 class='subtitle is-size-2-desktop' style='display: flex;justify-content: center;'><a>История сделок</a></h2>
                  <div class="table-container">
                       <table class="table is-bordered is-hoverable has-text-centered is-size-7-desktop" style="width: 100%;">
                          <thead>
                                {''.join(f"<tr class='th is-selected'>{''.join(f'<th>{k}</th>' for k in all_history_cols.values())}</tr>") if all_history else ''}
                          </thead>
                          <tbody>
                                {''.join(f"<tr>{''.join(f'<td data-monetary-amount={v if isinstance(v, int) or isinstance(v, float) else None}>{v}</td>' if v is not None else f'<td>-</td>' for v in c.values())}</tr>" for c in all_history)}
                          </tbody>
                      </table>
                  </div>
                  </div>
                  </section>
                  </body>
               """

        script = """
                  <script>
                    const queryString = window.location.search;
                    const urlParams = new URLSearchParams(queryString);
                    const finance = urlParams.has('finance');  
                    const checkbox = document.querySelector('.finance');
                    const forms = document.querySelectorAll("[id^='form']")
                    checkbox.addEventListener('change', (event) => {
                      if (event.currentTarget.checked) {
                        if (finance == false) {
                            // if not param but is checkbox, add ?finance from url
                            let params = '?finance=on';
                            for (let i = 0; i < forms.length; i++) {
                                forms[i].action = params
                            }
                            // document.location.search = params;
                        }
                        // else if param and checkbox, nothing do with url
                      } else {
                        if (finance == true) {
                            // if param but not checkbox, delete ?finance from url
                            let params = '?finance=off';
                            for (let i = 0; i < forms.length; i++) {
                                forms[i].action = params
                            }
                            // document.location.search = params;
                        }
                        // else if param and checkbox, nothing do with url
                      }
                    })
                  </script>
                  """

        if request.rel_url.query.get('finance') == "on":
            script += """
                        <script>
                            let selections = {};
                            const indicators = document.querySelectorAll(".indicator");
                            const checkboxIndicators = document.querySelectorAll(".nameindicators");
                            const valueindicator = document.querySelector(".valueindicator");
                            // get fisrt data for selections
                            for (var i = 0; i < checkboxIndicators.length; i++) {
                              if (checkboxIndicators[i].checked) {
                                selections[checkboxIndicators[i].name] = {
                                  value: checkboxIndicators[i].checked
                                };
                              } 
                              else {
                                selections[checkboxIndicators[i].name] = {
                                  value: checkboxIndicators[i].checked
                                };
                              }
                            }
                            // listen changes
                            for (var i = 0; i < checkboxIndicators.length; i++) {
                              checkboxIndicators[i].addEventListener("change", displayCheck);
                            }
                            // function to listen cheked
                            function displayCheck(e) {
                              if (e.target.checked) {
                                selections[e.target.name] = {
                                  value: e.target.checked
                                };
                              } 
                              else {
                                selections[e.target.name] = {
                                  value: e.target.checked
                                };
                              }
                              calculateIndexes(selections);
                            }
                            // function to calculate
                            function calculateIndexes(e) {
                               // set descion
                               let action = "";
                               let profit = 0;
                               for (let j = 0; j < indicators.length; j++) {
                                  let desicion = []
                                  // first week has to be buy? i set it's date as 0
                                  let indicatorsNodes = indicators[j].childNodes;
                                  for (let z = 0; z < indicatorsNodes.length; z++) {
                                     let selection = selections[indicatorsNodes[z].getAttribute("name")];
                                     if (typeof selection !== 'undefined') {
                                        if (selection.value == true) {
                                           desicion.push(indicatorsNodes[z].getAttribute("value"));
                                        }
                                 }
                                  }
                                  // get freq for desicion
                                  let occurrences = desicion.reduce(function (acc, curr) {
                                  return acc[curr] ? ++acc[curr] : acc[curr] = 1, acc
                                  }, {});
                                  // calculate procent relationship
                                  let totalDecision = sumValues(occurrences);
                                  // get max from dict
                                  let maxDecision = Math.max.apply(null, Object.values(occurrences)),
                                     val = Object.keys(occurrences).find(function(a) {
                                    return occurrences[a] === maxDecision;
                                     });
                                  // what do if freq eq? if hold 50%, than hold. if not hold, but sell 50%, than sell. this is more safety
                                  let freqDesicion = 0;
                                  let indicatorText = "";
                                  let indicatorSpan = "<span class='tooltiptext'>";
                                  // first date/week every hold
                                  // last date every sold?
                                  if (indicators[j].getAttribute("date") == 0) {
                                          indicatorText = "<div class='tooltip' style='color: green;'>" + indicatorsNodes[0].getAttribute("buy_price");
                                          indicatorSpan += "<p>Buy 100 %</p>"
                                          action = "sell";
                                          profit = parseFloat(indicatorsNodes[0].getAttribute("buy_price"));
                                  } else {
                                      if (typeof occurrences["Hold"] !== 'undefined') {
                                      freqDesicion = occurrences["Hold"];
                                      indicatorText = "<div class='tooltip' style='color: black;'>0";
                                      indicatorSpan += "<p>Hold " + Math.round((occurrences["Hold"] / totalDecision * 100 + Number.EPSILON) * 100) / 100 + " %</p>";
                                      }
                                      if (typeof occurrences["Sell"] !== 'undefined') {
                                      if (occurrences["Sell"] > freqDesicion && occurrences["Sell"] == maxDecision && action == "sell") {
                                           freqDesicion = occurrences["Sell"];
                                           indicatorText = "<div class='tooltip' style='color: red;'>" + indicatorsNodes[0].getAttribute("sell_price");
                                           action = "buy";
                                           profit += parseFloat(indicatorsNodes[0].getAttribute("sell_price"));
                                      }
                                      indicatorSpan += "<p>Sell " + Math.round((occurrences["Sell"] / totalDecision * 100 + Number.EPSILON) * 100) / 100 + " %</p>";
                                      }
                                      if (typeof occurrences["Buy"] !== 'undefined') {
                                          if (typeof occurrences["Sell"] !== 'undefined') {
                                          if (occurrences["Buy"] > freqDesicion && occurrences["Buy"] == maxDecision && occurrences["Buy"] !== maxDecision && action == "buy") {
                                               freqDesicion = occurrences["Buy"];
                                               indicatorText = "<div class='tooltip' style='color: green;'>" + indicatorsNodes[0].getAttribute("buy_price");
                                               action = "sell";
                                               profit += parseFloat(indicatorsNodes[0].getAttribute("buy_price"));
                                          }
                                          } else {
                                          if (occurrences["Buy"] > freqDesicion && occurrences["Buy"] == maxDecision && action == "buy") {
                                               freqDesicion = occurrences["Buy"];
                                               indicatorText = "<div class='tooltip' style='color: green;'>" + indicatorsNodes[0].getAttribute("buy_price");
                                               action = "sell";
                                               profit += parseFloat(indicatorsNodes[0].getAttribute("buy_price"));
                                          } 
                                          }
                                      indicatorSpan += "<p>Buy " + Math.round((occurrences["Buy"] / totalDecision * 100 + Number.EPSILON) * 100) / 100 + " %</p>";
                                      }
                                      // if date is today than calculate sell
                                      if (indicators[j].getAttribute("date") == -1) {
                                              profit += parseFloat(indicatorsNodes[0].getAttribute("sell_price"));
                                              profit = profit * -1; // inverse to get profit
                                              // profit multiplay on num lots? not need
                                              profit = Math.round((profit + Number.EPSILON) * 100) / 100;
                                              if (profit > 0) {
                                                    indicatorText = "<div class='tooltip' style='color: green;'>" + Math.round((profit + Number.EPSILON) * 100) / 100;
                                                    indicatorSpan += "<br><p>(СВОДКА) При продаже сегодня 100 %, доход составит на 1 бумагу: " + Math.round((profit + Number.EPSILON) * 100) / 100 + "руб. </p>"
                                              } else {
                                                    indicatorText = "<div class='tooltip' style='color: red;'>" + Math.round((profit + Number.EPSILON) * 100) / 100;
                                                    indicatorSpan += "<br><p>(СВОДКА) При продаже сегодня 100 %, уботок составит на 1 бумагу: " + Math.round((profit + Number.EPSILON) * 100) / 100 + "руб. </p>"
                                              }
                                      }
                                  }
                                  // if empty indicatorText = "<div class='tooltip' style='color: black;'>0";
                                  if (indicatorText == "") {
                                    indicatorText = "<div class='tooltip' style='color: black;'>0";
                                  }
                                  indicatorText += indicatorSpan + "</span></div>"
                                  indicatorsNodes.item(0).innerHTML = indicatorText;
                               }
                            }
                            const sumValues = obj => Object.values(obj).reduce((a, b) => a + b, 0);
                          </script>
                      """

        return web.Response(text=f"<html>{head}{body}{script}</html>", content_type="text/html")

    async def indices(self, request: web.Request) -> web.Response:
        """
        Account indices creator and view page
        :param request: request
        :return: response
        """
        post = await request.post()
        account = request.match_info.get('account', None)
        # access_level 0 - not defined, 3 - unavailable
        accounts = [{"id": accounts.id, "type": int(accounts.type), "status": int(accounts.status)} for accounts in
                    request.app["tinkoff"].accounts if int(accounts.access_level) not in [0, 3]]
        indices = request.match_info.get('indices', None)

        # all account indices
        session = request.app["database"].session
        cursor = await session.execute(
            f"""SELECT indexid, account FROM pie WHERE account == '{account}' GROUP BY indexid, account""")
        indexes_cols = list(map(lambda x: x[0], cursor.description))
        indexes_rows = await cursor.fetchall()
        indexes_account = [dict(zip(indexes_cols, row)) for row in indexes_rows]

        # if indices set than view account indices
        if indices and not post.get("delete"):
            cursor = await session.execute(
                f"""SELECT * FROM pie WHERE account == '{account}' AND indexid = '{indices}'""")
            securities_cols = list(map(lambda x: x[0], cursor.description))
            securities_rows = await cursor.fetchall()
            securities = [dict(zip(securities_cols, row)) for row in securities_rows]
            cols = {"secids": "Идентификатор", "shortname": "Наименование", "weight": "Вес, %"}
            securities = [{v: s.get(k) for k, v in cols.items()} for s in securities]
            await cursor.close()

            # update indexes_account
            cursor = await session.execute(
                f"""SELECT indexid, account FROM pie WHERE account == '{account}' GROUP BY indexid, account""")
            indexes_cols = list(map(lambda x: x[0], cursor.description))
            indexes_rows = await cursor.fetchall()
            indexes_account = [dict(zip(indexes_cols, row)) for row in indexes_rows]
            await cursor.close()
            # :todo delete index

            head = f"""
                        <head>
                            <meta charset="utf-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1">
                            <link rel="icon" href="data:;base64,iVBORw0KGgo=">
                            <title>Индекс {indices}</title>
                            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.4/css/bulma.min.css">
                            <script src="https://kit.fontawesome.com/ec9b915338.js" crossorigin="anonymous"></script>
                            <style>th{'{text-align: center !important;vertical-align: middle !important;}'}</style>
                        </head>
                    """

            body = f"""
                        <body>
                        <nav class="navbar" role="navigation" aria-label="dropdown navigation">
                          <div class="navbar-brand">
                              <a class="navbar-item" href="/">
                                <i class="fa-solid fa-house"></i>
                              </a>
                          </div>
                          <div class="navbar-item has-dropdown is-hoverable">
                            <a class="navbar-link">
                              Счета
                            </a>
                            <div class="navbar-dropdown">
                              {"".join(f'<a href="/{a.get("id")}" class="navbar-item">{a.get("id")}</a>' for a in accounts)}
                            </div>
                          </div>
                          {'<div class="navbar-item has-dropdown is-hoverable"><a class="navbar-link">Индексы счёта</a><div class="navbar-dropdown">' + "".join(f"<a class='navbar-item' href='/{ind.get('account')}/indices/{ind.get('indexid')}'>{ind.get('indexid')}</a>" for ind in indexes_account) + f'<hr class="navbar-divider"><a class="navbar-item" href="/{account}/indices">Создать индекс</a></div></div>' if account else ''}
                      </nav>
                        <section class="section">
                        {f"<div style='display: flex; justify-content: center;'><h2 class='subtitle is-size-2-desktop' style='display: flex;justify-content: center;text-align: center;'>Индекс {indices}</h2><form method='post'><button value='on' id='delete' name='delete' title='delete index' style='margin-left: 15px;margin-top: 2px;' class='button is-danger is-outlined' type='submit'><span class='icon is-small'><i class='fa-solid fa-trash'></i></span></button></form></div>" if securities else f'<h2 class="subtitle is-size-2-desktop" style="display: flex;justify-content: center;text-align: center;">Индекс {indices} не найден</h2>'}
                        <div class="table-container">
                              <table class="table is-bordered is-hoverable has-text-centered is-size-7-desktop" style="width: 100%;">
                                  <thead>
                                        {''.join(f"<tr class='th is-selected'>{''.join(f'<th>{k}</th>' for k in cols.values())}</tr>") if securities else ''}
                                  </thead>
                                  <tbody>
                                        {''.join(f"<tr>{''.join(f'<td>{v}</td>' if v is not None else f'<td>-</td>' for v in c.values())}</tr>" for c in securities)}
                                  </tbody>
                              </table>
                        </div>
                        </section>
                    </body>
                    """

            return web.Response(text=f"<!DOCTYPE html><html>{head}{body}</html>", content_type="text/html")

        elif indices and post.get("delete"):
            # delete index from database and redirect
            await session.execute(f"""DELETE FROM pie WHERE account == '{account}' AND indexid = '{indices}'""")
            await session.commit()
            return web.HTTPFound(f'/{account}/indices')

        # create account indices
        indexid = post.get("indexid")
        # input info from request
        secids = post.getall("secids") if post.get("secids") else []
        weight = post.getall("weight") if post.get("weight") else []
        combination = [{"secids": secids[i], "weight": float(weight[i])} for i in range(len(secids))]

        # get securities for indexes or []
        securities = [
            await request.app["moex"].query(f"engines/stock/markets/shares/boards/TQBR/securities/{c.get('secids')}")
            for c in combination]
        securities = [request.app["moex"].flatten(s, "securities") for s in securities]
        securities = sum(securities, [])
        securities = [{**c, **s} for c in combination for s in securities if c.get("secids") == s.get("SECID")]

        # normalize weight if some secids result is empty
        weight = [s.get("weight") for s in securities]
        securities = [{**s, **{"new_weight": round(((100 - sum(weight)) / len(securities)) + s.get("weight"), 2)}} for s
                      in securities]

        if securities and indexid:
            # record to database indices info
            await session.execute(f"DELETE FROM pie WHERE account == '{account}' AND indexid == '{indexid}'")
            await session.commit()
            [await request.app["database"].insert(session=session, table='pie',
                                                  line={"indexid": indexid, "secids": s.get("SECID"),
                                                        "shortname": s.get("SHORTNAME"), "weight": s.get("new_weight"),
                                                        "account": account}) for s in securities]

            cols = {"SECID": "Идентификатор", "SHORTNAME": "Наименование", "ISIN": "ISIN код",
                    "REGNUMBER": "Регистрационный номер", "SECTYPE": "Тип ценной бумаги",
                    "LISTLEVEL": "Уровень листинга", "weight": "Выбранный вес, %", "new_weight": "Полученный вес, %"}
            securities = [{v: s.get(k) for k, v in cols.items()} for s in securities]
            # show result to user as created indices page
            head = f"""
                        <head>
                            <meta charset="utf-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1">
                            <link rel="icon" href="data:;base64,iVBORw0KGgo=">
                            <title>Создан индекс</title>
                            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.4/css/bulma.min.css">
                            <script src="https://kit.fontawesome.com/ec9b915338.js" crossorigin="anonymous"></script>
                            <style>th{'{text-align: center !important;vertical-align: middle !important;}'}</style>
                        </head>
                    """

            body = f"""
                        <body>
                        <nav class="navbar" role="navigation" aria-label="dropdown navigation">
                          <div class="navbar-brand">
                              <a class="navbar-item" href="/">
                                <i class="fa-solid fa-house"></i>
                              </a>
                          </div>
                          <div class="navbar-item has-dropdown is-hoverable">
                            <a class="navbar-link">
                              Счета
                            </a>
                            <div class="navbar-dropdown">
                              {"".join(f'<a href="/{a.get("id")}" class="navbar-item">{a.get("id")}</a>' for a in accounts)}
                            </div>
                          </div>
                          {'<div class="navbar-item has-dropdown is-hoverable"><a class="navbar-link">Индексы счёта</a><div class="navbar-dropdown">' + "".join(f"<a class='navbar-item' href='/{ind.get('account')}/indices/{ind.get('indexid')}'>{ind.get('indexid')}</a>" for ind in indexes_account) + f'<hr class="navbar-divider"><a class="navbar-item" href="/{account}/indices">Создать индекс</a></div></div>' if account else ''}
                      </nav>
                        <section class="section">
                        <h2 class='subtitle is-size-2-desktop' style='display: flex;justify-content: center;text-align: center;'>Создан индекс {indexid}</h2>
                        <div class="table-container">
                              <table class="table is-bordered is-hoverable has-text-centered is-size-7-desktop" style="width: 100%;">
                                  <thead>
                                        {''.join(f"<tr class='th is-selected'>{''.join(f'<th>{k}</th>' for k in cols.values())}</tr>") if securities else ''}
                                  </thead>
                                  <tbody>
                                        {''.join(f"<tr>{''.join(f'<td>{v}</td>' if v is not None else f'<td>-</td>' for v in c.values())}</tr>" for c in securities)}
                                  </tbody>
                              </table>
                        </div>
                        </section>
                    </body>
                    """

            return web.Response(text=f"<!DOCTYPE html><html>{head}{body}</html>", content_type="text/html")
        # create indices page
        head = f"""
                    <head>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <link rel="icon" href="data:;base64,iVBORw0KGgo=">
                        <title>Создать индекс</title>
                        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.4/css/bulma.min.css">
                        <script src="https://kit.fontawesome.com/ec9b915338.js" crossorigin="anonymous"></script>
                        <style>th{'{text-align: center !important;vertical-align: middle !important;}'}</style>
                    </head>
                """
        body = f"""
                    <body>
                        <nav class="navbar" role="navigation" aria-label="dropdown navigation">
                          <div class="navbar-brand">
                              <a class="navbar-item" href="/">
                                <i class="fa-solid fa-house"></i>
                              </a>
                          </div>
                          <div class="navbar-item has-dropdown is-hoverable">
                            <a class="navbar-link">
                              Счета
                            </a>
                            <div class="navbar-dropdown">
                              {"".join(f'<a href="/{a.get("id")}" class="navbar-item">{a.get("id")}</a>' for a in accounts)}
                            </div>
                          </div>
                          {'<div class="navbar-item has-dropdown is-hoverable"><a class="navbar-link">Индексы счёта</a><div class="navbar-dropdown">' + "".join(f"<a class='navbar-item' href='/{ind.get('account')}/indices/{ind.get('indexid')}'>{ind.get('indexid')}</a>" for ind in indexes_account) + f'<hr class="navbar-divider"><a class="navbar-item" href="/{account}/indices">Создать индекс</a></div></div>' if account else ''}
                      </nav>
                        <section class="section">
                        <form method="post">
                            <div class="columns is-desktop">
                                <div class="column is-3">
                                    <h2 class='title is-size-1-desktop' style='display: flex;justify-content: center;'>Создать индекс </h2>
                                </div>
                                <div class="column" style='display: flex;justify-content: center;'>
                                    <input class="input is-medium is-responsive" type="text" name="indexid" required="required" maxlength="36" placeholder="Название индекса">
                                </div>
                            </div>
                            <br>
                            <div class="table-container">
                            <table class="table is-bordered is-hoverable has-text-centered is-size-6-desktop" style="width: 100%;">
                                <thead>
                                    <tr class='th is-selected'>
                                        <th style="width: 51%">SECID: </th>
                                        <th style="width: 51%">Вес, %: </th>
                                        <th style="width: 2%"></th>
                                    </tr>
                                </thead>
                                <tbody id='controls'>
                                    <tr>
                                          <th style="width: 51%">
                                              <input class="input is-primary" type="text" name="secids" required="required" maxlength="36" placeholder="Идентификатор">
                                          </th>
                                          <th style="width: 51%">
                                              <input onblur="total_input()" class="input is-primary" type="number" name="weight" min='0' max='100' step="0.01" value=0 placeholder="Вес">
                                          </th>
                                          <th style="width: 2%">
                                            <button class="delete" aria-label="delete" type="button" onclick="return this.parentNode.parentNode.remove();"></button>
                                          </th>
                                    </tr>
                                </tbody>
                                <tfoot>
                                    <tr>
                                          <th></th>
                                          <th><input class="input" type="text" name="inspect" id="inspect"/ readonly></th>
                                          <th><button style="font-weight: bold;background-color: #00d1b2;color:white; height: 20px;width: 20px;max-height: 20px;max-width: 20px;min-height: 20px;min-width: 20px;border: none;border-radius: 9999px;" class="is-primary is-rounded" type="button" onclick="creator();">+</button></th>
                                    </tr>
                                </tfoot>
                            </table>
                            </div>
                            <br>
                            <button style='width: 100%;display: none;' id='save' class="button is-primary is-large is-responsive" type="submit">Сохранить</button>
                          </div>
                        </form>
                        </section>
                    </body>
                """

        scripts = """
                    <script>
                        function creator() {
                            let controls = document.querySelector('#controls');
                            let panel = document.createElement('tr');
                            panel.innerHTML = `
                                  <th style="width: 51%">
                                      <input class="input is-primary" type="text" name="secids" required="required" maxlength="36" placeholder="Идентификатор">
                                  </th>
                                  <th style="width: 51%">
                                      <input onblur="total_input()" class="input is-primary" type="number" name="weight" min='0' max='100' step="0.01" value=0 placeholder="Вес">
                                  </th>
                                  <th style="width: 2%">
                                    <button class="delete" aria-label="delete" type="button" onclick="return this.parentNode.parentNode.remove();"></button>
                                  </th>`;
                            controls.appendChild(panel);
                        }
                        function total_input() {
                            let weight = document.getElementsByName('weight');
                            let inspect = 0;
                            for (let i = 0; i < weight.length; i++){
                                if(parseInt(weight[i].value))
                                    inspect += parseInt(weight[i].value);
                            }
                            if (inspect == 100){
                                document.getElementById('inspect').value = 'Сумма: ' + String(inspect) + '%';
                                document.getElementById('save').style.display = 'block';
                            } else {
                                document.getElementById('inspect').value = 'Сумма: ' + String(inspect) + '% (необходимо 100%)';
                                document.getElementById('save').style.display = 'none';
                            }
                        }
                    </script>
                    """
        return web.Response(text=f"<!DOCTYPE html><html>{head}{body}{scripts}</html>", content_type="text/html")


class App:
    """
    Application
    """

    @staticmethod
    async def create_app(configure: dict = None) -> web.Application:
        """
        Create application
        :param configure:
        :return:
        """
        application = web.Application()
        application["config"] = configure
        application["logger"] = Logger()
        application["moex"] = MOEX()
        application["database"] = SQLAccessor()
        application["database"].setup(application=application)
        application["telegram"] = Telegram()
        application["telegram"].setup(application=application)
        application["tinkoff"] = Tinkoff()
        application["tinkoff"].setup(application=application)
        application.add_routes([web.get('/', Routes().main),
                                web.get('/{account}', Routes().main),
                                web.get('/{account}/indices', Routes().indices),
                                web.get('/{account}/indices/{indices}', Routes().indices),
                                web.post('/', Routes().main),
                                web.post('/{account}', Routes().main),
                                web.post('/{account}/indices', Routes().indices),
                                web.post('/{account}/indices/{indices}', Routes().indices)])
        return application


if __name__ == '__main__':
    web.run_app(App.create_app(configure=toml.load("config.toml")), port=8080, host='0.0.0.0')
