# shim/

Stateless ~50-line stdio → HTTP proxy. Each Claude sub-agent that wants to use arXMCP spawns the shim from `~/.claude.json`; the shim forwards JSON-RPC frames to the long-running `server/` process at `127.0.0.1:7733`.

Why a shim is needed (instead of stdio MCP directly): [`.claude/notes/02-architecture-overview.md`](https://github.com/chris-dare-dev/arXMCP/blob/433ba41ba8710be74d6f99c627dce7d3b5383fca/.claude/notes/02-architecture-overview.md) § "Correction 1: MCP transport must be Streamable HTTP, not stdio".
