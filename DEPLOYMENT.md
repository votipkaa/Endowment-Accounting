# Deployment & Database Migrations

This document explains how to safely deploy updates without losing data.

## Production Database Setup

Your production database on Render is **completely separate** from your code. The database persists across deployments and code updates.

- **Database**: PostgreSQL on Render (persistent service)
- **Code**: Deployed via GitHub push to Render
- **Key point**: When you deploy new code, it connects to the *same* database that was already there

## Database Migrations (Schema Changes)

When you add new features that require database changes (new columns, tables, etc.), use **Flask-Migrate** to safely update the schema without losing data.

### Step 1: Install Flask-Migrate locally

```bash
pip install -r requirements.txt
```

This includes `Flask-Migrate` and `Alembic`, which handle schema versioning.

### Step 2: Make your model changes

Edit `app/models.py` with your new fields, tables, etc.

```python
class Fund(db.Model):
    # ... existing fields ...
    new_field = db.Column(db.String(200))  # Add this
```

### Step 3: Generate a migration

From the project root, run:

```bash
export FLASK_APP=wsgi:application
flask db migrate -m "Add new_field to Fund"
```

This creates a new file in `migrations/versions/` that describes the schema change.

### Step 4: Review the migration (optional but recommended)

Open the generated file in `migrations/versions/`. It shows the `upgrade()` function (forward changes) and `downgrade()` function (rollback). You can edit if needed.

### Step 5: Test locally

```bash
flask db upgrade
```

This applies the migration to your local database.

### Step 6: Commit and push

```bash
git add migrations/
git commit -m "Add new_field to Fund"
git push origin main
```

### Step 7: Render deploys automatically

When you push to GitHub:

1. Render detects the change and rebuilds
2. The `release` phase in `Procfile` runs: `flask db upgrade`
3. This applies your migration to the production database (no downtime, no data loss)
4. The web process starts with the new code
5. Your new feature is live

## How Migrations Prevent Data Loss

Traditional approach (❌ **Dangerous**):
- Push code that calls `db.create_all()`
- Production database gets recreated
- **All data is lost**

Flask-Migrate approach (✅ **Safe**):
- Migrations are SQL scripts that change the schema incrementally
- Old data is preserved
- Schema evolves safely over time
- Full rollback history if something goes wrong

## Example: Adding a Gift Type Field

You added `gift_type` and `PoolAdjustment` recently. Here's how it should have been handled with migrations:

1. Edit `models.py` → add `gift_type` column
2. Run `flask db migrate -m "Add gift_type to contributions"`
3. Review generated migration
4. Test locally with `flask db upgrade`
5. Commit and push
6. Render runs migration automatically on next deploy

## Common Commands

```bash
# Create initial migration (one-time, already done)
flask db init

# Generate a new migration after model changes
flask db migrate -m "Description of changes"

# Apply pending migrations (happens automatically on Render)
flask db upgrade

# Check migration history
flask db history

# Rollback to previous version (emergency only)
flask db downgrade -1
```

## Before Going Live with Real Data

1. **Test thoroughly on a development environment** with realistic data
2. **Always have backups** of your production database
3. **Never skip migrations** — always use this workflow for schema changes
4. **Version control everything** — migrations are code, treat them that way

## Troubleshooting

**Migration fails on deploy?**
- Check Render logs: `Settings → Logs`
- Run the migration locally first: `flask db upgrade`
- Debug any SQL errors in the generated migration file
- Fix and re-push

**Need to rollback a migration?**
- Run: `flask db downgrade -1` (locally to test)
- Or manually apply the downgrade SQL to production (contact support if unsure)

**Forgot to create a migration?**
- Create it now: `flask db migrate -m "Late migration"`
- Test: `flask db upgrade`
- Push and deploy

## Going Forward

Every time you make a model change:

1. `flask db migrate -m "Description"`
2. Test locally
3. Commit and push
4. Render handles the rest automatically

Your data is safe. Your deployments are automated. Life is good.
