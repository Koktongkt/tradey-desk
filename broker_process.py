"""Pinned broker launch mechanics; retry and response policies stay with callers."""


def bridge_command(root, operation: str, *, executable: str) -> list[str]:
    return [executable, "run", "--with", "fastmcp<4", "python",
            str(root / "broker_mcp_bridge.py"), operation]


def run_bridge(command, *, input: str, timeout: int, run, **kwargs):
    """Launch once without interpreting output or catching runner exceptions.

    Forward only supplied options: omitted cwd/check must remain omitted.
    The caller supplies its runner to retain its subprocess patch seam.
    """
    return run(command, input=input, text=True, capture_output=True,
               timeout=timeout, **kwargs)
