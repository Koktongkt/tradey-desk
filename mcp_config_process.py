"""Raw MCP environment configuration process boundary."""
from runtime_paths import hermes_cli


def read_mcp_env_process(server: str, *, timeout: float, run):
    return run(
        [hermes_cli(), "config", "get", "--raw", "--json", f"mcp_servers.{server}.env"],
        capture_output=True, text=True, timeout=timeout,
    )
