# MiDAS web portal — deploy guide

> **LIVE: https://midas.nuwaslab.com** (deployed 2026-10-11 via AWS CLI).
> App Runner service `midas` in `us-east-1`, image from ECR `midas:latest`, custom domain ACTIVE with
> auto-TLS, instance 0.25 vCPU / 1 GB. Redeploy after a catalog change: `scripts/push_to_ecr.sh` then
> `scripts/aws/deploy_apprunner.sh` (or `aws apprunner start-deployment --service-arn <arn>`).
>
> **GOTCHA that cost three failed deploys:** App Runner does **not** reliably honor the image's default
> Docker `CMD` — the container started with no command, exited instantly, and (being CREATE_FAILED) kept
> no application logs. Fix: set an explicit **`ImageConfiguration.StartCommand`** (see
> `scripts/aws/apprunner-source.json`). Diagnosis path: a public sample image deployed fine (ruled out
> account/roles), a trivial `python -m http.server` start command ran (ruled out the base image), then a
> *failed update* to a running service preserved the logs and confirmed the command was the issue.

One FastAPI app (`server.py`) serves the UI (`static/index.html`) **and** the live pipeline API
(`/api/datasets`, `/api/discover`, `/api/ingest`) from a single origin. Target host: **AWS App Runner**
(runs the Python container, custom domain + automatic TLS, scales toward ~$0 when idle). Domain:
**nuwaslab.com** (recommended target `midas.nuwaslab.com`). Validated locally as both `uvicorn server:app`
and the built Docker image: all endpoints return correctly, discover de-dups, and the image contains only
public files (no dev scripts or docs).

## 0. Run locally first
```bash
pip install -r requirements.txt
uvicorn server:app --port 8080
# open http://localhost:8080   (health: /api/health, API docs: /api/docs)
```

## 1. Build + test the container locally
```bash
docker build -t midas .
docker run -p 8080:8080 midas     # test at http://localhost:8080
```
`.dockerignore` keeps dev/doc files OUT of the image (dev scripts, docs, candidates.tsv). The image
contains only: server.py, discover.py, ingest.py, datasets*.tsv, static/.

---

## AWS prerequisites (one time)

**Recommended path = App Runner pulling a container image from ECR.** (App Runner's *other* source type,
"source code from GitHub", does NOT build your Dockerfile — it uses App Runner's managed Python runtime with
an `apprunner.yaml` and checks out the whole repo. ECR is how a Dockerfile-based image deploys.)

**IAM / Identity Center.** An EC2-only policy is not enough. On the Identity Center **permission set** assigned
to you (this is your own lab account), use `AdministratorAccess` for first-time setup, or attach least-privilege:
- `AmazonEC2ContainerRegistryFullAccess` — create the ECR repo + push (PowerUser can't *create* repos)
- `AWSAppRunnerFullAccess` — create/run the service + custom domain
- `AmazonRoute53FullAccess` — add the domain's validation + alias records
- plus `iam:CreateServiceLinkedRole` and create/pass the App Runner **ECR access role** (the console offers
  to create both roles automatically on first deploy)

**CLI credentials.** With SSO: `aws sso login --profile <profile>` (opens a browser, lasts ~8–12h; re-run when
it expires). Re-login after changing the permission set so the new scope takes effect.

## 2a. Deploy to App Runner from ECR  (recommended)
```bash
AWS_PROFILE=<profile> REGION=us-east-1 bash scripts/push_to_ecr.sh
```
The script checks your identity, creates the `midas` ECR repo (idempotent), logs Docker in, and builds + pushes
the image; it prints the exact image URI and the console steps. Then, in the App Runner console:
1. **Create service → Container registry → Amazon ECR →** pick `midas:latest`.
2. **Port 8080**, **health-check path `/api/health`**. Let it auto-create the service-linked role + ECR access role.
3. Deploy. When it's **Running**, open the default `*.awsapprunner.com` URL to confirm.

Redeploy later (after the catalog grows via `promote.py`): re-run the script, then App Runner → your service →
**Deploy** (or enable automatic deployments so a new `:latest` push ships itself).

CLI alternative to the console (after the first manual deploy has created the ECR access role):
```bash
aws apprunner start-deployment --service-arn <your-service-arn>
```

## 2b. Lightsail (flat ~$7–10/mo) alternative
```bash
aws lightsail create-container-service --service-name midas --power nano --scale 1
aws lightsail push-container-image --service-name midas --label midas --image midas:latest
# then create a deployment with containerPort 8080 and a public endpoint on /api/health
```

## 3. Custom domain (nuwaslab.com, Route 53)
1. You already registered `nuwaslab.com`; its hosted zone is in Route 53.
2. App Runner → your service → **Custom domains** → add **`midas.nuwaslab.com`** (subdomain keeps the apex free
   for a lab homepage; use the apex `nuwaslab.com` instead if you prefer the portal to be the whole site).
3. App Runner returns a set of **CNAME** records (one target + certificate-validation records). Add them in the
   `nuwaslab.com` hosted zone. App Runner then provisions the TLS cert automatically — the domain goes *Active*
   in a few minutes to ~an hour.

## 4. Contact form (Amazon SES)
`POST /api/contact` emails each submission via SES (honeypot + per-IP rate limit + size caps). Setup done:
- **Identities** (us-east-1): domain `nuwaslab.com` verified via Easy DKIM (3 CNAMEs in Route 53) so mail sends
  from `noreply@nuwaslab.com` (send-only; the domain is SES-verified, so any `@nuwaslab.com` from-address works
  without an MX record); recipient `<your-verified-email>` verified (SES **sandbox** only delivers to verified
  addresses — to email anyone, request production access).
- **Permission**: App Runner service runs with instance role `MiDASInstanceRole` (inline `ses:SendEmail`), set via
  `InstanceRoleArn` in `scripts/aws/apprunner-instance.json`.
- **Required env vars** — the code defaults are placeholders (no personal email in the public repo), so set these
  on the service (App Runner → Configuration → Environment variables, or `ImageConfiguration.RuntimeEnvironmentVariables`
  in the source config):
  - `MIDAS_CONTACT_TO` — where submissions are emailed (your verified recipient). Code default: `you@example.com`.
  - `MIDAS_CONTACT_FROM` — the send-only From, e.g. `MiDAS <noreply@nuwaslab.com>` (any address on the verified domain). Code default: `MiDAS <noreply@nuwaslab.com>`.
  - `MIDAS_SES_REGION` — SES region. Code default: `us-east-1`.

  **Keep them across deploys:** these live in the App Runner *service* config, so a plain `start-deployment` (new
  `:latest` image) preserves them — but a config-style `update-service --source-configuration` **replaces**
  `RuntimeEnvironmentVariables`, so re-include both in that call or the form silently reverts to the placeholders.

> **Note on `scripts/aws/`:** the deploy configs are templated with `<ACCOUNT_ID>` — replace it with your AWS
> account ID before using them (the `push_to_ecr.sh` / `deploy_apprunner.sh` scripts resolve the account dynamically).

## Cost (low traffic)
- App Runner: ~$5–25/mo (scales toward the low end when idle). Lightsail nano container: ~$7–10/mo flat.
- Route 53: already paid (~$13/yr domain) + ~$0.50/mo hosted zone. Egress + ECR storage: pennies.

## Hardening before heavy public traffic
- **Rate limit** `/api/discover` and `/api/ingest` (e.g. `slowapi`, per-IP) — they call EuropePMC/ENA, so
  bound external load. Inputs are already capped (n ≤ 15, accession regex) and responses cached in-memory (1h).
- The in-memory cache resets on restart/scale-out; for a shared cache use a small Redis/DynamoDB (optional).
- `/api/discover` runs synchronously (~10–20s for n≤15). Fine for a demo; if N grows, move to a job queue.
- **Catalog is baked into the image** (datasets_hydrated.tsv snapshot). It grows via the local pipeline
  (`promote.py` → commit → re-run `scripts/push_to_ecr.sh` → redeploy). For a continuously-updating catalog,
  move it to S3/DynamoDB and have `server.py` read from there.
- The deployed site is institution-neutral by design; keep internal/dev files out of the image.
