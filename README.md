# Samaan · Mandal Stock

A mobile-friendly Streamlit register for a mandal of 15–20 people. It follows the Samaan design: warm paper background, green sidebar, terracotta actions, serif headings, inventory cards and clear quantity summaries.

## What members can do without login

- Search inventory, filter category and availability, and see current holders.
- Choose their name in **Share my list** and copy a prepared message with all current items and quantities.
- View paginated transaction history and copy return confirmations.

Anyone who can open the Streamlit app can read inventory, member names, holdings and history. No member password is required. WhatsApp numbers are **admin-only**. The existing Sites deployment is separate and its access policy has not been changed.

## What the admin can do after login

- Add an item with name, photo, initial quantity, category and notes.
- Add/edit a member's name and WhatsApp number; pause a member.
- Hand over an available quantity and tag its holder.
- Record partial or full returns, including notes about condition or events.
- Copy holdings/return messages or open them in WhatsApp addressed to the saved number. The admin reviews and presses **Send** in WhatsApp; no automatic messaging service or paid WhatsApp API is used.

Return confirmations include member, item, received quantity, recording date/time in IST, notes and currently outstanding quantity. Historical confirmations label the balance as current when the message is prepared, rather than pretending it was the balance on the historical return date.

## Deploy from GitHub to Streamlit

1. In Streamlit Community Cloud, create an app using this repository, branch `main`, entrypoint **`app.py`**.
2. Add these values in **Advanced settings → Secrets** (or the deployed app's **Settings → Secrets**):

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "CHOOSE_A_UNIQUE_PASSWORD_OF_AT_LEAST_12_CHARACTERS"
MANDAL_NAME = "Our Mandal"
```

Use a dedicated PostgreSQL database or an empty database in your existing database service. The application creates only tables prefixed `mandal_`. Never commit the actual connection URL or password to GitHub. PostgreSQL persists records and compressed photos across Streamlit restarts. Do not use a hosted SQLite file: Streamlit's local filesystem is not a durable database.

For a hashed password instead of `ADMIN_PASSWORD`, run `python generate_password.py` locally and put its output in `ADMIN_PASSWORD_HASH`. When both are present, the hash takes priority. No default admin password is included.

3. Deploy. Visitors can browse without app login; use **Admin** to sign in and enter members/items.

Streamlit's hosting-level sharing setting is separate from this app's admin login. Choose the hosting audience according to your needs; this repository does not modify sharing automatically.

### Lightweight operation

- Metadata snapshots are cached for up to 30 seconds, with immediate cache invalidation after edits and a manual Refresh button.
- No background polling or scheduled jobs.
- Photos resize to at most 1,000 px and under 200 KB, cached separately from inventory metadata; no full photo payload on every metadata read.
- History reads 21 rows per page and displays 20; there is no hidden history cutoff. CSV export covers the displayed page.
- Up to 25 member records. No paid messaging integrations or external API keys.

A database URL is required for production. This code does not provision a database, transfer old Sites records, or deploy itself to Streamlit. Configure the database secret and Streamlit deployment once.

## Local run and validation

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
python -m unittest discover -s tests -v
```

For disposable local testing only, set `ALLOW_LOCAL_SQLITE = true` and `DATABASE_URL = "sqlite:///mandal-local.db"` in your local `.streamlit/secrets.toml`. Real secrets and local database files are gitignored. Tests create temporary SQLite databases and never touch production.

The transaction service locks the relevant inventory row in PostgreSQL (SQLite uses an immediate write transaction in local tests), rechecks stock/holder balances within the transaction, and commits one ledger entry. Unique operation IDs make retries idempotent. Visitors have no write controls and every write path also checks the admin session. Failed admin logins are throttled across sessions; sessions expire after 30 minutes idle or 8 hours absolute.

Database tests cover over-issues, over-returns, partial/full returns, repeated submissions, competing handovers, paused members, phone privacy and admin guards. Streamlit AppTest checks public navigation, copyable messages and admin login controls. Production PostgreSQL deployment should be smoke-tested with your configured database before recording real inventory.
