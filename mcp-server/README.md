# Discogsography MCP Server

Model Context Protocol (MCP) server that exposes the Discogsography knowledge graph to AI assistants like Claude, Cursor, and Zed.

All data is fetched via the Discogsography API — the MCP server has no direct database dependencies.

## Tools

| Tool | Description |
|------|-------------|
| `search` | Full-text search across artists, labels, masters, and releases |
| `get_artist_details` | Detailed artist info (genres, styles, groups, release count) |
| `get_label_details` | Label info with release count |
| `get_release_details` | Release info (title, year, artists, labels, genres, styles) |
| `get_genre_details` | Genre info with artist count |
| `get_style_details` | Style (sub-genre) info with artist count |
| `find_path` | Shortest path between any two entities in the graph |
| `get_trends` | Release count by year for any entity |
| `get_graph_stats` | Database-wide node counts |
| `get_collaborators` | Artists who share releases with a given artist |
| `get_genre_tree` | Full genre/style hierarchy with release counts |

## Installation

```bash
# From PyPI (when published)
uvx discogsography-mcp

# From source
uv sync --all-extras
```

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "discogsography": {
      "command": "uvx",
      "args": ["discogsography-mcp"],
      "env": {
        "API_BASE_URL": "http://localhost:8004"
      }
    }
  }
}
```

### Claude Code

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "discogsography": {
      "command": "uvx",
      "args": ["discogsography-mcp"],
      "env": {
        "API_BASE_URL": "http://localhost:8004"
      }
    }
  }
}
```

### Cursor / Zed

Use the same `command` and `args` in your editor's MCP server configuration.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:8004` | Base URL for the Discogsography API |

## Transport

- **stdio** (default): For local use with Claude Desktop, Cursor, Zed
- **streamable-http**: For hosted deployments

```bash
# stdio (default)
discogsography-mcp

# streamable-http
discogsography-mcp --transport streamable-http
```

## Example Queries

With the MCP server connected, AI assistants can answer questions like:

- "Find me jazz labels active in the 1960s"
- "What's the shortest path between Brian Eno and J Dilla?"
- "Show me the genre distribution of releases on Blue Note"
- "Which artists have the most releases in the Electronic genre?"
- "What are the release trends for Warp Records over time?"
- "Who did Miles Davis collaborate with most often?"
- "Show me the complete genre hierarchy — what styles belong to Electronic?"
