# Cloud Migration Guide

Migrate from local server to full cloud architecture (Vercel + Supabase Cloud).

## Overview

**Before (Local):**
```
Pi → Local Server → Local Supabase
```

**After (Cloud):**
```
Pi → Vercel (Serverless) → Supabase Cloud
```

## Step 1: Set Up Supabase Cloud

### 1. Create Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Create new project
3. Note down:
   - Project URL: `https://your-project.supabase.co`
   - Anon Key (public)
   - Service Role Key (secret)

### 2. Migrate Database Schema

```bash
# Install Supabase CLI if not already
npm install -g supabase

# Link to your cloud project
supabase link --project-ref your-project-ref

# Push local schema to cloud
supabase db push

# Or use SQL dump
pg_dump -h localhost -p 54322 -U postgres -d postgres > backup.sql
psql -h db.your-project.supabase.co -p 5432 -U postgres -d postgres < backup.sql
```

### 3. Configure RLS Policies

In Supabase Dashboard → SQL Editor, run:

```sql
-- Enable RLS on all tables
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE cabinet_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_transactions ENABLE ROW LEVEL SECURITY;

-- Edge API bypasses RLS via service role
-- Regular users use JWT auth
```

## Step 2: Prepare Next.js for Vercel

### 1. Update Environment Variables

Create `.env.production`:

```bash
# Supabase Cloud
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Edge API Secret (for Pi authentication)
EDGE_API_SECRET=your-edge-device-secret-key

# Optional: Disable local Supabase
# SUPABASE_LOCAL=false
```

### 2. Update Edge API Routes

The edge routes need to work with Supabase Cloud. Key changes:

**Before (local):**
```typescript
// Used local Supabase client
const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, ...)
```

**After (cloud):**
```typescript
// Use service role for edge API (bypasses RLS)
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!,
  { auth: { autoRefreshToken: false, persistSession: false } }
)
```

### 3. Update src/utils/supabase/server.ts

For edge API routes to use service role:

```typescript
export function createServiceClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    }
  )
}
```

## Step 3: Deploy to Vercel

### 1. Install Vercel CLI

```bash
npm i -g vercel
```

### 2. Deploy

```bash
cd /path/to/server

# Login (first time)
vercel login

# Deploy
vercel --prod
```

Or use Git integration:
1. Push code to GitHub
2. Import project in Vercel dashboard
3. Set environment variables
4. Deploy

### 3. Configure Environment Variables in Vercel

In Vercel Dashboard → Project → Settings → Environment Variables:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://your-project.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `your-anon-key` |
| `SUPABASE_SERVICE_ROLE_KEY` | `your-service-role-key` |
| `EDGE_API_SECRET` | `your-edge-secret` |

## Step 4: Update Pi Configuration

### 1. Copy Cloud Config

```bash
cd ~/save4223/save4223-cabinet-pi
cp config.cloud.example.json config.json
```

### 2. Edit config.json

```json
{
  "server_url": "https://save4223.vercel.app",
  "edge_secret": "your-edge-api-secret-key",
  "cabinet_id": 1,
  "ssl": {
    "verify": true,
    "cert_path": null
  },
  "api": {
    "timeout": 15,
    "max_retries": 3,
    "retry_delay": 2.0
  }
}
```

### 3. Test Connection

```bash
uv run python test_connection.py
```

## Important Considerations

### 1. Cold Starts (Vercel Serverless)

Vercel functions have cold starts (~1-3 seconds). For Pi API calls:

- **Problem**: Card tap → 3 second delay → unlock
- **Solution**: Use Vercel's "Always On" or reduce cold starts

**Mitigation:**
```javascript
// Add to vercel.json
{
  "functions": {
    "api/edge/**/*.ts": {
      "maxDuration": 10
    }
  }
}
```

Or use **Vercel Pro** for Always On.

### 2. API Timeout Settings

Update Pi config for cloud latency:

```json
{
  "api": {
    "timeout": 15,
    "max_retries": 5,
    "retry_delay": 2.0
  }
}
```

### 3. Offline Mode

The Pi has SQLite for offline operation. When internet is down:
- Uses cached auth data
- Queues sessions for later sync
- Works normally, syncs when back online

### 4. Rate Limits

Vercel has rate limits on free tier:
- 100 GB-hours execution
- 1,000 concurrent invocations
- 10-second max duration (hobby)

For Pi usage, this is plenty.

## Step 5: Test Full Flow

```bash
# On Pi
uv run python -m src.main
```

Test:
1. Card tap → should authenticate via Vercel
2. Unlock → should work
3. Borrow item → should sync to Supabase Cloud
4. Check web UI → should show updated inventory

## Rollback Plan

If cloud doesn't work well:

```bash
# Switch back to local server
# Update Pi config.json:
{
  "server_url": "https://lovelace.tail20b481.ts.net:3001",
  "ssl": {
    "verify": true,
    "cert_path": "/home/pi/.config/tailscale/lovelace.tail20b481.ts.net.crt"
  }
}
```

## Troubleshooting

### Connection Timeout

```bash
# Test API directly
curl "https://save4223.vercel.app/api/health"

# Should return: {"status":"ok"}
```

### 401 Unauthorized

- Check `EDGE_API_SECRET` matches in Vercel and Pi config
- Verify `Authorization: Bearer <secret>` header is sent

### Database Connection Errors

- Check Supabase URL is correct
- Verify service role key has proper permissions
- Check Supabase dashboard for connection issues

### Slow Response

- Cold start on Vercel hobby tier is normal
- Consider Vercel Pro for Always On
- Or stay with local server for production

## Architecture Comparison

| Feature | Local Server | Vercel Cloud |
|---------|-------------|--------------|
| Latency | ~10ms | ~100-500ms |
| Cold Start | None | 1-3 seconds |
| Cost | Free (your hardware) | Free tier available |
| Maintenance | You manage | Managed |
| Offline | Works with cache | Requires internet |
| Scalability | Limited | Unlimited |

## Recommendation

For **production with Pi**:
- Start with **local server + Tailscale** (best latency)
- Use **Vercel** for web UI only
- Keep Pi on local API

For **cloud-only**:
- Accept 1-3 second cold starts
- Use Vercel Pro ($20/mo) for Always On
- Good for multi-location deployments
