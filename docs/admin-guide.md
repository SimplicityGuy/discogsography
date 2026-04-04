# Admin Guide

## Creating an Admin Account

Admin accounts are created via the `admin-setup` CLI tool inside the API container:

```
docker exec -it discogsography-api-1 admin-setup \
  --email admin@example.com --password <password>
```

Passwords must be at least 8 characters. If the email already exists, the password is updated.

## Listing Admin Accounts

```
docker exec -it discogsography-api-1 admin-setup --list
```

## Accessing the Admin Panel

Navigate to `http://<host>:8003/admin` and log in with your admin credentials.

The monitoring dashboard at `http://<host>:8003` remains public — no login required.

## Triggering an Extraction

Click **Trigger Extraction** in the admin panel. This forces a full reprocessing of all Discogs data files:

- Downloads the latest monthly data from the Discogs S3 bucket
- Reprocesses all files regardless of existing state markers
- Publishes records to RabbitMQ for graphinator and tableinator consumers

The admin panel also supports triggering a **MusicBrainz extraction**, which downloads the latest MusicBrainz JSONL dumps and publishes records to the `discogsography-musicbrainz-{artists,labels,release-groups,releases}` exchanges for brainzgraphinator and brainztableinator consumers.

Use this when:

- A previous extraction failed and you want to retry
- You suspect data corruption and want a clean reprocess
- A new Discogs monthly dump (or MusicBrainz twice-weekly dump) has been published and you don't want to wait for the periodic check

The extraction runs asynchronously. Progress is tracked in the extraction history table.

If an extraction is already running, the trigger returns an error — wait for it to complete first.

## DLQ Management

Dead-letter queues (DLQs) collect messages that consumers failed to process. Each data type has a DLQ per consumer:

| Queue                                                             | Consumer          |
| ----------------------------------------------------------------- | ----------------- |
| `discogsography-discogs-graphinator-artists.dlq`                  | Graphinator       |
| `discogsography-discogs-graphinator-labels.dlq`                   | Graphinator       |
| `discogsography-discogs-graphinator-masters.dlq`                  | Graphinator       |
| `discogsography-discogs-graphinator-releases.dlq`                 | Graphinator       |
| `discogsography-discogs-tableinator-artists.dlq`                  | Tableinator       |
| `discogsography-discogs-tableinator-labels.dlq`                   | Tableinator       |
| `discogsography-discogs-tableinator-masters.dlq`                  | Tableinator       |
| `discogsography-discogs-tableinator-releases.dlq`                 | Tableinator       |
| `discogsography-musicbrainz-brainzgraphinator-artists.dlq`       | Brainzgraphinator |
| `discogsography-musicbrainz-brainzgraphinator-labels.dlq`        | Brainzgraphinator |
| `discogsography-musicbrainz-brainzgraphinator-release-groups.dlq` | Brainzgraphinator |
| `discogsography-musicbrainz-brainzgraphinator-releases.dlq`      | Brainzgraphinator |
| `discogsography-musicbrainz-brainztableinator-artists.dlq`       | Brainztableinator |
| `discogsography-musicbrainz-brainztableinator-labels.dlq`        | Brainztableinator |
| `discogsography-musicbrainz-brainztableinator-release-groups.dlq` | Brainztableinator |
| `discogsography-musicbrainz-brainztableinator-releases.dlq`      | Brainztableinator |

**Purging** permanently deletes all messages in a DLQ. Do this when:

- Messages are known-bad and will never succeed on retry
- After fixing the root cause and retriggering an extraction

Purging cannot be undone.

DLQ names follow the pattern `{exchange-prefix}-{consumer}-{data-type}.dlq`, using the `DISCOGS_EXCHANGE_PREFIX` and `MUSICBRAINZ_EXCHANGE_PREFIX` env vars as the base.

## Phase 3: Metrics History and Trend Analysis

### Queue and Health History Endpoints

Two new endpoints expose time-series metrics for queue depths and service health:

```
GET /api/admin/queues/history?range=<range>
GET /api/admin/health/history?range=<range>
```

Both endpoints require admin authentication (Bearer token).

**Valid range values:**

| Range  | Description             | Data Granularity  |
| ------ | ----------------------- | ----------------- |
| `1h`   | Last 1 hour             | 5-minute buckets  |
| `6h`   | Last 6 hours            | 5-minute buckets  |
| `24h`  | Last 24 hours (default) | 15-minute buckets |
| `7d`   | Last 7 days             | 1-hour buckets    |
| `30d`  | Last 30 days            | 6-hour buckets    |
| `90d`  | Last 90 days            | 1-day buckets     |
| `365d` | Last 365 days           | 1-day buckets     |

Granularity is selected automatically based on the requested range. Omitting the `range` parameter defaults to `24h`.

### Background Metrics Collector

A background collector runs inside the API service and periodically samples queue depths and service health. Collected data is stored in PostgreSQL for historical querying.

The collector interval is controlled by the `METRICS_COLLECTION_INTERVAL` environment variable (default: 300 seconds / 5 minutes).

### New Environment Variables

| Variable                      | Default | Description                                                                              |
| ----------------------------- | ------- | ---------------------------------------------------------------------------------------- |
| `METRICS_RETENTION_DAYS`      | `366`   | How many days of metrics to retain in the database. Older rows are pruned automatically. |
| `METRICS_COLLECTION_INTERVAL` | `300`   | Seconds between each metrics collection cycle in the background collector.               |

Set these in your `docker-compose.yml` or environment file:

```
METRICS_RETENTION_DAYS=366
METRICS_COLLECTION_INTERVAL=300
```

### New Database Tables

Metrics are stored in two PostgreSQL tables:

**`queue_metrics`** — RabbitMQ queue depth snapshots:

| Column                    | Type         | Description                                      |
| ------------------------- | ------------ | ------------------------------------------------ |
| `id`                      | bigint       | Primary key (generated always as identity)       |
| `recorded_at`             | timestamptz  | When the sample was taken                        |
| `queue_name`              | varchar(100) | Name of the RabbitMQ queue                       |
| `messages_ready`          | integer      | Number of ready messages at sample time          |
| `messages_unacknowledged` | integer      | Number of unacknowledged messages at sample time |
| `consumers`               | integer      | Number of active consumers at sample time        |
| `publish_rate`            | real         | Message publish rate                             |
| `ack_rate`                | real         | Message acknowledgement rate                     |

**`service_health_metrics`** — Per-service health check results:

| Column             | Type        | Description                                             |
| ------------------ | ----------- | ------------------------------------------------------- |
| `id`               | bigint      | Primary key (generated always as identity)              |
| `recorded_at`      | timestamptz | When the sample was taken                               |
| `service_name`     | varchar(50) | Name of the service (e.g. `graphinator`, `tableinator`) |
| `status`           | varchar(20) | Health status (`healthy`, `unhealthy`, `unknown`)       |
| `response_time_ms` | real        | Health check response time in milliseconds              |
| `endpoint_stats`   | jsonb       | Per-endpoint latency statistics (API service only)      |

Both tables are indexed on `recorded_at` for efficient range queries. Rows older than `METRICS_RETENTION_DAYS` are pruned automatically.

### Dashboard: Queue Trends and System Health Tabs

The admin panel (`http://<host>:8003/admin`) exposes two new tabs backed by the history endpoints:

- **Queue Trends** — Line charts showing message depth over time for each RabbitMQ queue. Use the range selector (1h / 6h / 24h / 7d / 30d / 90d / 365d) to zoom in or out.
- **System Health** — Status timeline showing per-service health over the selected range. Unhealthy periods are highlighted in red; response time is shown as a secondary series.

Both tabs auto-refresh every 60 seconds and respect the currently selected time range.
