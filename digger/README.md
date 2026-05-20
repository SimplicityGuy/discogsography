# Digger

Discogs marketplace scraper and wantlist intelligence worker for the Digger feature.

Scrapes Discogs marketplace listing pages via a Redis token-bucket rate budget, stores results in the `digger.*` PostgreSQL schema, and exposes health + Prometheus metrics on port 8012.

## Ports

| Endpoint  | Port |
| --------- | ---- |
| Health    | 8012 |
| Metrics   | 8012 |

## Environment Variables

| Variable                    | Default                                                                | Required |
| --------------------------- | ---------------------------------------------------------------------- | -------- |
| `POSTGRES_HOST`             | —                                                                      | Yes      |
| `POSTGRES_USERNAME`         | —                                                                      | Yes      |
| `POSTGRES_PASSWORD`         | —                                                                      | Yes      |
| `POSTGRES_DATABASE`         | —                                                                      | Yes      |
| `REDIS_HOST`                | —                                                                      | Yes      |
| `DIGGER_SCRAPER_USER_AGENT` | `discogsography-digger/0.1 (github.com/SimplicityGuy/discogsography)` | No       |
| `DIGGER_RATE_BUDGET_PER_HOUR` | `600`                                                                | No       |
| `DIGGER_CB_WINDOW_SECONDS`  | `300`                                                                  | No       |
| `DIGGER_CB_FAILURE_PCT`     | `30`                                                                   | No       |
| `DIGGER_CB_COOLDOWN_SECONDS` | `1800`                                                                | No       |
| `LOG_LEVEL`                 | `INFO`                                                                 | No       |

All `*_PASSWORD` and `*_USERNAME` variables support the `_FILE` suffix for Docker secrets.
