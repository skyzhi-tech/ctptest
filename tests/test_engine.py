import threading
import unittest

from ctptest.cases import CASES
from ctptest.config import Config
from ctptest.engine import Engine, LocalReject, Outcome
from ctptest.store import Store
from tests.fakes import FakeAdapter, SYMBOL
from tests import temp_directory


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = temp_directory()
        self.config = Config(symbol=SYMBOL, timeout=0.02)
        self.store = Store(self.temp.name, "unit-tests")
        self.adapter = FakeAdapter()
        self.messages = []
        self.stop = threading.Event()
        self.engine = Engine(self.config, self.store, self.adapter,
                             lambda k,v: self.messages.append((k,v)), self.stop)
        self.engine.tick()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def execute(self, case):
        self.engine.execute(case)
        return next(v for k,v in reversed(self.messages) if k == "run_finished")

    def test_all_required_cases_and_log_dependencies(self):
        for case in CASES:
            with self.subTest(case=case.id):
                if case.id == 5:
                    self.adapter.next_status = "DISCONNECTED"
                if case.id == 6:
                    self.adapter.next_status = "READY"
                result = self.execute(case.id)
                expected = "未通过" if case.id in (21,22,23) else "待环境准备" if case.id == 32 else "通过"
                self.assertEqual(expected, result["status"], result["summary"])

    def test_local_checks_never_call_sdk(self):
        for case in (18,19,20):
            result = self.execute(case)
            self.assertEqual("通过", result["status"])
        self.assertEqual([], self.adapter.calls)

    def test_error_cases_not_disabled_by_missing_code_capability(self):
        for case in (21,22,23):
            self.assertEqual("未通过", self.execute(case)["status"])
        self.assertTrue(self.adapter.calls)

    def test_pause_persisted_and_blocks_common_gate(self):
        self.engine.paused = True
        with self.assertRaises(LocalReject) as context:
            self.engine.submit(SYMBOL, price=102)
        self.assertEqual("paused", context.exception.reason)
        self.assertEqual([], self.adapter.calls)
        self.engine.paused = False
        self.assertEqual("通过", self.execute(25)["status"])
        self.assertFalse(self.store.get("paused"))

    def test_repeated_snapshot_and_foreign_order_not_counted(self):
        self.execute(1)
        baseline = self.store.count(self.engine.day, "order")
        self.adapter.orders["foreign"] = dict(self.adapter.orders["1:1:1"], order_id="foreign")
        for _ in range(3):
            self.engine.tick()
        self.assertEqual(baseline, self.store.count(self.engine.day,"order"))
        self.assertEqual(1, baseline[0])
        trades = [e for e in self.store.events(category="trade") if e["kind"] == "trade"]
        self.assertEqual(1,len(trades))
        self.assertIn("price",trades[0]["payload"])

    def test_unknown_is_not_retried_or_passed(self):
        self.adapter.result_status = "UNKNOWN"
        result = self.execute(1)
        self.assertEqual("结果待核对", result["status"])
        self.assertEqual(1, len([c for c in self.adapter.calls if c[0] == "insert"]))
        self.assertEqual((1,1), self.store.count(self.engine.day, "order"))
        self.assertTrue(self.engine.resources()["未完成委托"])

    def test_stop_before_execution_sends_nothing(self):
        self.stop.set()
        self.assertEqual("已停止", self.execute(7)["status"])
        self.assertEqual([], self.adapter.calls)

    def test_stop_after_submit_no_later_insert(self):
        self.adapter.on_poll = self.stop.set
        self.assertEqual("已停止", self.execute(7)["status"])
        self.assertEqual(1, len([c for c in self.adapter.calls if c[0] == "insert"]))

    def test_empty_cancel_result_is_not_success(self):
        self.adapter.cancel_results = []
        self.assertEqual("结果待核对", self.execute(3)["status"])
        self.assertEqual((0,0), self.store.count(self.engine.day, "cancel"))

    def test_unexpected_fill_fails_passive_test(self):
        original = self.adapter.insert
        def filled(**params):
            result = original(**params)
            self.adapter.orders[result[0]["order_id"]].update(status="FILLED", volume_traded=1)
            return result
        self.adapter.insert = filled
        self.assertEqual("结果待核对", self.execute(3)["status"])

    def test_timeout_does_not_mean_disconnect_or_pass(self):
        self.assertEqual("结果待核对", self.execute(5)["status"])
        self.assertEqual("READY", self.engine.state["status"])

    def test_threshold_equal_and_above(self):
        self.assertEqual("通过", self.execute(13)["status"])
        events = self.store.events(category="monitor")
        warnings = [e for e in events if e["kind"] == "warning"]
        self.assertTrue(warnings)
        self.assertEqual(warnings[0]["payload"]["count"], warnings[0]["payload"]["threshold"])
        self.execute(7)
        self.assertGreater(self.store.count(self.engine.day,"order")[0], self.store.get("threshold_order"))

    def test_original_holdings_not_treated_as_owned(self):
        self.adapter.position = 10
        self.engine.tick()
        self.execute(2)
        inserts = [p for name,p in self.adapter.calls if name == "insert"]
        self.assertEqual(["OPEN", "CLOSE"], [p["offset"] for p in inserts])
        self.assertEqual(10, self.adapter.position)

    def test_log_cases_do_not_create_missing_trades(self):
        self.assertEqual("待环境准备", self.execute(29)["status"])
        self.assertEqual([], self.adapter.calls)

    def test_native_error_matching_future_adapter_contract(self):
        self.adapter.raw_errors_supported = True
        self.adapter.error_code = 31
        self.config.funds_symbol = SYMBOL
        self.config.funds_error_codes = "31"
        self.assertEqual("通过", self.execute(21)["status"])

    def test_order_rejection_preserves_original_status_msg_without_inventing_code(self):
        self.adapter.error_code = 31
        self.assertEqual("未通过", self.execute(1)["status"])
        events = [e for e in self.store.events(category="error") if e["kind"] == "order_error"]
        self.assertEqual(1, len(events))
        payload = events[0]["payload"]
        self.assertEqual("柜台原始拒绝", payload["status_msg"])
        self.assertEqual(payload["status_msg"], payload["error_message"])
        self.assertEqual("Order.status_msg", payload["error_source"])
        self.assertIsNone(payload["error_code"])

    def test_sdk_local_rejection_message_visible_without_order_or_count(self):
        self.adapter.result_status = "REJECTED"
        result = self.execute(1)
        self.assertEqual("未通过", result["status"])
        self.assertIn("本地拒绝", result["summary"])
        errors = [e for e in self.store.events(category="error") if e["kind"] == "sdk_reject"]
        self.assertEqual(1, len(errors))
        self.assertEqual("本地拒绝", errors[0]["payload"]["message"])
        self.assertEqual("TradingResult.message", errors[0]["payload"]["error_source"])
        self.assertEqual({}, self.adapter.orders)
        self.assertEqual((0, 0), self.store.count(self.engine.day, "order"))

    def test_target_status_msg_runs_but_missing_code_is_not_full_pass(self):
        self.adapter.error_code = 31
        self.adapter.emit_raw_errors = False
        for case, message in ((21, "资金不足"), (22, "平仓量超过持仓量"), (23, "非交易时间")):
            with self.subTest(case=case):
                self.adapter.error_message = message
                self.adapter.reject_offset = "CLOSE" if case == 22 else None
                result = self.execute(case)
                self.assertEqual("结果待核对", result["status"], result["summary"])
                self.assertIn(message, result["summary"])
                self.assertIn("错误信息已验证", result["summary"])
        for case in (18,19,20):
            self.assertEqual("通过", self.execute(case)["status"])
        self.assertEqual("通过", self.execute(32)["status"])

    def test_day_rollover_resets_count_scope(self):
        self.execute(1)
        self.assertEqual((0,0), self.store.count("20261116", "order"))

    def test_storage_failure_blocks_subsequent_inserts(self):
        self.engine.storage_ok = False
        with self.assertRaises(Outcome):
            self.engine.submit(SYMBOL, price=102)
        self.assertEqual([], self.adapter.calls)

    def test_log_write_failure_keeps_reception_but_prevents_trade(self):
        def fail(*args, **kwargs):
            raise OSError("disk full")
        self.store.event = fail
        result = self.execute(1)
        self.assertEqual("结果待核对", result["status"])
        self.assertEqual([], self.adapter.calls)
        self.engine.tick()
        self.assertEqual("READY", self.engine.state["status"])
        self.assertFalse(self.engine.storage_ok)


if __name__ == "__main__":
    unittest.main()
