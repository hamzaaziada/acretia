"""Tests for scripts/secret_scan.py. Secrets are assembled at runtime so this file holds no literal secret."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import secret_scan as SS  # noqa: E402

B62 = "Qz7Kp2Lm9Xv4Rt8Yb3Nc6Hd1Wf5Sg0JaUeOi"  # mixed, high entropy filler (36 chars)


def names(text, rel="src/x.py"):
    return [n for _, n, _ in SS.scan_text(rel, text)]


class TruePositives(unittest.TestCase):
    def test_aws_key_id(self):
        self.assertIn("aws-access-key-id", names("k = '" + "AKIA" + "Q7ZP2LM9XV4RT8YB" + "'"))

    def test_aws_secret_near_context(self):
        sec = "wJk3+Qz7Kp2Lm9Xv4Rt8Yb3Nc6Hd1Wf5Sg0Ja/Uq"
        self.assertEqual(len(sec), 40)
        self.assertIn("aws-secret-key", names("aws_secret_access_key = " + sec))

    def test_github_tokens(self):
        for pre in ("gh" + "p_", "gh" + "o_", "gh" + "s_"):
            self.assertIn("github-token", names("t=" + pre + B62))
        self.assertIn("github-token", names("github" + "_pat_" + B62 + "Zy"))

    def test_slack(self):
        self.assertIn("slack-token", names("x=" + "xo" + "xb-" + "8830417295-Qz7Kp2Lm9Xv4"))

    def test_stripe(self):
        self.assertIn("stripe-key", names("s=" + "sk" + "_live_" + B62[:24]))
        self.assertIn("stripe-key", names("s=" + "rk" + "_live_" + B62[:24]))

    def test_openai_and_anthropic(self):
        self.assertIn("openai-style-key", names("k=" + "sk" + "-" + "Qz7Kp2Lm9Xv4Rt8Yb3Nc6Hd1"))
        self.assertIn("anthropic-key", names("k=" + "sk" + "-ant-" + "Qz7Kp2Lm9Xv4Rt8Yb3Nc6Hd1"))

    def test_google(self):
        self.assertIn("google-api-key", names("k=" + "AI" + "za" + B62[:35]))

    def test_private_key_block(self):
        self.assertIn("private-key-block", names("-----" + "BEGIN RSA PRIVATE" + " KEY-----"))
        self.assertIn("private-key-block", names("-----" + "BEGIN PRIVATE" + " KEY-----"))

    def test_generic_assignment(self):
        self.assertIn("generic-secret-assignment", names('password = "' + B62[:20] + '"'))
        self.assertIn("generic-secret-assignment", names("{'api_key': '" + B62[:20] + "'}"))

    def test_env_file_committed(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, ".env"), "w").write("A=1\n")
            open(os.path.join(d, ".env.example"), "w").write("A=\n")
            self.assertEqual(run(["--root", d, d])[0], 1)
            os.remove(os.path.join(d, ".env"))
            self.assertEqual(run(["--root", d, d])[0], 0)


class FalsePositives(unittest.TestCase):
    def test_task_requiring_url(self):
        for t in ("https://x.org/task-requiring-long-description-here",
                  "see ask-the-team-about-things-123 and disk-usage-report-2024-final"):
            self.assertEqual(names(t), [])

    def test_aws_doc_examples(self):
        self.assertEqual(names("AKIAIOSFODNN7EXAMPLE"), [])
        self.assertEqual(names("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"), [])

    def test_hash_and_base64_image(self):
        self.assertEqual(names("sha256: " + "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"), [])
        self.assertEqual(names("src='data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==" + "'"), [])

    def test_low_entropy_and_short(self):
        self.assertEqual(names('password = "aaaaaaaaaaaaaaaa"'), [])
        self.assertEqual(names('token = "short"'), [])

    def test_env_var_name_and_placeholder(self):
        self.assertEqual(names('api_key = "OPENAI_API_KEY_ENV_NAME"'), [])
        self.assertEqual(names('api_key = "your_key_goes_here_ok"'), [])

    def test_allow_marker(self):
        self.assertEqual(names("k=" + "AK" + "IA" + "Q7ZP2LM9XV4RT8YB  # secret-scan: allow"), [])

    def test_fixture_fake_words_only_in_fixtures(self):
        line = 'token = "test_' + B62[:20] + '"'
        self.assertEqual(names(line, "tests/fixtures/a.json"), [])
        self.assertIn("generic-secret-assignment", names(line, "src/a.py"))


class Output(unittest.TestCase):
    def test_masking(self):
        self.assertEqual(SS.mask("abcd" + "efghijkl"), "abcd" + "*" * 8)
        self.assertNotIn("Rt8Yb3", SS.mask(B62))

    def test_exit_codes_and_no_leak(self):
        with tempfile.TemporaryDirectory() as d:
            secret = "gh" + "p_" + B62
            f = os.path.join(d, "a.py")
            open(f, "w").write("x = '" + secret + "'\n")
            rc, out = run(["--root", d, f])
            self.assertEqual(rc, 1)
            self.assertIn("a.py:1: github-token", out)
            self.assertNotIn(secret, out)
            self.assertNotIn(secret[8:], out)
            open(f, "w").write("x = 1\n")
            self.assertEqual(run(["--root", d, f])[0], 0)

    def test_accepts_all_history_flag(self):
        self.assertEqual(run(["--all-history", "false", "--root", ROOT, os.path.join(ROOT, "scripts", "secret_scan.py")])[0], 0)


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SS.main(argv)
    return rc, buf.getvalue()


if __name__ == "__main__":
    unittest.main()
