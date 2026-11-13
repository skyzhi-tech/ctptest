import queue
import threading
import unittest

from ctptest.adapter import ExsdkAdapter, snapshot
from ctptest.config import Config
from ctptest.locking import InstanceLock
from ctptest.worker import Worker
from tests import temp_directory
from tests.fakes import FakeAdapter, SYMBOL


class WorkerTests(unittest.TestCase):
    def wait_for(self, output, predicate):
        for _ in range(1000):
            item = output.get(timeout=3)
            if predicate(*item):
                return item[1]
        self.fail("后台事件数量异常")

    def test_actual_worker_queue_run_history_and_shutdown(self):
        with temp_directory() as directory:
            output = queue.Queue()
            creator_threads = []
            def create(config, secrets):
                creator_threads.append(threading.get_ident())
                return FakeAdapter()
            worker = Worker(Config(symbol=SYMBOL, log_dir=directory), output, create,
                            lambda c: dict(token="dummy-token", password="dummy-password", auth_code="dummy-auth"))
            worker.start()
            try:
                self.wait_for(output, lambda k,v:k=="status" and v["connection"]=="READY")
                worker.commands.put(("run",18))
                result = self.wait_for(output, lambda k,v:k=="run_finished")
                self.assertEqual("通过",result["status"])
                worker.commands.put(("view",result["run_id"]))
                view = self.wait_for(output, lambda k,v:k=="view")
                self.assertTrue(any(e["kind"]=="validation_verified" for e in view["events"]))
                self.assertNotEqual(threading.get_ident(),creator_threads[0])
            finally:
                worker.close()
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_missing_credentials_history_still_available(self):
        with temp_directory() as directory:
            output=queue.Queue()
            def missing(_): raise ValueError("missing credentials")
            worker=Worker(Config(log_dir=directory),output,secrets_loader=missing)
            worker.start()
            try:
                self.wait_for(output,lambda k,v:k=="available")
                worker.commands.put(("run",21))
                self.assertEqual("待环境准备",self.wait_for(output,lambda k,v:k=="run_finished")["status"])
            finally:
                worker.close()
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_instance_lock_is_released(self):
        with temp_directory() as directory:
            first=InstanceLock(directory,"same")
            try:
                with self.assertRaises(RuntimeError): InstanceLock(directory,"same")
            finally:
                first.close()
            second=InstanceLock(directory,"same")
            second.close()


class SdkShapeTests(unittest.TestCase):
    def test_installed_public_sdk_shape_and_snapshot(self):
        from exsdk.trading_data import Order, TradingResult
        self.assertNotIn("error_code",Order.fields)
        self.assertNotIn("ErrorID",Order.fields)
        self.assertEqual("REJECTED",snapshot(TradingResult("REJECTED",None,"reason"))["status"])
        self.assertIn("cancel_error",snapshot(Order()))

    def test_wrong_thread_rejected_before_any_api_call(self):
        adapter=object.__new__(ExsdkAdapter)
        adapter.thread=threading.get_ident()+1
        with self.assertRaises(RuntimeError): adapter.poll()


if __name__ == "__main__": unittest.main()
