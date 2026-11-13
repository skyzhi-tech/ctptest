from pathlib import Path
import queue
import threading
import tkinter as tk
import unittest

from ctptest.gui import Application
from tests import temp_directory


class StubWorker:
    def __init__(self):
        self.commands = queue.Queue()
        self.stop_test = threading.Event()


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp = temp_directory()
        self.app = Application(self.root, Path(self.temp.name)/"config.toml", autoconnect=False)
        self.app.worker = StubWorker()
        self.app.available = True

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def test_selection_view_never_sends_only_explicit_first_click(self):
        self.app.select(1)
        self.assertTrue(self.app.worker.commands.empty())
        self.app.select(1, execute=True)
        self.assertEqual(("run",1), self.app.worker.commands.get_nowait())
        self.app.select(1, execute=True)
        self.assertTrue(self.app.worker.commands.empty())

    def test_history_selection_only_views(self):
        run = dict(id="history1", case_id=1, status="通过", started="2026-11-13", day="20261113", summary="证据")
        self.app.handle("history", [run])
        self.app.select(1, execute=True)
        commands = list(self.app.worker.commands.queue)
        self.assertFalse(any(k=="run" for k,v in commands))
        self.assertEqual("通过", self.app.result_label.cget("text"))

    def test_live_result_and_raw_evidence_render(self):
        self.app.select(21)
        self.app.handle("run_started", dict(case_id=21, run_id="run1"))
        self.app.handle("event", dict(run_id="run1", at="2026-11-13", kind="sdk_limitation",
                                       payload={"missing":"原始柜台错误码"}))
        self.app.handle("run_finished", dict(case_id=21,run_id="run1",status="SDK 限制",summary="未发单"))
        self.assertEqual("SDK 限制", self.app.result_label.cget("text"))
        self.assertIn("原始柜台错误码", self.app.text.get("1.0","end"))


if __name__ == "__main__": unittest.main()
