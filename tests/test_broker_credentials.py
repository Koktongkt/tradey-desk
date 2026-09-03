import json
import subprocess
import unittest
from unittest.mock import patch

import broker_credentials


class BrokerCredentialTests(unittest.TestCase):
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
        self.assertEqual(run.call_args.args[0][-2:], ["--json", "mcp_servers.alpaca.env"])

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
