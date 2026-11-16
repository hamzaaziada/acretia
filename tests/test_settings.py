"""Settings: whitelist, .env merge, masking, removal."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.env = d / ".env"
        self.store = d / "keys" / "secrets.env"
        # never touch the real Keychain from tests
        self._p = mock.patch.dict(os.environ, {"OM_KEYSTORE": "file", "OM_KEYSTORE_FILE": str(self.store)})
        self._p.start()
        self.addCleanup(self._p.stop)
        self.env.write_text('SEC_USER_AGENT="MeshPool AI x@y.z"\n# comment\nOM_MODEL_DEFAULT="openai"\n')

    def iso(self):
        return {"OM_KEYSTORE": "file", "OM_KEYSTORE_FILE": str(self.store)}

    def test_save_merges_and_masks(self):
        with mock.patch.dict(os.environ, {"OM_KEYSTORE": "file", "OM_KEYSTORE_FILE": str(self.store)}, clear=True):
            st = settings.save(self.env, {"DEEPSEEK_API_KEY": "sk-abcdef123456", "OM_MODEL_DEFAULT": "deepseek:deepseek-chat"})
            text = self.env.read_text()
            self.assertIn('SEC_USER_AGENT="MeshPool AI x@y.z"', text)          # untouched
            self.assertIn("# comment", text)
            self.assertIn('OM_MODEL_DEFAULT="deepseek:deepseek-chat"', text)   # replaced in place
            self.assertEqual(text.count("OM_MODEL_DEFAULT"), 1)
            self.assertNotIn("sk-abcdef123456", text)                             # keys never go into .env
            self.assertIn("DEEPSEEK_API_KEY=sk-abcdef123456", self.store.read_text())  # they go to the key store
            self.assertEqual(oct(self.store.stat().st_mode & 0o777), "0o600")
            self.assertEqual(st["keys"]["deepseek"], {"env": "DEEPSEEK_API_KEY", "set": True, "hint": "••••3456"})
            self.assertNotIn("sk-abcdef123456", str(st))                          # never echoed back
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-abcdef123456")   # live without restart
            self.assertEqual(oct(self.env.stat().st_mode & 0o777), "0o600")
            settings.save(self.env, {"DEEPSEEK_API_KEY": ""})
            self.assertNotIn("DEEPSEEK_API_KEY", self.env.read_text())
            self.assertNotIn("DEEPSEEK_API_KEY", os.environ)

    def test_rejects_unknown_vars_and_bad_values(self):
        with mock.patch.dict(os.environ, self.iso(), clear=True):
            with self.assertRaises(ValueError):
                settings.save(self.env, {"PATH": "/tmp"})
            with self.assertRaises(ValueError):
                settings.save(self.env, {"OM_MODEL_DEFAULT": "deepseek chat; rm -rf"})
            with self.assertRaises(ValueError):
                settings.save(self.env, {"OPENAI_API_KEY": "abc\nEVIL=1"})
            with self.assertRaises(ValueError):
                settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "file:///etc/passwd"})

    def test_custom_provider_sets_key_env(self):
        with mock.patch.dict(os.environ, self.iso(), clear=True):
            settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "http://gpu:8000/v1", "OM_MODEL_DEFAULT": "custom:Qwen/Qwen2.5-72B"})
            self.assertEqual(os.environ["OM_PROVIDER_CUSTOM_API_KEY_ENV"], "CUSTOM_API_KEY")

    def test_test_without_model(self):
        with mock.patch.dict(os.environ, self.iso(), clear=True):
            r = settings.test("sheets_agent")
            self.assertFalse(r["ok"])


class SecurityTests(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.env, self.store = d / ".env", d / "keys" / "secrets.env"
        self.env.write_text('SEC_USER_AGENT="x"\n')
        self._p = mock.patch.dict(os.environ, {"OM_KEYSTORE": "file", "OM_KEYSTORE_FILE": str(self.store)}, clear=True)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_key_is_bound_to_its_host(self):
        from om import llm
        settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "https://api.meshpool.example/v1", "CUSTOM_API_KEY": "mp-secret-123456"})
        self.assertEqual(os.environ["OM_PROVIDER_CUSTOM_KEY_HOST"], "api.meshpool.example")
        self.assertNotIn("mp-secret", self.env.read_text())
        with self.assertRaises(ValueError):           # moving the endpoint needs the key again
            settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "https://evil.example/v1"})
        os.environ["OM_PROVIDER_CUSTOM_BASE_URL"] = "https://evil.example/v1"        # even if .env is edited by hand…
        with self.assertRaises(llm.LLMError):
            llm.make_provider("custom:m")                                             # …the key isn't sent there

    def test_no_key_over_plain_http(self):
        from om import llm
        with self.assertRaises(ValueError):
            settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "http://api.remote.example/v1", "CUSTOM_API_KEY": "mp-secret-123456"})
        settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "http://localhost:8000/v1", "CUSTOM_API_KEY": "local-key-123456"})
        self.assertEqual(llm.make_provider("custom:m").base_url, "http://localhost:8000/v1")
        with self.assertRaises(ValueError):
            settings.save(self.env, {"OM_PROVIDER_CUSTOM_BASE_URL": "https://user:pw@host.example/v1"})

    def test_keys_found_in_env_file_are_moved_out(self):
        self.env.write_text('SEC_USER_AGENT="x"\nDEEPSEEK_API_KEY="sk-plaintext-999999"\n')
        self.assertEqual(settings.migrate(self.env), ["DEEPSEEK_API_KEY"])
        self.assertNotIn("sk-plaintext", self.env.read_text())
        self.assertIn("sk-plaintext-999999", self.store.read_text())

    def test_web_refuses_other_sites_and_hosts(self):
        from email.message import Message
        from om import web
        H = web.make_handler.__code__  # noqa: F841  (handler is built per server; test the guard directly)
        handler_cls = web.make_handler.__globals__["make_handler"]
        sent = []

        class Fake:
            pass
        import om.search as search
        idx = search.Index(Path(tempfile.mkdtemp()) / "s.db")
        cls = handler_cls(idx, Path(tempfile.mkdtemp()) / "s.db", Path(tempfile.mkdtemp()))
        h = cls.__new__(cls)
        h.path = "/api/settings"
        h._json = lambda obj, code=200: sent.append(code)

        def headers(**kw):
            m = Message()
            for k, v in kw.items():
                m[k.replace("_", "-")] = v
            return m
        h.headers = headers(Host="localhost:8791", Origin="http://localhost:8791", Sec_Fetch_Site="same-origin")
        self.assertTrue(h._allowed(write=True))
        h.headers = headers(Host="localhost:8791", Origin="https://evil.example", Sec_Fetch_Site="cross-site")
        self.assertFalse(h._allowed(write=True))
        h.headers = headers(Host="localhost:8791", Origin="http://localhost:3000", Sec_Fetch_Site="same-site")
        self.assertFalse(h._allowed(write=True))
        h.headers = headers(Host="attacker.example:8791")                                 # DNS rebinding
        self.assertFalse(h._allowed(write=False))
        h.headers = headers(Host="127.0.0.1:8791")                                         # curl / CLI, no Origin
        self.assertTrue(h._allowed(write=True))
        self.assertEqual(sent, [403, 403, 403])


if __name__ == "__main__":
    unittest.main()
