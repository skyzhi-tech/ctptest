"""Concise business logs. Complete source payloads remain in SQLite."""
from .cases import BY_ID
from .timeutil import format_shanghai_time


SKIP = {"test_start", "pricing", "fixture", "verified", "validation_verified",
        "counter_message_verified", "counter_error_verified", "order_submitted", "cancel_submitted"}
METRICS = {"order": "报单", "cancel": "撤单"}
WORDS = {"BUY": "买", "SELL": "卖", "OPEN": "开仓", "CLOSE": "平仓",
         "CLOSE_TODAY": "平今", "CLOSE_YESTERDAY": "平昨"}


def text(value):
    return " ".join(str(value).splitlines()).strip() if value is not None else ""


def fields(payload, names):
    return "  ".join(f"{label}={text(payload[key])}" for key, label in names
                     if payload.get(key) is not None and text(payload[key]))


class LogFormatter:
    def __init__(self):
        self.seen = set()
        self.error_messages = set()

    def entries(self, event):
        kind, p = event.get("kind"), event.get("payload") or {}
        if kind in SKIP:
            return []
        oid = text(p.get("order_id"))
        message = text(p.get("message"))
        if kind == "request_intent":
            params = " ".join(filter(None, (text(p.get("symbol")), WORDS.get(p.get("direction"), text(p.get("direction"))),
                                WORDS.get(p.get("offset"), text(p.get("offset"))))))
            return [("报单", params + "  " + fields(p, (("volume", "手数"), ("limit_price", "价格"))))]
        if kind == "cancel_intent":
            return [("撤单", f"委托={oid}")]
        if kind in ("submission_result", "sdk_reject"):
            operation = "撤单" if p.get("operation") == "cancel" else "报单"
            if p.get("status") == "REJECTED":
                return [("SDK拒绝", f"{operation}  {message or '未提供原因'}")]
            return [("提交", "  ".join(filter(None, (operation, f"委托={oid}" if oid else "",
                         text(p.get("status")), message))))]
        if kind in ("order", "order_error", "sdk_order_error"):
            result = []
            status_msg = text(p.get("status_msg"))
            if p.get("status") == "REJECTED":
                result.append(("柜台拒绝", f"委托={oid}  {status_msg or '未提供原因'}"))
            elif kind == "order":
                result.append(("委托", fields(p, (("order_id", "委托"), ("symbol", "合约"),
                    ("status", "状态"), ("volume_traded", "已成交"), ("volume_left", "剩余")))
                    + (f"  {status_msg}" if status_msg else "")))
            if p.get("cancel_error"):
                result.append(("撤单失败", f"委托={oid}  {text(p['cancel_error'])}"))
            return result
        if kind == "trade":
            return [("成交", fields(p, (("trade_id", "成交"), ("symbol", "合约"),
                    ("price", "价格"), ("volume", "手数"), ("order_sys_id", "交易所委托"))))]
        if kind == "local_reject":
            return [("本地拒绝", message)]
        if kind == "counter_error":
            return [("柜台错误", fields(p, (("order_id", "委托"), ("error_code", "错误码")))
                    + "  " + text(p.get("error_message")))]
        if kind == "sdk_error":
            return [("SDK错误", f"{p.get('exception') or 'Error'}: {message}")]
        if kind == "submission_uncertain":
            return [("提交异常", message)]
        if kind == "connection":
            before, status = p.get("before"), p.get("status")
            return [("连接", f"{before} → {status}" if before else text(status))]
        if kind in ("login_verified", "connection_verified", "disconnect_verified", "reconnected"):
            return [("连接", text(p.get("status")))]
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
            result = [] if duplicate_error else [(label, summary)]
            resources = p.get("resources") or {}
            if resources.get("未完成委托"):
                result.append(("未完成委托", "、".join(map(str, resources["未完成委托"]))))
            if resources.get("本工具多头净成交"):
                result.append(("测试持仓", "  ".join(f"{s}={q}" for s,q in resources["本工具多头净成交"].items())))
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
            if label in {"本地拒绝", "SDK拒绝", "柜台拒绝", "柜台错误", "SDK错误", "撤单失败", "提交异常", "错误"}:
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
