# AWS IRSA for the voice pipeline + demo seed

These manifests let the backend pod get **short-lived AWS credentials** for the
voice pipeline (Amazon Transcribe STT + Amazon Polly TTS) via **IRSA** (IAM
Roles for Service Accounts) — replacing the temporary 4-hour SSO credentials we
currently export by hand. Plus a one-shot Job to seed the demo/review account.

## ⚠️ Read first — cloud mismatch to reconcile

The existing manifests in `k8s/` target **Azure** (`*.azurecr.io` image,
`azure-keyvault` ClusterSecretStore, `serviceAccountName: default` for Azure
Workload Identity). But the CI (`.github/workflows/build-and-push-aws.yml`)
pushes to **AWS ECR** (`741375879811.dkr.ecr.eu-west-1`) and the voice pipeline
calls **AWS** Transcribe/Polly. "IRSA" is an **AWS/EKS** concept.

So before applying: confirm which cloud production actually runs on.
- **AWS EKS** → use these files as-is (IRSA).
- **Azure AKS** → IRSA does not apply; instead bind an Azure Workload Identity
  to a federated principal (or an IAM role via web-identity) that AWS trusts,
  or provision a scoped IAM user and store its keys in the secret. Tell me the
  target and I'll produce that variant.

These files assume the **AWS EKS** target implied by ECR + the voice services.

## What's here

| File | What it is |
|---|---|
| `iam-voice-permissions.json` | IAM **permissions** policy — Transcribe streaming + Polly. Attach to the role. |
| `iam-trust-policy.json` | IAM **trust** policy — lets the EKS OIDC provider assume the role for this ServiceAccount. |
| `serviceaccount.yaml` | The `sky-poc-backend` ServiceAccount annotated with the role ARN. |
| `../seed-demo-job.yaml` | Manual one-shot Job that runs `seed_demo.py` to bootstrap the demo/review account. |

## Setup (infra owner, one time per environment)

1. **Get the cluster OIDC provider host** (no `https://`):
   ```
   aws eks describe-cluster --name <CLUSTER> \
     --query "cluster.identity.oidc.issuer" --output text | sed 's#https://##'
   ```
   Put it into `iam-trust-policy.json` in place of `OIDC_PROVIDER_HOST`, and set
   `NAMESPACE` (e.g. `staging` / `production`).

2. **Create the role + attach the policy:**
   ```
   aws iam create-role --role-name SKY_BACKEND_VOICE_ROLE \
     --assume-role-policy-document file://iam-trust-policy.json
   aws iam put-role-policy --role-name SKY_BACKEND_VOICE_ROLE \
     --policy-name sky-voice --policy-document file://iam-voice-permissions.json
   ```

3. **Annotate + use the ServiceAccount:** apply `serviceaccount.yaml` (with the
   role ARN filled in), and change `serviceAccountName: default` →
   `sky-poc-backend` on the **Deployment**, the **migrate Job**, and the
   **worker** (anything that touches voice).

4. **Verify** inside a pod:
   ```
   aws sts get-caller-identity      # should show .../SKY_BACKEND_VOICE_ROLE
   ```
   Then a voice session works with **no** exported SSO creds and no
   `VOICE_STT_PROVIDER` juggling.

## Also required for store review (config, not IRSA)

Add `MFA_EXEMPT_EMAILS` to this environment's secret store (the value the code
reads via `settings.MFA_EXEMPT_EMAILS`), so the reviewer signs in without MFA:

```
MFA_EXEMPT_EMAILS = demo@skyfirstlabs.com
```

Wire it in `external-secret.yaml` the same way as the other keys, and keep it
**only** in review/staging — never point it at a real customer account.

## Demo seed

After migrations, run the seed once (see the header of `../seed-demo-job.yaml`).
It creates the demo tenant, `demo@skyfirstlabs.com` / `SkyDemo!2026`, and demo
content. Idempotent, so safe to re-run.
