# Database Seeding Guide

## Role Permissions Seed

### Problem
The `role_permissions` table must be populated with default RBAC permissions for the application to function correctly. Without this data, users will receive 403 Forbidden errors when accessing dashboards and other protected endpoints.

### Solution
Run the seed script after database migrations to populate the `role_permissions` table.

## Usage

### Local Development
```bash
cd /path/to/sky-poc-backend
python3 scripts/seed_role_permissions.py
```

### Production/Staging (Kubernetes)

#### Option 1: Run as a Kubernetes Job (Recommended)
Create a one-time job to seed the database:

```bash
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: seed-role-permissions
  namespace: your-namespace
spec:
  template:
    spec:
      containers:
      - name: seed
        image: your-backend-image:latest
        command: ["python3", "scripts/seed_role_permissions.py"]
        envFrom:
        - secretRef:
            name: backend-secrets
      restartPolicy: Never
  backoffLimit: 3
EOF
```

Check job status:
```bash
kubectl get jobs -n your-namespace
kubectl logs job/seed-role-permissions -n your-namespace
```

Clean up after success:
```bash
kubectl delete job seed-role-permissions -n your-namespace
```

#### Option 2: Run via kubectl exec
```bash
# Find the backend pod
kubectl get pods -n your-namespace | grep backend

# Execute the seed script
kubectl exec -n your-namespace <backend-pod-name> -- python3 scripts/seed_role_permissions.py
```

### Verification
After running the seed script, verify the data:

```bash
# Via kubectl
kubectl exec -n your-namespace <backend-pod-name> -- \
  psql $DATABASE_URL -c "SELECT role, jsonb_pretty(permissions::jsonb) FROM role_permissions ORDER BY role;"

# Expected output: 4 roles (commander, navigator, explorer, guest)
```

## What Gets Seeded

The script populates 4 roles with their respective permissions:

1. **commander** - Full access (create, edit, delete planets, manage crew, connections, etc.)
2. **navigator** - Most access (create/edit planets, manage spaces/crews, but cannot delete planets or manage connections)
3. **explorer** - Read-only access (view planets, connections, read data tables)
4. **guest** - Minimal access (view planets only)

## Integration with CI/CD

### Add to Deployment Pipeline
Update your deployment workflow to run the seed script after migrations:

```yaml
# Example GitHub Actions workflow
- name: Run Database Migrations
  run: |
    kubectl exec -n $NAMESPACE deployment/backend -- alembic upgrade head

- name: Seed Role Permissions
  run: |
    kubectl exec -n $NAMESPACE deployment/backend -- python3 scripts/seed_role_permissions.py
```

### Add to Dockerfile Init Script
Alternatively, add to your container's entrypoint:

```bash
#!/bin/bash
# In your start.sh or entrypoint script

# Run migrations
alembic upgrade head

# Seed role permissions (idempotent - safe to run multiple times)
python3 scripts/seed_role_permissions.py

# Start application
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Idempotency
The seed script is **idempotent** - it's safe to run multiple times:
- Existing roles are **updated** with current permissions
- Missing roles are **inserted**
- No duplicate entries are created

## Troubleshooting

### Error: "Table role_permissions does not exist"
**Solution**: Run migrations first
```bash
alembic upgrade head
```

### Error: "Connection refused"
**Solution**: Check DATABASE_URL environment variable
```bash
echo $DATABASE_URL
```

### Error: "Permission denied"
**Solution**: Ensure the database user has INSERT/UPDATE permissions on the `role_permissions` table

## Support
For issues, contact the backend development team.
