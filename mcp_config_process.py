"""Raw MCP environment configuration process boundary."""


def read_mcp_env_process(server: str, *, timeout: float, run):
    return run(
        ["/opt/hermes/bin/hermes", "config", "get", "--raw", "--json", f"mcp_servers.{server}.env"],
        capture_output=True, text=True, timeout=timeout,
    )
