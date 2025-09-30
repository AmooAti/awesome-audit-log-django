# Migration Guide: Timestamp Fix for Async Logging

## Overview

**Version**: Below 1.0.0
**Issue Fixed**: Audit log timestamps now correctly reflect when events occur, not when they're saved to the database.

### The Problem

In previous versions, when using async logging (with Celery), audit log timestamps were captured at database INSERT time, not when the actual event occurred. This caused incorrect timestamps when there was a delay between event occurrence and database persistence.

**Example of the problem:**

- Event occurs at `2025-09-30 10:00:00`
- Celery processes the task at `2025-09-30 10:00:05` (5 seconds later)
- Old behavior: `created_at` shows `10:00:05` ❌
- New behavior: `created_at` shows `10:00:00` ✅

### What Changed

1. **Timestamp Capture**: The `created_at` timestamp is now captured in application code when the signal fires, not as a database DEFAULT value
2. **Database Schema**: The `created_at` column no longer uses DEFAULT constraints
3. **Payload**: The timestamp is now included in the audit payload and explicitly inserted

### Breaking Changes

⚠️ **Database Schema Change Required**

The `created_at` column definition has changed:

**PostgreSQL:**

```sql
-- Old
created_at TIMESTAMPTZ DEFAULT NOW()

-- New
created_at TIMESTAMPTZ NOT NULL
```

**MySQL:**

```sql
-- Old
`created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP

-- New
`created_at` TIMESTAMP NOT NULL
```

**SQLite:**

```sql
-- Old
created_at TEXT DEFAULT (datetime('now'))

-- New
created_at TEXT NOT NULL
```

### Migration Steps

#### Option 1: Fresh Start (Development Only)

If you're in development and can afford to lose audit logs:

1. Drop all `*_log` tables
2. Update the package
3. Tables will be recreated with the new schema automatically

```sql
-- PostgreSQL/MySQL
DROP TABLE IF EXISTS your_model_log;

-- SQLite
DROP TABLE IF EXISTS your_model_log;
```

#### Option 2: Alter Existing Tables (Production)

For production environments where you need to preserve existing audit logs:

**PostgreSQL:**

```sql
-- Remove DEFAULT, keep existing timestamps
ALTER TABLE your_model_log
  ALTER COLUMN created_at DROP DEFAULT,
  ALTER COLUMN created_at SET NOT NULL;
```

**MySQL:**

```sql
-- Remove DEFAULT, keep existing timestamps
ALTER TABLE your_model_log
  MODIFY COLUMN `created_at` TIMESTAMP NOT NULL;
```

**SQLite:**

```sql
-- SQLite requires table recreation
-- 1. Rename old table
ALTER TABLE your_model_log RENAME TO your_model_log_old;

-- 2. Create new table with correct schema (will be auto-created on first insert)
-- Let the application create it, then:

-- 3. Copy data from old table
INSERT INTO your_model_log
  SELECT * FROM your_model_log_old;

-- 4. Drop old table
DROP TABLE your_model_log_old;
```

#### Option 3: Automated Migration Script

We provide a Django management command to help with migration:

```bash
# Dry run to see what would be changed
python manage.py migrate_audit_timestamps --dry-run

# Run the actual migration
python manage.py migrate_audit_timestamps

# Skip confirmation prompts
python manage.py migrate_audit_timestamps --force

# Migrate a specific database
python manage.py migrate_audit_timestamps --database=audit_db
```
