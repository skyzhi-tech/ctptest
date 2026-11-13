import queue
import threading
import uuid

from .adapter import ExsdkAdapter
from .config import load_secrets
from .engine import Engine, Outcome
from .store import Store
from .locking import InstanceLock


class Worker(threading.Thread):
    def __init__(self, config, output, adapter_factory=ExsdkAdapter, secrets_loader=load_secrets, session_id=None):
        super().__init__(name="ctptest-trading", daemon=True)
        self.config = config
        self.session_id = session_id or uuid.uuid4().hex
        self.output = output
        self.commands = queue.Queue()
        self.stop_test = threading.Event()
        self.shutdown = threading.Event()
        self.adapter_factory, self.secrets_loader = adapter_factory, secrets_loader
        self.redact = lambda value: value

    def emit(self, kind, value):
        self.output.put((kind, self.redact(value)))

    def run(self):
        store = adapter = engine = lock = None
        failure_status = "待环境准备"
        failure_reason = "连接未建立，请检查设置并重新连接"
        try:
            lock = InstanceLock(self.config.log_dir, self.config.scope)
            # History is available even when credentials or the network fail.
            store = Store(self.config.log_dir, self.config.scope, session_id=self.session_id)
            self.redact = store.clean
            self.emit("history", store.history())
            try:
                secrets = self.secrets_loader(self.config)
                store.secrets = [value for value in secrets.values() if value]
                adapter = self.adapter_factory(self.config, secrets)
                engine = Engine(self.config, store, adapter, self.emit, self.stop_test)
            except Exception as error:
                failure_reason = f"连接未建立：{type(error).__name__}: {error}"
                self.emit("connection_error", {"message": failure_reason})
            self.emit("available", {})
            while not self.shutdown.is_set():
                try:
                    command, value = self.commands.get(timeout=0.05 if not engine else 0)
                except queue.Empty:
                    command, value = None, None
                if command == "run":
                    if engine is None:
                        run_id = store.start(value, "")
                        self.emit("run_started", {"case_id": value, "run_id": run_id})
                        status = failure_status
                        message = failure_reason
                        store.event("", run_id, value, "system", "test_result", {"status": status, "summary": message})
                        store.finish(run_id, status, message)
                        self.emit("run_finished", dict(case_id=value, run_id=run_id, status=status, summary=message))
                    else:
                        engine.execute(value)
                    self.emit("history", store.history())
                elif command == "view":
                    events = store.events(run_id=value, limit=5000)
                    # Log-test screenshots should include their referenced evidence on revisit.
                    for event in list(events):
                        if event["kind"] == "log_search":
                            from .cases import LOG_REQUIREMENTS
                            required = LOG_REQUIREMENTS.get(event["case_id"], (None, []))[1]
                            events += [e for e in store.events(category=event["payload"]["category"],
                                       day=event["day"], limit=1000) if e["case_id"] in required]
                    self.emit("view", {"run_id": value, "events": events})
                elif command == "resume" and engine:
                    if engine.run_id is None:
                        engine.paused = False
                        store.set("paused", False)
                        engine.record("system", "manual_resume", {"paused": False})
                if engine:
                    try:
                        engine.tick()
                    except Exception as error:
                        failure_status = error.status if isinstance(error, Outcome) else "结果待核对"
                        failure_reason = str(error)
                        self.emit("connection_error", {"message": failure_reason})
                        try:
                            if engine.run_id:
                                store.finish(engine.run_id, "结果待核对", "后台异常中断")
                        finally:
                            engine = None
        except Exception as error:
            self.emit("fault", {"message": f"后台初始化或存储异常：{error}"})
        finally:
            if adapter:
                try:
                    adapter.close()
                except Exception as error:
                    self.emit("fault", {"message": f"释放连接异常：{error}"})
            if store:
                store.close()
            if lock:
                lock.close()
            self.emit("closed", {})

    def close(self):
        self.stop_test.set()
        self.shutdown.set()
