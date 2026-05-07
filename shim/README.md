# shim/

Stateless ~50-line stdio → HTTP proxy. Each Claude sub-agent that wants to use arXMCP spawns the shim from `~/.claude.json`; the shim forwards JSON-RPC frames to the long-running `server/` process at `127.0.0.1:7733`.

Empty until [E01_S09](../.claude/roadmap/epic-01-vertical-slice.md). Why a shim is needed (instead of stdio MCP directly): [`.claude/notes/02-architecture-overview.md`](../.claude/notes/02-architecture-overview.md) § "Correction 1: MCP transport must be Streamable HTTP, not stdio".
