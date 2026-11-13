from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import time
import uuid

from .cases import BY_ID, LOG_REQUIREMENTS
from .store import now


TERMINAL = {"FILLED", "CANCELLED", "REJECTED"}


class Outcome(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class LocalReject(Outcome):
    def __init__(self, reason, message):
        super().__init__("未通过", message)
        self.reason = reason


class SdkFailure(Outcome):
    def __init__(self, error):
        self.original_message = str(error)
        self.unsupported_position = "持仓查询包含 SDK 不支持的合约类别" in self.original_message
        if self.unsupported_position:
            super().__init__("SDK 限制", f"持仓同步失败：{self.original_message}。"
                             "需修复 SDK 或使用持仓类别兼容的测试账号。")
        else:
            super().__init__("结果待核对", f"SDK 数据更新失败：{self.original_message}")


def decimal(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        raise Outcome("待环境准备", "价格或合约规则缺失/非有限值")


class Engine:
    def __init__(self, config, store, adapter, emit, stop):
        self.config, self.store, self.adapter = config, store, adapter
        self.emit, self.stop = emit, stop
        self.day = ""
        self.state = {"status": "SYNCING", "account": {}, "orders": {}, "positions": {}, "trades": {}}
        self.run_id = None
        self.case_id = None
        self.rules = {}
        self.symbols = None
        self.storage_ok = True
        self.paused = store.get("paused", False)
        self.saw_ready = False
        self.saw_disconnect = False
        self.disconnect_at = None
        self.last_orders = {}
        self.last_trades = {}
        self.raw_errors = []
        self.cleanup_ids = set()
        self.summary_extra = []
        self.sdk_failure = None

    def record(self, category, kind, payload, dedupe=None, run_id=None, case_id=None):
        if not self.storage_ok:
            event = {"day": self.day, "at": now(), "run_id": run_id or self.run_id,
                     "case_id": case_id if case_id is not None else self.case_id,
                     "category": category, "kind": kind, "payload": self.store.clean(payload),
                     "persistence": "FAILED"}
            self.emit("event", event)
            return event
        try:
            event = self.store.event(self.day, run_id if run_id is not None else self.run_id,
                case_id if case_id is not None else self.case_id, category, kind, payload, dedupe)
        except Exception as error:
            self.storage_ok = False
            self.emit("fault", {"message": "日志保存失败；禁止新开平仓：" + str(error)})
            return self.record(category, kind, payload, dedupe, run_id, case_id)
        self.emit("event", event)

    def tick(self):
        if self.sdk_failure is not None:
            raise self.sdk_failure
        try:
            new = self.adapter.poll(0.2)
        except Exception as error:
            self.sdk_failure = SdkFailure(error)
            old_status = self.state["status"]
            self.state["status"] = "ERROR"
            self.record("error", "sdk_error", {"source": "exsdk", "exception": type(error).__name__,
                        "message": str(error), "previous_status": old_status, "status": "ERROR",
                        "diagnostic": "unsupported_position_class" if self.sdk_failure.unsupported_position
                                      else "sdk_update_failed"})
            self.record("system", "connection", {"before": old_status, "status": "ERROR",
                        "message": str(self.sdk_failure)})
            self.emit_status()
            raise self.sdk_failure from error
        old_status = self.state["status"]
        old_day = self.day
        self.day = str(new.get("account", {}).get("trading_day") or self.day)
        if self.day != old_day:
            self.rules.clear()
            self.symbols = None
        self.state = new
        if new["status"] == "READY":
            self.saw_ready = True
        if self.saw_ready and new["status"] == "DISCONNECTED":
            self.saw_disconnect = True
            if old_status != "DISCONNECTED":
                self.disconnect_at = now()
        if new["status"] != old_status or (self.day and not old_day):
            self.record("system", "connection", {"before": old_status, "status": new["status"],
                        "message": "登录并同步成功" if new["status"] == "READY" else "交易连接状态变化"})
        owners = self.store.owners(self.day)
        for order_id, order in new.get("orders", {}).items():
            if order_id not in owners or self.last_orders.get(order_id) == order:
                continue
            owner = owners[order_id]
            self.record("trade", "order", order | {"request_id": owner["request_id"]},
                        run_id=owner["run_id"], case_id=self._case_for_run(owner["run_id"]))
            if order.get("status") == "REJECTED" or order.get("cancel_error"):
                self.record("error", "order_error", order | {
                            "request_id": owner["request_id"],
                            "error_message": order.get("status_msg"),
                            "error_source": "Order.status_msg",
                            "error_code": None,
                            "error_code_note": "SDK 未提供独立错误码字段；status_msg 原文完整保留"},
                            run_id=owner["run_id"],
                            case_id=self._case_for_run(owner["run_id"]))
        self.last_orders = {k: dict(v) for k, v in new.get("orders", {}).items()}
        own_system_ids = {order.get("order_sys_id"): owners[oid]
                          for oid, order in new.get("orders", {}).items()
                          if oid in owners and order.get("order_sys_id")}
        for trade_id, trade in new.get("trades", {}).items():
            owner = own_system_ids.get(trade.get("order_sys_id"))
            if owner and self.last_trades.get(trade_id) != trade:
                self.record("trade", "trade", trade | {"request_id": owner["request_id"]},
                            dedupe=f"trade:{self.store.scope}:{self.day}:{trade.get('order_sys_id')}:{trade_id}",
                            run_id=owner["run_id"], case_id=self._case_for_run(owner["run_id"]))
        self.last_trades = {k: dict(v) for k, v in new.get("trades", {}).items()}
        for error in new.get("errors", []):
            self.raw_errors.append(error)
            self.record("error", "counter_error", error)
        self.emit_status()

    def _case_for_run(self, run_id):
        row = self.store.db.execute("SELECT case_id FROM runs WHERE id=?", (run_id,)).fetchone()
        return row[0] if row else self.case_id

    def emit_status(self):
        counts = {name: self.store.count(self.day, name) for name in ("order", "cancel")}
        self.emit("status", {"connection": self.state["status"], "day": self.day,
                  "paused": self.paused, "counts": counts,
                  "thresholds": {k: self.store.get(f"threshold_{k}") for k in counts},
                  "resources": self.resources()})

    def resources(self):
        owners = self.store.owners(self.day)
        active = [k for k in owners if self.state.get("orders", {}).get(k, {}).get("status") not in TERMINAL]
        positions = {}
        for symbol in {o["symbol"] for o in owners.values()}:
            net = self.own_long(symbol)
            if net:
                positions[symbol] = net
        return {"未完成委托": active, "本工具多头净成交": positions}

    def check_stop(self):
        if self.stop.is_set():
            raise Outcome("已停止", "用户停止；后续步骤未发送，已发委托继续核对")

    def wait(self, predicate, message, timeout=None, respect_stop=True):
        deadline = time.monotonic() + (self.config.timeout if timeout is None else timeout)
        while not predicate():
            if respect_stop:
                self.check_stop()
            if time.monotonic() >= deadline:
                raise Outcome("结果待核对", message + "：等待超时，不自动重发")
            self.tick()
            if self.state["status"] == "ERROR":
                raise Outcome("待环境准备", "SDK 进入 ERROR，请在设置中重新连接")
        return True

    def require_ready(self):
        self.check_stop()
        if self.state["status"] != "READY" or not self.day:
            raise Outcome("待环境准备", "交易连接尚未 READY 或缺少柜台交易日")

    def rule(self, symbol):
        if self.symbols is None:
            self.symbols = set(self.adapter.symbols())
        if symbol not in self.symbols:
            raise LocalReject("symbol", f"合约不存在或不是具体期货：{symbol}")
        if symbol not in self.rules:
            self.rules[symbol] = self.adapter.instrument(symbol)
        info = self.rules[symbol]
        if info.get("ins_class") != "FUTURE":
            raise LocalReject("symbol", "仅允许具体期货合约")
        data = info.get("data", {})
        tick = decimal(data.get("price_tick"))
        minimum, maximum = data.get("min_limit_order_volume"), data.get("max_limit_order_volume")
        if tick <= 0 or not minimum or not maximum:
            raise Outcome("待环境准备", "合约价位或最小/最大手数规则缺失")
        return data

    def quote_price(self, symbol, direction="BUY", passive=False):
        rule = self.rule(symbol)
        quote = {}
        def fresh():
            nonlocal quote
            quote = self.adapter.quote(symbol)
            age = time.time() - (quote.get("timestamp", 0) or 0) / 1000
            return 0 <= age <= self.config.quote_max_age
        try:
            self.wait(fresh, "没有新鲜行情", timeout=min(self.config.timeout, 15))
        except Outcome as error:
            if error.status == "结果待核对":
                raise Outcome("待环境准备", "缺少新鲜行情，未构造或发送委托") from error
            raise
        tick = decimal(rule["price_tick"])
        low, high = decimal(quote.get("lower_limit")), decimal(quote.get("upper_limit"))
        if low <= 0 or high < low:
            raise Outcome("待环境准备", "行情涨跌停范围不可用")
        book = quote.get("bids" if passive else ("asks" if direction == "BUY" else "bids")) or []
        if not book:
            raise Outcome("待环境准备", "缺少有效买卖盘口")
        price = decimal(book[0][0])
        if passive:
            price -= tick * self.config.price_offset
        elif direction == "BUY":
            price += tick * self.config.price_offset
        else:
            price -= tick * self.config.price_offset
        price = max(low, min(high, price))
        price = (price / tick).to_integral_value(rounding=ROUND_FLOOR if direction == "BUY" else ROUND_CEILING) * tick
        if not low <= price <= high:
            raise Outcome("待环境准备", "无法构造涨跌停范围内合法价格")
        self.record("trade", "pricing", {"symbol": symbol, "price": str(price),
                    "quote_timestamp": quote["timestamp"], "passive": passive,
                    "lower_limit": str(low), "upper_limit": str(high)})
        return price

    def validate(self, params):
        self.require_ready()
        if not self.storage_ok:
            raise Outcome("结果待核对", "日志不可用，禁止开平仓")
        if self.paused:
            raise LocalReject("paused", "程序化交易已暂停：委托未发送")
        rule = self.rule(params["symbol"])
        price, tick = decimal(params["limit_price"]), decimal(rule["price_tick"])
        if price <= 0 or price % tick:
            raise LocalReject("tick", f"价格 {price} 不符合最小变动价位 {tick}")
        volume = params["volume"]
        if not isinstance(volume, int) or not rule["min_limit_order_volume"] <= volume <= rule["max_limit_order_volume"]:
            raise LocalReject("volume", f"数量 {volume} 不符合单笔范围 "
                              f"{rule['min_limit_order_volume']}～{rule['max_limit_order_volume']}")

    def threshold(self, kind):
        count, _ = self.store.count(self.day, kind)
        value = count + 2
        self.store.set(f"threshold_{kind}", value)
        self.record("monitor", "threshold_set", {"metric": kind, "value": value, "current": count})
        self.check_threshold(kind)
        return value

    def check_threshold(self, kind):
        count, unknown = self.store.count(self.day, kind)
        value = self.store.get(f"threshold_{kind}")
        self.record("monitor", "statistics", {"metric": kind, "count": count, "unknown": unknown,
                    "threshold": value, "warning": value is not None and count >= value})
        if value is not None and count >= value:
            self.record("monitor", "warning", {"metric": kind, "count": count, "threshold": value,
                        "message": "达到或超过阈值"})

    def submit(self, symbol, direction="BUY", offset="OPEN", volume=1, price=None):
        params = dict(symbol=symbol, direction=direction, offset=offset, volume=volume,
                      limit_price=str(price) if price is not None else "0")
        request_id = uuid.uuid4().hex[:12]
        self.record("trade", "request_intent", params | {"request_id": request_id})
        try:
            self.validate(params)
        except LocalReject as error:
            self.record("error", "local_reject", params | {"reason": error.reason, "message": str(error),
                                                         "request_id": request_id})
            raise
        self.check_stop()
        try:
            results = self.adapter.insert(**(params | {"limit_price": float(price)}))
        except Exception as error:
            self.record("error", "submission_uncertain", {"request_id": request_id, "message": str(error)})
            raise Outcome("结果待核对", "提交异常，不能证明未发送，不自动重发") from error
        ids = self.handle_results("order", results, request_id, symbol)
        if not results:
            raise Outcome("结果待核对", "SDK 下单返回空结果")
        if any(r["status"] == "UNKNOWN" for r in results):
            raise Outcome("结果待核对", "提交 UNKNOWN，保留订单标识，不自动重发")
        if any(r["status"] == "REJECTED" for r in results):
            reasons = "；".join(r.get("message") or "（message 为空）" for r in results if r["status"] == "REJECTED")
            raise Outcome("未通过", "SDK 本地拒绝（TradingResult.message）：" + reasons)
        return ids

    def handle_results(self, kind, results, request_id, symbol=""):
        ids = []
        for index, result in enumerate(results):
            self.record("trade", "submission_result", result | {"request_id": request_id, "operation": kind})
            if result["status"] == "REJECTED":
                self.record("error", "sdk_reject", result | {"request_id": request_id, "operation": kind,
                            "error_source": "TradingResult.message"})
            order_id = result.get("order_id")
            if kind == "order" and order_id:
                self.store.own(self.day, order_id, request_id, self.run_id, symbol)
                self.cleanup_ids.add(order_id)
            if result["status"] in {"SUBMITTED", "UNKNOWN"}:
                self.record("monitor", f"{kind}_submitted", result | {"request_id": request_id},
                            dedupe=f"{self.store.scope}:{self.day}:{request_id}:{index}")
                self.check_threshold(kind)
                if order_id:
                    ids.append(order_id)
        return ids

    def await_orders(self, ids, filled=False, passive=False):
        if not ids:
            raise Outcome("结果待核对", "缺少委托ID，无法核对回报")
        def received():
            orders = self.state.get("orders", {})
            for order_id in ids:
                order = orders.get(order_id)
                if not order:
                    return False
                if order.get("status") == "REJECTED":
                    raise Outcome("未通过", "柜台拒绝委托：" + str(order.get("status_msg")))
                if passive and (order.get("volume_traded") or 0) > 0:
                    raise Outcome("结果待核对", "辅助挂单发生意外成交，请核对测试持仓")
                if filled:
                    if order.get("status") != "FILLED":
                        return False
                elif order.get("status") not in {"ALIVE", "FILLED"} or not order.get("order_sys_id"):
                    return False
            return True
        self.wait(received, "等待成交" if filled else "等待真实委托回报")
        return [self.state["orders"][k] for k in ids]

    def cancel(self, order_id, cleanup=False):
        if not cleanup:
            self.check_stop()
        if self.state["status"] != "READY":
            raise Outcome("待环境准备", "未就绪，不能撤单")
        if order_id not in self.store.owners(self.day):
            raise Outcome("未通过", "拒绝撤销非本工具委托")
        order = self.state.get("orders", {}).get(order_id, {})
        if order.get("status") in TERMINAL:
            return False
        request_id = uuid.uuid4().hex[:12]
        self.record("trade", "cancel_intent", {"order_id": order_id, "request_id": request_id})
        results = self.adapter.cancel(order_id)
        self.handle_results("cancel", results, request_id)
        if not results:
            raise Outcome("结果待核对", "SDK 撤单返回空列表，不代表撤单成功")
        if any(r["status"] != "SUBMITTED" for r in results):
            reasons = "；".join(f"{r['status']}: {r.get('message') or '（message 为空）'}"
                               for r in results if r["status"] != "SUBMITTED")
            raise Outcome("结果待核对", "撤单即时结果（TradingResult.message）：" + reasons + "；请核对原委托")
        def finished():
            current = self.state.get("orders", {}).get(order_id, {})
            if current.get("cancel_error"):
                raise Outcome("未通过", "撤单失败：" + str(current["cancel_error"]))
            return current.get("status") in TERMINAL
        self.wait(finished, "等待撤单终态", timeout=5 if cleanup else None, respect_stop=not cleanup)
        current = self.state["orders"][order_id]
        if current.get("status") != "CANCELLED" or (current.get("volume_traded") or 0) > 0:
            raise Outcome("结果待核对", "撤单前发生成交或未得到撤单成功状态")
        self.cleanup_ids.discard(order_id)
        return True

    def own_long(self, symbol):
        owners = self.store.owners(self.day)
        quantity = 0
        for oid, order in self.state.get("orders", {}).items():
            if oid not in owners or order.get("symbol") != symbol:
                continue
            volume = order.get("volume_traded") or 0
            if order.get("direction") == "BUY" and order.get("offset") == "OPEN":
                quantity += volume
            if order.get("direction") == "SELL" and str(order.get("offset", "")).startswith("CLOSE"):
                quantity -= volume
        return max(0, quantity)

    def prepare_long(self, symbol):
        available = self.state.get("positions", {}).get(symbol, {}).get("available_long") or 0
        if self.own_long(symbol) >= 1 and available >= 1:
            self.record("trade", "fixture", {"symbol": symbol, "message": "复用本工具一手可平多仓"})
            return
        ids = self.submit(symbol, price=self.quote_price(symbol))
        self.await_orders(ids, filled=True)
        if self.own_long(symbol) < 1:
            raise Outcome("结果待核对", "无法证明存在本工具测试持仓")

    def passive_order(self):
        symbol = self.config.symbol
        ids = self.submit(symbol, price=self.quote_price(symbol, passive=True))
        self.await_orders(ids, passive=True)
        return ids

    def cleanup(self):
        for oid in list(self.cleanup_ids):
            order = self.state.get("orders", {}).get(oid, {})
            if order.get("status") in TERMINAL:
                self.cleanup_ids.discard(oid)
                continue
            if not order.get("order_sys_id") or self.state["status"] != "READY":
                self.summary_extra.append(f"委托 {oid} 未完成清理，请核对")
                continue
            try:
                self.cancel(oid, cleanup=True)
                self.record("trade", "cleanup", {"order_id": oid, "message": "本次辅助委托已撤销"})
            except Exception as error:
                self.summary_extra.append(f"委托 {oid} 清理未确认：{error}")

    def execute(self, case_id):
        self.case_id = case_id
        self.run_id = self.store.start(case_id, self.day)
        self.cleanup_ids = set()
        self.summary_extra = []
        self.emit("run_started", {"case_id": case_id, "run_id": self.run_id})
        status, message = "通过", "已取得符合本测试点判定条件的真实证据"
        try:
            case = BY_ID[case_id]
            self.record("system", "test_start", {"title": case.title, "purpose": case.purpose,
                                                 "prerequisite": case.prerequisite})
            self.check_stop()
            self.perform(case_id)
        except Outcome as error:
            status, message = error.status, str(error)
        except Exception as error:
            status, message = "结果待核对", f"执行异常：{type(error).__name__}: {error}；不会自动重试交易"
        finally:
            if not self.storage_ok:
                status, message = "结果待核对", "日志写入失败；不能证明证据已保存。" + message
            if self.storage_ok:
                try:
                    self.cleanup()
                except Exception as error:
                    self.summary_extra.append(f"清理中断：{error}")
            if self.summary_extra:
                message += "；" + "；".join(self.summary_extra)
                if status == "通过":
                    status = "结果待核对"
            try:
                self.record("system", "test_result", {"status": status, "summary": message,
                            "resources": self.resources()})
                with self.store.db:
                    self.store.db.execute("UPDATE runs SET day=? WHERE id=?", (self.day, self.run_id))
                self.store.finish(self.run_id, status, message)
            except Exception:
                status, message = "结果待核对", message + "；结果持久化失败"
            self.emit("run_finished", {"case_id": case_id, "run_id": self.run_id, "status": status,
                                      "summary": self.store.clean(message)})
            self.run_id = self.case_id = None
            self.emit_status()

    def perform(self, case_id):
        if case_id in LOG_REQUIREMENTS:
            return self.log_case(case_id)
        if case_id in (0, 4):
            self.wait(lambda: self.state["status"] == "READY", "等待登录同步")
            self.record("trade", "login_verified", {"status": "READY", "day": self.day,
                        "message": "实际交易连接已登录并同步"})
            self.record("system", "connection_verified", {"status": "READY"})
            return
        if case_id == 5:
            if not self.saw_ready:
                raise Outcome("待环境准备", "先等待连接 READY，再在外部断开交易网络")
            self.record("system", "waiting_disconnect", {"message": "请在外部断开交易网络"})
            self.wait(lambda: self.saw_disconnect and self.state["status"] == "DISCONNECTED", "等待真实网络断开")
            self.record("system", "disconnect_verified", {"status": "DISCONNECTED", "at": self.disconnect_at,
                        "message": "已识别 READY 后的真实交易连接断开"})
            return
        if case_id == 6:
            if not self.saw_disconnect:
                raise Outcome("待环境准备", "当前会话没有真实断线记录；先执行断线测试")
            self.record("system", "waiting_reconnect", {"message": "请恢复交易网络，等待 READY"})
            self.wait(lambda: self.state["status"] == "READY", "等待重连同步")
            self.record("system", "reconnected", {"status": "READY", "disconnect_at": self.disconnect_at,
                        "message": "断线后重新同步成功"})
            return
        self.require_ready()
        symbol = self.config.symbol
        if case_id == 1:
            self.await_orders(self.submit(symbol, price=self.quote_price(symbol)))
        elif case_id == 2:
            self.prepare_long(symbol)
            self.await_orders(self.submit(symbol, direction="SELL", offset="CLOSE",
                                         price=self.quote_price(symbol, "SELL")), filled=True)
        elif case_id in (3, 7, 8, 13, 15):
            if case_id == 3:
                available = [oid for oid, o in self.state["orders"].items()
                             if oid in self.store.owners(self.day) and o.get("status") == "ALIVE"
                             and o.get("order_sys_id") and not o.get("volume_traded")
                             and not o.get("cancel_pending")]
                for oid in (available[:1] or self.passive_order()):
                    if not self.cancel(oid):
                        raise Outcome("结果待核对", "未产生有效撤单")
                return
            metric = "cancel" if case_id in (8, 15) else "order"
            baseline = self.store.count(self.day, metric)[0]
            target = self.threshold(metric) if case_id in (13, 15) else None
            count = 2 if target is not None else 3
            for _ in range(count):
                ids = self.passive_order()
                if metric == "cancel":
                    for oid in ids:
                        self.cancel(oid)
            current = self.store.count(self.day, metric)[0]
            if current - baseline != count or (target is not None and current < target):
                raise Outcome("未通过", "实际请求数量/阈值与测试预期不一致")
            self.record("monitor", "verified", {"metric": metric, "before": baseline, "after": current,
                        "threshold": target})
        elif case_id in (12, 14):
            self.threshold("order" if case_id == 12 else "cancel")
        elif case_id in (18, 19, 20):
            rule = self.rule(symbol)
            price = decimal(rule["price_tick"]) * 100
            volume = 1
            bad_symbol = symbol
            reason = {18: "symbol", 19: "tick", 20: "volume"}[case_id]
            if case_id == 18:
                bad_symbol = "SHFE.ctptest_invalid_" + uuid.uuid4().hex
            elif case_id == 19:
                price += decimal(rule["price_tick"]) / 2
            else:
                volume = int(rule["max_limit_order_volume"]) + 1
            try:
                self.submit(bad_symbol, volume=volume, price=price)
            except LocalReject as error:
                if error.reason != reason:
                    raise
                self.record("error", "validation_verified", {"reason": reason, "message": str(error),
                            "sent_to_sdk": False})
            else:
                raise Outcome("未通过", "错误参数未被本地拦截")
        elif case_id == 25:
            if self.paused:
                raise Outcome("待环境准备", "当前已暂停；先在设置中明确恢复后再执行暂停测试")
            self.paused = True
            self.store.set("paused", True)
            self.record("system", "pause", {"paused": True})
            try:
                try:
                    self.submit(symbol, price=Decimal(1))
                except LocalReject as error:
                    if error.reason != "paused":
                        raise
                    self.record("system", "pause_verified", {"blocked": True, "sent_to_sdk": False})
                else:
                    raise Outcome("未通过", "暂停未阻止发单")
            finally:
                self.paused = False
                self.store.set("paused", False)
                self.record("system", "resume", {"paused": False})
            # Prove the common order gate is restored with an actual test order.
            self.await_orders(self.submit(symbol, price=self.quote_price(symbol, passive=True)), passive=True)
        elif case_id in (21, 22, 23):
            self.counter_case(case_id)

    def counter_case(self, case_id):
        prefix = {21: "funds", 22: "position", 23: "market"}[case_id]
        symbol = getattr(self.config, prefix + "_symbol") or self.config.symbol
        expected = {s.strip() for s in getattr(self.config, prefix + "_error_codes").split(",") if s.strip()}
        terms = {
            21: ("资金不足", "insufficientfunds", "insufficientmoney"),
            22: ("持仓不足", "可平不足", "平仓量超过", "平仓数量超过", "insufficientposition"),
            23: ("非交易时间", "非交易时段", "市场未开", "当前状态禁止", "marketclosed", "nottrading"),
        }[case_id]
        def target_message(message):
            normalized = "".join(str(message or "").lower().split())
            return any(term in normalized for term in terms)
        volume, direction, offset = self.config.funds_volume if case_id == 21 else 1, "BUY", "OPEN"
        if case_id == 22:
            self.prepare_long(symbol)
            available = self.state["positions"].get(symbol, {}).get("available_long")
            if available is None:
                raise Outcome("待环境准备", "柜台可平持仓未知")
            volume, direction, offset = available + 1, "SELL", "CLOSE"
        first = len(self.raw_errors)
        ids = self.submit(symbol, direction, offset, volume, self.quote_price(symbol, direction))
        def matched():
            for error in self.raw_errors[first:]:
                if (error.get("order_id") in ids and error.get("error_code") is not None
                        and (str(error["error_code"]) in expected or target_message(error.get("error_message")))):
                    self.record("error", "counter_error_verified", error)
                    return True
            orders = [self.state["orders"].get(oid, {}) for oid in ids]
            for order in orders:
                if order.get("status") == "REJECTED" and target_message(order.get("status_msg")):
                    self.record("error", "counter_message_verified", {
                        "order_id": order["order_id"], "status_msg": order["status_msg"],
                        "error_source": "Order.status_msg", "error_code": None,
                        "message_verified": True, "code_verified": False})
                    raise Outcome("结果待核对", "已收到目标柜台错误：" + order["status_msg"]
                                  + "；错误信息已验证，未取得可核对的独立错误码，完整验收待核对")
            if orders and all(o.get("status") in TERMINAL for o in orders):
                raise Outcome("未通过", "未触发目标柜台错误，实际委托状态和原因见回报")
            return False
        self.wait(matched, "等待目标原始柜台错误")

    def log_case(self, case_id):
        category, required = LOG_REQUIREMENTS[case_id]
        history = [r for r in self.store.history(5000) if r["day"] == self.day]
        completed = {r["case_id"] for r in history if r["status"] == "通过"}
        evidence = self.store.events(category=category, day=self.day, limit=1000)
        if case_id == 32:
            # Logging evidence can be complete even while the separate code check is pending.
            completed |= {e["case_id"] for e in evidence if e["kind"] in
                          {"validation_verified", "counter_message_verified", "counter_error_verified"}}
        missing = [key for key in required if key not in completed]
        self.record("system", "log_search", {"category": category, "missing_cases": missing,
                    "records": len(evidence)})
        for event in evidence:
            if event["case_id"] in required:
                self.emit("evidence", event)
        if missing:
            raise Outcome("待环境准备", "缺少同交易日通过记录：" + "、".join(map(str, missing)))
        if not evidence:
            raise Outcome("未通过", "未检索到日志证据")
