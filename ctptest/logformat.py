"""Concise business logs. Complete source payloads remain in SQLite."""
from .cases import BY_ID
from .timeutil import format_shanghai_time
from .errorcodes import error_code


SKIP = {"test_start", "pricing", "fixture", "verified", "validation_verified",
        "counter_message_verified", "counter_error_verified", "order_submitted", "cancel_submitted"}
METRICS = {"order": "报单", "cancel": "撤单"}
WORDS = {"BUY": "买", "SELL": "卖", "OPEN": "开仓", "CLOSE": "平仓",
         "CLOSE_TODAY": "平今", "CLOSE_YESTERDAY": "平昨"}
ORDER_STATES = {"PENDING": "待回报", "ALIVE": "未结束", "FILLED": "全部成交",
                "CANCELLED": "已结束（未全成）", "REJECTED": "已拒绝"}
CONNECTION_STATES = {"SYNCING": "登录同步中", "READY": "已登录", "DISCONNECTED": "连接断开", "ERROR": "连接异常"}


def text(value):
    return " ".join(str(value).splitlines()).strip() if value is not None else ""


def fields(payload, names):
    return "  ".join(f"{label}={text(payload[key])}" for key, label in names
                     if payload.get(key) is not None and text(payload[key]))


def instrument_fields(payload):
    symbol = text(payload.get("symbol"))
    exchange, separator, instrument = symbol.partition(".")
    return f"ExchangeID={exchange}  InstrumentID={instrument}" if separator else (f"合约={symbol}" if symbol else "")


def order_identity(order_id, brief=False):
    parts = text(order_id).split(":")
    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2]:
        if brief:
            return f"OrderRef={parts[2]}"
        return f"FrontID={parts[0]}  SessionID={parts[1]}  OrderRef={parts[2]}"
    return f"本地委托号={text(order_id)}" if order_id else ""


def side_text(payload):
    return " ".join(WORDS.get(payload[key], text(payload[key])) for key in ("direction", "offset") if payload.get(key))


class LogFormatter:
    def __init__(self):
        self.seen = set()
        self.error_messages = set()
        self.cancel_reports = set()

    def entries(self, event):
        kind, p = event.get("kind"), event.get("payload") or {}
        if kind in SKIP:
            return []
        oid = text(p.get("order_id"))
        message = text(p.get("message"))
        cancel_key = (event.get("run_id"), oid, p.get("order_sys_id"), p.get("volume_traded"), p.get("status_msg"))
        if kind == "request_intent":
            return [("报单请求", "  ".join(filter(None, (instrument_fields(p), side_text(p),
                    fields(p, (("limit_price", "LimitPrice"), ("volume", "VolumeTotalOriginal")))))))]
        if kind == "cancel_intent":
            return [("撤单请求", order_identity(oid))]
        if kind == "cancel_verified":
            if cancel_key in self.cancel_reports:
                return []
            details = [order_identity(oid, brief=True),
                       fields(p, (("order_sys_id", "OrderSysID"), ("volume_traded", "VolumeTraded"))),
                       "状态=已撤单"]
            if p.get("status_msg"):
                details.append("StatusMsg=" + text(p["status_msg"]))
            return [("撤单回报", "  ".join(filter(None, details)))]
        if kind in ("submission_result", "sdk_reject"):
            operation = "撤单" if p.get("operation") == "cancel" else "报单"
            if p.get("status") == "REJECTED":
                return [("本地拒绝", f"{operation}  {message or '未提供原因'}")]
            status = {"SUBMITTED": "已提交，等待柜台回报", "UNKNOWN": "提交结果未知，待核对"}.get(p.get("status"), text(p.get("status")))
            return [("提交结果", "  ".join(filter(None, (operation, order_identity(oid), status, message))))]
        if kind in ("order", "order_error", "sdk_order_error"):
            if kind == "order" and p.get("status") == "CANCELLED":
                self.cancel_reports.add(cancel_key)
            result = []
            status_msg = text(p.get("status_msg"))
            rejected = p.get("status") == "REJECTED"
            if rejected or kind == "order":
                details = [order_identity(oid, brief=True), fields(p, (("order_sys_id", "OrderSysID"),)),
                           instrument_fields(p), side_text(p),
                           "状态=" + ORDER_STATES.get(p.get("status"), text(p.get("status")) or "未知"),
                           fields(p, (("volume_traded", "VolumeTraded"), ("volume_left", "VolumeTotal")))]
                code = error_code(status_msg) if rejected else None
                if code is not None:
                    details.append(f"ErrorID={code}")
                if status_msg:
                    details.append("StatusMsg=" + status_msg)
                result.append(("柜台拒绝" if rejected else "委托回报", "  ".join(filter(None, details))))
            if p.get("cancel_error"):
                result.append(("撤单失败", order_identity(oid) + "  " + text(p['cancel_error'])))
            return result
        if kind == "trade":
            return [("成交回报", "  ".join(filter(None, (instrument_fields(p), side_text(p),
                     fields(p, (("order_sys_id", "OrderSysID"), ("trade_id", "TradeID"),
                                ("price", "Price"), ("volume", "Volume")))))))]
        if kind == "local_reject":
            return [("本地拒绝", message)]
        if kind == "counter_error":
            return [("柜台错误", "  ".join(filter(None, (order_identity(oid),
                    fields(p, (("error_code", "ErrorID"),)), text(p.get("error_message"))))))]
        if kind == "counter_context":
            info = fields(p, (("available", "Available"), ("available_long", "可平多仓")))
            if p.get("expected_codes"):
                info = "  ".join(filter(None, (info, "预期ErrorID=" + ",".join(p["expected_codes"]))))
            return [("测试条件", info)] if info else []
        if kind == "counter_waiting":
            return [("等待回报", message)]
        if kind == "sdk_error":
            return [("SDK错误", f"{p.get('exception') or 'Error'}: {message}")]
        if kind == "submission_uncertain":
            return [("提交异常", message)]
        if kind == "connection":
            before, status = p.get("before"), p.get("status")
            current = CONNECTION_STATES.get(status, text(status))
            return [("交易连接", f"{CONNECTION_STATES.get(before, text(before))} → {current}" if before else current)]
        if kind == "login_context":
            return [("CTP账户", fields(p, (("broker_id", "BrokerID"), ("user_id", "UserID"), ("app_id", "AppID")))),
                    ("交易前置", text(p.get("front_url")))]
        if kind == "login_verified":
            account = p.get("account") or {}
            state = "登录及同步完成" if p.get("status") == "READY" else CONNECTION_STATES.get(p.get("status"), text(p.get("status")))
            result = [("登录核对", "  ".join(filter(None, (state,
                       fields(account, (("account_id", "AccountID"),)), fields(p, (("day", "TradingDay"),))))))]
            funds = fields(account, (("balance", "Balance"), ("available", "Available")))
            if funds:
                result.append(("账户资金", funds))
            return result
        if kind == "connection_verified" and "position_symbols" in p:
            return [("查询汇总", f"持仓 {p['position_symbols']} 合约  委托 {p['orders']} 笔  成交 {p['trades']} 笔")]
        if kind in ("connection_verified", "disconnect_verified", "reconnected"):
            return [("交易连接", CONNECTION_STATES.get(p.get("status"), text(p.get("status"))))]
        if kind in ("waiting_disconnect", "waiting_reconnect"):
            return [("等待", message)]
        if kind in ("pause", "resume", "manual_resume", "pause_verified"):
            return [("交易", {"pause": "已暂停", "resume": "已恢复", "manual_resume": "已恢复",
                              "pause_verified": "暂停期间下单已拦截"}[kind])]
        if kind in ("threshold_set", "statistics", "warning"):
            metric = METRICS.get(p.get("metric"), text(p.get("metric")))
            if kind == "threshold_set":
                return [("阈值", f"{metric}={p.get('value')}  当前={p.get('current')}")]
            if kind == "warning":
                return [("预警", f"{metric} {p.get('count')} >= {p.get('threshold')}")]
            info = f"{metric}={p.get('count')}"
            if p.get("threshold") is not None:
                info += f"  阈值={p['threshold']}"
            if p.get("unknown"):
                info += f"  提交时未知={p['unknown']}"
            return [("统计", info)]
        if kind == "cleanup":
            return [("清理", f"委托={oid} 已撤销")]
        if kind == "log_search":
            category = {"trade": "交易", "system": "系统", "monitor": "监测", "error": "错误"}.get(p.get("category"), "")
            info = f"{category}日志 {p.get('records', 0)} 条"
            if p.get("missing_cases"):
                info += "  缺少：" + "、".join(BY_ID[c].title if c in BY_ID else str(c) for c in p["missing_cases"])
            return [("检索", info)]
        if kind == "test_result":
            status, summary = p.get("status"), text(p.get("summary"))
            if summary in {"已取得符合本测试点判定条件的真实证据", "用户停止；后续步骤未发送，已发委托继续核对"}:
                summary = ""
            for prefix in ("SDK 本地拒绝（TradingResult.message）：", "柜台拒绝委托："):
                if summary.startswith(prefix):
                    summary = summary.removeprefix(prefix)
            duplicate_error = (event.get("run_id"), summary) in self.error_messages
            if duplicate_error:
                summary = ""
            label = {"通过": "通过", "未通过": "未通过", "待环境准备": "未就绪", "结果待核对": "待核对",
                     "SDK 限制": "SDK错误", "已停止": "停止"}.get(status, "结果")
            result = [(label, summary)]
            resources = p.get("resources") or {}
            if resources.get("未完成委托"):
                result.append(("未完成委托", "、".join(map(str, resources["未完成委托"]))))
            return result
        if kind == "sdk_limitation":
            return [("SDK", text(p.get("missing")))]
        # Preserve actual messages from unknown error types, never dump dictionaries.
        reason = message or text(p.get("error_message")) or text(p.get("summary"))
        return [("错误" if event.get("category") == "error" else "操作", reason)] if reason else []

    def format_event(self, event):
        lines = []
        for label, message in self.entries(event):
            message = text(message)
            if event.get("kind") == "runtime_error" and (event.get("run_id"), message) in self.error_messages:
                continue
            request = (event.get("payload") or {}).get("request_id") if event.get("kind") in {
                "request_intent", "cancel_intent", "submission_result", "sdk_reject"} else None
            key = (event.get("run_id"), label, message, request)
            if key in self.seen:
                continue
            self.seen.add(key)
            if label in {"本地拒绝", "柜台拒绝", "柜台错误", "SDK错误", "撤单失败", "提交异常", "错误"}:
                self.error_messages.add((event.get("run_id"), message))
                raw = event.get("payload") or {}
                for name in ("message", "status_msg", "error_message"):
                    if raw.get(name):
                        self.error_messages.add((event.get("run_id"), text(raw[name])))
            stamp = format_shanghai_time(event.get("at"))
            lines.append(f"{stamp}  [{label}]" + (f" {message}" if message else ""))
        return "\n".join(lines)


def format_events(events):
    formatter = LogFormatter()
    return "\n".join(line for event in events if (line := formatter.format_event(event)))
