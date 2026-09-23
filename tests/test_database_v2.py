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
