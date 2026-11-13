"""Deterministic test-only broker; never imported by the application."""
from copy import deepcopy
import time

SYMBOL = "DCE.test9999"


class FakeAdapter:
    raw_errors_supported = False

    def __init__(self):
        self.calls = []
        self.orders = {}
        self.trades = {}
        self.position = 0
        self.next_status = "READY"
        self.cancel_results = None
        self.result_status = "SUBMITTED"
        self.error_code = None
        self.error_message = "柜台原始拒绝"
        self.emit_raw_errors = True
        self.reject_offset = None
        self.errors = []
        self.on_poll = None

    def poll(self, seconds=0.2):
        if self.on_poll:
            self.on_poll()
        for oid, order in self.orders.items():
            if order["status"] == "PENDING":
                order["status"] = "ALIVE"
                price = order["limit_price"]
                if self.error_code and (self.reject_offset is None or order["offset"] == self.reject_offset):
                    order.update(status="REJECTED", status_msg=self.error_message)
                    if self.emit_raw_errors:
                        self.errors.append(dict(order_id=oid, error_code=self.error_code, error_message=self.error_message))
                elif order["direction"] == "BUY" and price >= 102 or order["direction"] == "SELL" and price <= 100:
                    volume = order["volume_original"]
                    order.update(status="FILLED", volume_traded=volume, volume_left=0)
                    self.position += volume if order["offset"] == "OPEN" else -volume
                    self.trades[oid] = dict(trade_id=oid, order_sys_id=order["order_sys_id"],
                                            symbol=order["symbol"], direction=order["direction"],
                                            offset=order["offset"], price=price, volume=volume)
        errors, self.errors = self.errors, []
        return deepcopy(dict(status=self.next_status, account={"trading_day": "20261113"},
                   orders=self.orders, positions={SYMBOL: {"available_long": self.position}}, trades=self.trades, errors=errors))

    def symbols(self):
        return [SYMBOL]

    def instrument(self, symbol):
        return dict(symbol=symbol, ins_class="FUTURE", data=dict(price_tick=2, min_limit_order_volume=1,
                                                                max_limit_order_volume=100))

    def quote(self, symbol):
        return dict(timestamp=int(time.time()*1000), lower_limit=50, upper_limit=150,
                    bids=[(100, 100)], asks=[(102, 100)])

    def insert(self, **params):
        self.calls.append(("insert", params))
        if self.result_status == "REJECTED":
            return [dict(status="REJECTED", order_id=None, message="本地拒绝")]
        oid = f"1:1:{len(self.orders)+1}"
        self.orders[oid] = dict(order_id=oid, order_sys_id="sys" + oid, symbol=params["symbol"],
                              direction=params["direction"], offset=params["offset"], limit_price=params["limit_price"],
                              volume_original=params["volume"], volume_traded=0, volume_left=params["volume"],
                              status="PENDING", status_msg="", cancel_pending=False, cancel_error=None)
        return [dict(status=self.result_status, order_id=oid, message="")]

    def cancel(self, oid):
        self.calls.append(("cancel", oid))
        if self.cancel_results is not None:
            return self.cancel_results
        self.orders[oid].update(status="CANCELLED", cancel_pending=False)
        return [dict(status="SUBMITTED", order_id=oid, message="")]

    def close(self):
        pass
