# Public demo synthetic dataset

This dataset is a small, realistic e-commerce dataset (customers,
products, orders, order_items) the SKY public demo (Cenário B) lets
visitors query. It's read-only — every demo Space gets a Connection
record pointing at this Postgres, but the demo guest user has no
write privilege.

## What's in here

| Table       | Rows | Purpose                                       |
| ----------- | ---- | --------------------------------------------- |
| customers   | 40   | Wide enough for "top N customers" queries     |
| products    | 20   | Covers Subscription / Service / Add-on / Support / Usage |
| orders      | ~600 | 14 months of activity with realistic spread   |
| order_items | ~1.5k| 1-4 line items per order                      |

Every name is fictional (Northwind / Acme / Wonka / etc.). Email
domains use the `*.example` reserved TLD so nothing accidentally
hits a real inbox.

## Provisioning

1. Spin up a dedicated Postgres (Azure Database for PostgreSQL Flexible
   Server, smallest tier — the dataset is ~1 MB). **Do not reuse the
   application DB.**

2. Create a read-only role:

   ```sql
   CREATE ROLE demo_reader LOGIN PASSWORD '<strong>';
   GRANT CONNECT ON DATABASE demo_dataset TO demo_reader;
   GRANT USAGE ON SCHEMA public TO demo_reader;
   ```

3. Load the seed:

   ```bash
   psql "$DEMO_ADMIN_DB_URL" -f scripts/demo/seed.sql
   ```

4. Lock down access AFTER the seed (so the migration could run as
   the admin role, but visitors only read):

   ```sql
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO demo_reader;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO demo_reader;
   REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
   ```

5. Inside the SKY app, create a Connection record pointing at this
   Postgres using the `demo_reader` role. Either via the UI (login
   as a real owner, Settings → Connections) or directly:

   ```sql
   -- inside the application DB
   INSERT INTO data_connections (id, name, source_type, ...)
   VALUES ('<uuid>', 'Demo — Sample E-commerce', 'postgresql', ...);
   ```

6. Copy the new connection's UUID into the BE env:

   ```yaml
   # gitops/charts/common-app/values-sky-be-stg.yaml
   DEMO_DATASET_CONNECTION_ID: "<uuid>"
   ```

   When this is set, `DemoService.signup()` automatically wires the
   new Space to the demo connection so visitors land on a populated
   dashboard instead of an empty one.

## Re-seeding

The seed script is idempotent (TRUNCATE before INSERT). Schedule a
nightly cron on the demo Postgres to re-run it — keeps the dataset
fresh and wipes any side-effects of edge-case writes that slipped
through.

```bash
# crontab on the demo DB host:
0 3 * * * psql "$DEMO_ADMIN_DB_URL" -f /opt/sky/scripts/demo/seed.sql
```

## Sample questions the AI chat can answer

These map cleanly onto the schema and exercise the SQL specialist
end-to-end. Worth pinning a few of them as starter prompts on the
demo Space's first dashboard.

- "Who are my top 5 customers by total revenue?"
- "What was monthly revenue over the last 12 months?"
- "Average order value by customer plan."
- "Which products are best-selling by quantity?"
- "Cancellation rate by month."
- "Orders trending up vs down vs last quarter?"
- "Customers I haven't seen an order from in 60 days."
