from pathlib import Path
import unittest

from ctptest.config import Config, load_config, load_secrets, save_config
from ctptest.store import Store
from tests import temp_directory


class Vault:
    def __init__(self): self.data = {}
    def write(self, key, value): self.data[key] = value
    def read(self, key): return self.data[key]


class PersistenceTests(unittest.TestCase):
    def test_credentials_not_saved_in_config(self):
        with temp_directory() as path:
            config = Config(broker_id="b", user_id="123456", front_url="tcp://localhost:123",
                            app_id="app", symbol="DCE.test", log_dir=path)
            secrets = dict(token="SECRET-TOKEN", password="SECRET-PASSWORD", auth_code="SECRET-AUTH")
            vault = Vault()
            target = Path(path)/"config.toml"
            save_config(target, config, secrets, vault)
            saved = target.read_text(encoding="utf-8")
            self.assertFalse(any(s in saved for s in secrets.values()))
            loaded = load_config(target)
            self.assertEqual(config.scope, loaded.scope)
            self.assertEqual(secrets, load_secrets(loaded, vault))

    def test_redaction_deduplication_recovery(self):
        with temp_directory() as path:
            store = Store(path, "a", ["secret123"])
            run = store.start(1, "20261113")
            for _ in range(2):
                store.event("20261113", run, 1, "monitor", "order_submitted",
                            {"status": "SUBMITTED", "password": "secret123", "text": "x secret123"}, "same")
            store.set("paused", True)
            self.assertEqual((1,0), store.count("20261113", "order"))
            store.close()
            store = Store(path,"a")
            self.assertEqual("结果待核对", store.history()[0]["status"])
            self.assertTrue(store.get("paused"))
            self.assertEqual((1,0), store.count("20261113", "order"))
            store.close()
            self.assertNotIn("secret123", (Path(path)/"ctptest.log").read_text(encoding="utf-8"))
            store = Store(path,"b")
            self.assertEqual([],store.history())
            self.assertEqual((0,0),store.count("20261113","order"))
            store.close()


if __name__ == "__main__": unittest.main()
