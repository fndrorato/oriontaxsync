import sqlite3
import tempfile
import unittest
from pathlib import Path

from config.database import DatabaseManager


class DatabaseV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.db.disconnect()
        self.temp.cleanup()

    def test_existing_installations_default_to_intersolid(self):
        installation = self.db.get_installation()
        self.assertEqual("intersolid", installation["erp_type"])
        self.assertTrue(installation["installation_id"])
        self.assertEqual(
            "https://github.com/fndrorato/oriontaxsync/releases/latest/download/update-manifest.json",
            self.db.get_configuracao("update_manifest_url"),
        )

    def test_switches_erp_explicitly(self):
        self.db.set_erp_type("sysmo")
        self.assertEqual("sysmo", self.db.get_installation()["erp_type"])
        with self.assertRaises(ValueError):
            self.db.set_erp_type("oracle")

    def test_switches_to_vr(self):
        self.db.set_erp_type("vr")
        self.assertEqual("vr", self.db.get_installation()["erp_type"])

    def test_vr_config_round_trip(self):
        self.assertIsNone(self.db.get_vr_config())
        self.db.save_vr_config("http://10.0.0.5:9025/", "tok", page_size=200)
        cfg = self.db.get_vr_config()
        self.assertEqual("http://10.0.0.5:9025", cfg["base_url"])
        self.assertEqual("tok", cfg["token"])
        self.assertEqual(200, cfg["page_size"])
        self.assertEqual(50, cfg["patch_batch_size"])
        self.assertIs(False, cfg["write_enabled"])
        self.db.save_vr_config("http://10.0.0.5:9025/", "tok", write_enabled=True)
        self.assertIs(True, self.db.get_vr_config()["write_enabled"])
        self.db.save_vr_config("http://10.0.0.5:9025/", "tok")
        self.assertIs(False, self.db.get_vr_config()["write_enabled"])

    def test_adds_write_enabled_column_to_existing_config_vr(self):
        path = Path(self.temp.name) / "old_vr.db"
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE config_vr (
            id INTEGER PRIMARY KEY CHECK (id = 1), base_url TEXT NOT NULL, token_encrypted TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL DEFAULT 60, page_size INTEGER NOT NULL DEFAULT 500,
            patch_batch_size INTEGER NOT NULL DEFAULT 50, is_active INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit(); conn.close()
        db = DatabaseManager(path)
        try:
            db.save_vr_config("http://10.0.0.5:9025", "tok")
            self.assertIs(False, db.get_vr_config()["write_enabled"])
        finally:
            db.disconnect()

    def test_cliente_stores_optional_uf(self):
        self.assertTrue(self.db.create_cliente("Loja 1", "01.234.567/0001-95", " go "))
        self.assertTrue(self.db.create_cliente("Loja 2", "22881305000192"))
        self.assertEqual("GO", self.db.get_cliente_by_cnpj_threadsafe("01234567000195")["uf"])
        self.assertIsNone(self.db.get_cliente_by_cnpj_threadsafe("22.881.305/0001-92")["uf"])
        self.assertIsNone(self.db.get_cliente_by_cnpj_threadsafe("11111111000111"))

    def test_cliente_rejects_invalid_uf_and_updates(self):
        self.assertFalse(self.db.create_cliente("Loja", "22881305000192", "XX"))
        self.db.create_cliente("Loja", "22881305000192")
        cid = self.db.get_cliente_by_cnpj_threadsafe("22881305000192")["id"]
        self.assertTrue(self.db.update_cliente(cid, "Loja", "22881305000192", "sp"))
        self.assertEqual("SP", self.db.get_cliente(cid)["uf"])

    def test_adds_uf_column_to_existing_clientes(self):
        path = Path(self.temp.name) / "old_clientes.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, "
                     "cnpj TEXT UNIQUE NOT NULL, is_active INTEGER DEFAULT 1, "
                     "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO clientes (nome, cnpj) VALUES ('Antiga', '22881305000192')")
        conn.commit(); conn.close()
        db = DatabaseManager(path)
        try:
            self.assertIsNone(db.get_cliente_by_cnpj_threadsafe("22881305000192")["uf"])
        finally:
            db.disconnect()

    def test_migrates_old_erp_check_constraint(self):
        # banco criado pela versao 2.0.0.x, cujo CHECK nao conhece 'vr'
        path = Path(self.temp.name) / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE app_installation (
            id INTEGER PRIMARY KEY CHECK (id = 1), installation_id TEXT NOT NULL UNIQUE,
            erp_type TEXT NOT NULL CHECK(erp_type IN ('intersolid', 'sysmo')),
            configured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("INSERT INTO app_installation (id, installation_id, erp_type) VALUES (1, 'abc', 'sysmo')")
        conn.commit(); conn.close()
        db = DatabaseManager(path)
        try:
            self.assertEqual("sysmo", db.get_installation()["erp_type"])
            self.assertEqual("abc", db.get_installation()["installation_id"])
            db.set_erp_type("vr")
            self.assertEqual("vr", db.get_installation()["erp_type"])
        finally:
            db.disconnect()

    def test_sysmo_and_api_secrets_round_trip(self):
        self.db.save_sysmo_config("db", 5432, "sysmo", "user", "secret")
        self.db.save_oriontax_api_config("https://api.test", "token", batch_size=200, page_size=999)
        self.assertEqual("secret", self.db.get_sysmo_config()["password"])
        api = self.db.get_oriontax_api_config()
        self.assertEqual("token", api["token"])
        self.assertEqual(200, api["batch_size"])
        self.assertEqual(500, api["page_size"])


if __name__ == "__main__":
    unittest.main()
