# MAP: tests/fixtures

> A single-file test fixture: a real, minimal MCP server that speaks the
> protocol over real stdio. It exists so `test_mcp_integration.py` can exercise
> the full MCP path — transport, schema export, registry, precedence, gating,
> invocation — against a running process rather than a mock of one. One of its
> two tools is deliberately named `read_note` to collide with a builtin, which
> is how the registry's precedence aliasing gets tested against a real name.

**Depends on:** `mcp` SDK (the only external import) · **Depended on by:** `test_mcp_integration.py`
**Reads:** nothing · **Writes:** nothing (echoes input back; the `read_note` tool returns a fixed string)

## Files

<!-- map:files:start -->
| File | Loc | Role |
| --- | --- | --- |
| `echo_mcp_server.py` | 38 | A dependency-free MCP server with two tools: `echo` (uppercases input) and `read_note` (returns a prefixed string, colliding with the builtin on purpose). Runs on `MCPServer` 2.x over stdio. |
<!-- map:files:end -->

## Invariants

- This file must remain dependency-free beyond the `mcp` SDK itself. Adding
  anything else would break the test isolation contract.
- The `read_note` tool returns `"mcp read_note: {path}"` — the test asserts
  this literal substring to prove the MCP tool ran, not the builtin.

## See also

- `../MAP.md` — the test suite that exercises this fixture
