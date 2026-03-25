# Admin Guide

## Creating an Admin Account

Admin accounts are created via the `admin-setup` CLI tool inside the API container:

    docker exec -it discogsography-api-1 admin-setup \
      --email admin@example.com --password <password>

Passwords must be at least 8 characters. If the email already exists, the password is updated.

## Listing Admin Accounts

    docker exec -it discogsography-api-1 admin-setup --list

## Accessing the Admin Panel

Navigate to `http://<host>:8003/admin` and log in with your admin credentials.

The monitoring dashboard at `http://<host>:8003` remains public — no login required.

## Triggering an Extraction

Click **Trigger Extraction** in the admin panel. This forces a full reprocessing of all Discogs data files:

- Downloads the latest monthly data from the Discogs S3 bucket
- Reprocesses all files regardless of existing state markers
- Publishes records to RabbitMQ for graphinator and tableinator consumers

Use this when:

- A previous extraction failed and you want to retry
- You suspect data corruption and want a clean reprocess
- A new Discogs monthly dump has been published and you don't want to wait for the periodic check

The extraction runs asynchronously. Progress is tracked in the extraction history table.

If an extraction is already running, the trigger returns an error — wait for it to complete first.

## DLQ Management

Dead-letter queues (DLQs) collect messages that consumers failed to process. Each data type has a DLQ per consumer:

| Queue | Consumer |
|-------|----------|
| `graphinator-artists-dlq` | Graphinator |
| `graphinator-labels-dlq` | Graphinator |
| `graphinator-masters-dlq` | Graphinator |
| `graphinator-releases-dlq` | Graphinator |
| `tableinator-artists-dlq` | Tableinator |
| `tableinator-labels-dlq` | Tableinator |
| `tableinator-masters-dlq` | Tableinator |
| `tableinator-releases-dlq` | Tableinator |

**Purging** permanently deletes all messages in a DLQ. Do this when:

- Messages are known-bad and will never succeed on retry
- After fixing the root cause and retriggering an extraction

Purging cannot be undone.
