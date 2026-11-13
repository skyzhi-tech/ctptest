"""All SDK access is confined to the worker thread; no network on import."""
from dataclasses import asdict, is_dataclass
import threading
import time


def snapshot(obj):
    if isinstance(obj, dict):
        return {k: snapshot(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [snapshot(v) for v in obj]
    if is_dataclass(obj):
        return asdict(obj)
    fields = getattr(obj, "fields", None)
    if fields:
        return {key: getattr(obj, key, None) for key in fields}
    return obj


class ExsdkAdapter:
    def __init__(self, config, secrets):
        from exsdk import ExApi, CtpAccount
        self.thread = threading.get_ident()
        self.errors = []
        self.quotes = {}
        self.raw_errors_supported = False  # exsdk 1.7 public API: no native ErrorID.
        account = CtpAccount(broker_id=config.broker_id, user_id=config.user_id,
                             password=secrets["password"], front_url=config.front_url,
                             app_id=config.app_id, auth_code=secrets["auth_code"])
        self.api = ExApi(token=secrets["token"], account=account)
        self.watches = {"account": self.api.watch_account(), "positions": self.api.watch_position(),
                        "orders": self.api.watch_order(), "trades": self.api.watch_trade()}

    def _check(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError("SDK 只能在创建线程使用")

    def poll(self, seconds=0.2):
        self._check()
        self.api.wait_update(deadline=time.time() + seconds)
        data = {"status": self.api.trading_status()}
        for name, watch in self.watches.items():
            value = watch.data()
            data[name] = {k: snapshot(v) for k, v in value.items()} if name != "account" else snapshot(value)
        data["errors"], self.errors = self.errors, []
        return data

    def symbols(self):
        self._check()
        return self.api.query_symbols("FUTURE")

    def instrument(self, symbol):
        self._check()
        return self.api.query_symbol_info(symbol)

    def quote(self, symbol):
        self._check()
        if symbol not in self.quotes:
            self.quotes[symbol] = self.api.watch_quote(symbol)
        return snapshot(self.quotes[symbol].data())

    def insert(self, **params):
        self._check()
        return [snapshot(r) for r in self.api.insert_order(**params)]

    def cancel(self, order_id):
        self._check()
        return [snapshot(r) for r in self.api.cancel_order(order_id)]

    def close(self):
        self._check()
        self.api.close()
