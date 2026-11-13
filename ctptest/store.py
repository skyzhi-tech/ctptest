import json
from pathlib import Path
import sqlite3
import uuid
from .timeutil import TZ, now, format_shanghai_time
from .logformat import LogFormatter


class Store:
    def __init__(self, directory, scope, secrets=(), session_id=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.scope = scope
        self.session_id = session_id or uuid.uuid4().hex
        self.secrets = [s for s in secrets if s]
        self.log_formatter = LogFormatter()
        self.db = sqlite3.connect(self.directory / "ctptest.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, scope TEXT, case_id INTEGER, day TEXT,
          started TEXT, ended TEXT, status TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, scope TEXT, day TEXT, at TEXT,
          run_id TEXT, case_id INTEGER, category TEXT, kind TEXT, payload TEXT,
          dedupe TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS event_scope ON events(scope,day,run_id);
        CREATE TABLE IF NOT EXISTS settings (scope TEXT, key TEXT, value TEXT,
          PRIMARY KEY(scope,key));
        CREATE TABLE IF NOT EXISTS owned (scope TEXT, day TEXT, order_id TEXT,
          request_id TEXT, run_id TEXT, symbol TEXT, PRIMARY KEY(scope,day,order_id));
        CREATE TABLE IF NOT EXISTS sessions (scope TEXT PRIMARY KEY, session_id TEXT);
        """)
        with self.db:
            previous = self.db.execute("SELECT session_id FROM sessions WHERE scope=?", (scope,)).fetchone()
            if previous is None or previous[0] != self.session_id:
                for table in ("runs", "events", "settings", "owned"):
                    self.db.execute(f"DELETE FROM {table} WHERE scope=?", (scope,))
                self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (scope, self.session_id))
            else:
                self.db.execute("UPDATE runs SET status='结果待核对', ended=?, summary=? "
                                "WHERE scope=? AND status IN ('执行中','等待成交')",
                                (now(), "本次会话中的测试中断，请核对存量委托", scope))
            # Reconnects and account changes within this app session retain the log.
            log_session = self.db.execute("SELECT session_id FROM sessions WHERE scope='text-log'").fetchone()
            if log_session is None or log_session[0] != self.session_id:
                (self.directory / "ctptest.log").write_text("", encoding="utf-8")
                self.db.execute("INSERT OR REPLACE INTO sessions VALUES ('text-log',?)", (self.session_id,))

    def clean(self, value):
        if isinstance(value, dict):
            return {str(k): ("***" if any(s in str(k).lower() for s in
                    ("password", "token", "authcode", "auth_code")) else self.clean(v)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "***")
            return value
        return value

    def start(self, case_id, day):
        run_id = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                            (run_id, self.scope, case_id, day, now(), None, "执行中", ""))
        return run_id

    def finish(self, run_id, status, summary):
        with self.db:
            self.db.execute("UPDATE runs SET ended=?, status=?, summary=? WHERE id=? AND scope=?",
                            (now(), status, self.clean(summary), run_id, self.scope))

    def set_phase(self, run_id, phase):
        with self.db:
            self.db.execute("UPDATE runs SET status=? WHERE id=? AND scope=?", (phase, run_id, self.scope))

    def event(self, day, run_id, case_id, category, kind, payload, dedupe=None):
        event = dict(day=day, at=now(), run_id=run_id, case_id=case_id,
                     category=category, kind=kind, payload=self.clean(payload))
        text = json.dumps(event["payload"], ensure_ascii=False, default=str)
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO events "
                "(scope,day,at,run_id,case_id,category,kind,payload,dedupe) VALUES (?,?,?,?,?,?,?,?,?)",
                (self.scope, day, event["at"], run_id, case_id, category, kind, text, dedupe))
        if cursor.rowcount:
            line = self.log_formatter.format_event(event)
            if line:
                with (self.directory / "ctptest.log").open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
        return event

    def count(self, day, kind):
        rows = self.db.execute("SELECT payload FROM events WHERE scope=? AND day=? AND kind=?",
                               (self.scope, day, f"{kind}_submitted"))
        data = [json.loads(row[0]) for row in rows]
        return len(data), sum(item.get("status") == "UNKNOWN" for item in data)

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE scope=? AND key=?", (self.scope, key)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?)",
                            (self.scope, key, json.dumps(value)))

    def own(self, day, order_id, request_id, run_id, symbol):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO owned VALUES (?,?,?,?,?,?)",
                            (self.scope, day, order_id, request_id, run_id, symbol))

    def owners(self, day):
        return {row["order_id"]: dict(row) for row in self.db.execute(
            "SELECT * FROM owned WHERE scope=? AND day=?", (self.scope, day))}

    def history(self, limit=200):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM runs WHERE scope=? ORDER BY started DESC, rowid DESC LIMIT ?", (self.scope, limit))]

    def events(self, run_id=None, category=None, day=None, limit=500):
        query, args = "SELECT * FROM events WHERE scope=?", [self.scope]
        for name, value in (("run_id", run_id), ("category", category), ("day", day)):
            if value is not None:
                query += f" AND {name}=?"
                args.append(value)
        query += " ORDER BY id DESC LIMIT ?"
        rows = list(self.db.execute(query, [*args, limit]))
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in reversed(rows)]

    def close(self):
        self.db.close()
