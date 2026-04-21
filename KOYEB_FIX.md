# Koyeb Deployment Fix

## Issues Found

1. **SQLite Database Error**: `unable to open database file`
   - The `data/` directory may not exist or be writable
   - **Solution**: Use `DATABASE_URL` (Supabase PostgreSQL) for production instead of SQLite

2. **Nginx Error**: Missing closing bracket for BACKEND_URL
   - This error is from frontend deployment, not backend
   - Backend doesn't use nginx

## Fix Applied

✅ Code updated to:
- Automatically create `data/` directory if it doesn't exist
- Better error handling for database initialization
- Dockerfile ensures data directory has write permissions

## Required: Set Environment Variables in Koyeb

**IMPORTANT**: For production on Koyeb, you **MUST** set `DATABASE_URL` to use Supabase PostgreSQL instead of SQLite.

### Required Environment Variables in Koyeb Dashboard:

```
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
DATABASE_URL=postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres
```

### How to Get DATABASE_URL from Supabase:

1. Go to your Supabase project dashboard
2. Navigate to **Settings** → **Database**
3. Find **Connection string** → **URI**
4. Copy the connection string
5. Replace `[YOUR-PASSWORD]` with your database password
6. Set it as `DATABASE_URL` in Koyeb

Example format:
```
postgresql://postgres.xxxxx:[PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

## Why SQLite Fails on Koyeb

- Koyeb uses ephemeral filesystems (data can be lost)
- SQLite files may not persist between deployments
- File permissions can be restrictive
- **PostgreSQL (via Supabase) is the recommended solution for production**

## Verification

After setting `DATABASE_URL`:
1. Redeploy your backend on Koyeb
2. Check logs - you should see "Database initialized successfully"
3. Test health endpoint: `https://your-app.koyeb.app/api/health`

## If You Must Use SQLite (Not Recommended)

If you absolutely need SQLite for some reason:
1. The code now creates the `data/` directory automatically
2. Ensure the directory is writable (Dockerfile sets permissions)
3. Note: Data will be lost on redeployment (ephemeral storage)

