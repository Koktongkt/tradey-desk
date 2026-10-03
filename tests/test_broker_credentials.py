import json
import subprocess
import unittest
from unittest.mock import patch

import broker_credentials


class BrokerCredentialTests(unittest.TestCase):
    def test_mcp_process_preserves_raw_command_timeout_and_result(self):
        import importlib.util
        spec = importlib.util.find_spec("mcp_config_process")
        self.assertIsNotNone(spec, "missing MCP process seam")
        helper = __import__("mcp_config_process").read_mcp_env_process
        self.assertTrue(callable(helper))
        completed = subprocess.CompletedProcess([], 7, "raw", "private")
        with patch("subprocess.run", return_value=completed) as run:
            self.assertIs(helper("massive", timeout=17, run=run), completed)
        run.assert_called_once_with(
            ["/opt/hermes/bin/hermes", "config", "get", "--raw", "--json", "mcp_servers.massive.env"],
            capture_output=True, text=True, timeout=17,
        )

    def test_configured_alpaca_env_uses_hermes_mcp_config_not_inherited_env(self):
        configured = {
            "ALPACA_API_KEY": "new-api",
            "ALPACA_SECRET_KEY": "new-secret",
            "ALPACA_PAPER_TRADE": "true",
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(configured), "")
        with patch("broker_credentials.subprocess.run", return_value=completed) as run:
            result = broker_credentials.configured_alpaca_env()
        self.assertEqual(result["ALPACA_API_KEY"], "new-api")
        self.assertEqual(result["ALPACA_SECRET_KEY"], "new-secret")
        self.assertEqual(
            run.call_args.args[0],
            [
                "/opt/hermes/bin/hermes",
                "config",
                "get",
                "--raw",
                "--json",
                "mcp_servers.alpaca.env",
            ],
        )
        self.assertEqual(
            run.call_args.kwargs,
            {"capture_output": True, "text": True, "timeout": 30},
        )

    def test_configured_alpaca_env_fails_closed_when_paper_flag_is_not_true(self):
        configured = {
            "ALPACA_API_KEY": "api",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_PAPER_TRADE": "false",
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(configured), "")
        with patch("broker_credentials.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError):
                broker_credentials.configured_alpaca_env()


if __name__ == "__main__":
    unittest.main()
