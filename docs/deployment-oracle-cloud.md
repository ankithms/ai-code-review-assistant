# Deploy on Oracle Cloud Always Free

This guide deploys the complete application to one Oracle Cloud Infrastructure
(OCI) Ampere A1 VM using Docker Compose and Caddy. The VM, its boot volume, and
normal outbound traffic can stay within OCI's Always Free allowances.

Always Free capacity is not guaranteed. VM creation can fail with an "out of
host capacity" message, and Oracle can change its offers. Confirm that every
resource is marked **Always Free eligible** before creating it and review the
[current OCI Free Tier limits](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm).
The deployment is a single point of failure and is best suited to a personal or
low-traffic instance.

## What can be free

OCI currently includes up to 2 Ampere A1 OCPUs and 12 GB of memory in total,
plus 200 GB of combined boot and block-volume storage, in an account's home
region. This guide uses one Arm VM with 2 OCPUs, 12 GB of memory, and a 50 GB
boot volume. Stay within those totals across the entire tenancy.

Oracle generally requires a payment card to verify a new account, but states
that it will not charge the card unless the account is upgraded. A domain name
and Gemini API usage are separate and may cost money. A free DNS hostname can
be used instead of purchasing a domain.

## Prerequisites

Prepare:

- an OCI Free Tier account;
- a hostname, such as `review.example.com`, that can point to the VM;
- a GitHub OAuth app;
- a GitHub token with access to the repositories being reviewed; and
- a Gemini API key.

The GitHub token needs repository metadata and contents access and permission to
read pull requests and create review comments. Grant it access only to
repositories that have authorized sending selected code to the configured AI
provider. Read [the privacy guidance](../PRIVACY.md) before connecting a private
repository.

## 1. Create the Always Free VM

In the OCI Console, create a compute instance in the account's **home region**:

1. Select the Ubuntu 24.04 image for Ampere A1.
2. Choose the `VM.Standard.A1.Flex` shape and verify that it is labeled
   **Always Free eligible**.
3. Allocate 2 OCPUs and 12 GB of memory.
4. Keep the boot volume at 50 GB and verify that total block storage in the
   tenancy remains within the free allowance.
5. Place the instance in a public subnet, assign a public IPv4 address, and add
   your SSH public key.

If A1 capacity is unavailable, try another availability domain in the home
region or retry later. Do not silently choose a paid shape. The smaller
`VM.Standard.E2.1.Micro` shape is x86-compatible but its 1 GB memory is likely
too constrained for this stack and image builds.

Reserve the instance's public IP if the OCI Console offers that choice, then
point the hostname's DNS `A` record to it.

## 2. Open only the web ports

In the subnet security list or a network security group, allow inbound TCP:

- port `22` from your own IP address;
- port `80` from `0.0.0.0/0`; and
- port `443` from `0.0.0.0/0`.

Do not expose ports `3000`, `5050`, `5432`, `6379`, `8000`, `8001`, or `9090`.
The checked-in Compose file binds its published ports to `127.0.0.1` as a
second layer of protection.

Connect to the VM and configure its host firewall:

```bash
ssh ubuntu@VM_PUBLIC_IP
sudo apt update
sudo apt install -y git caddy ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 3. Install Docker

Install Docker Engine and the Compose plugin using Docker's official Ubuntu
instructions. Do not use the obsolete standalone `docker-compose` package.
Allow the deployment user to run Docker, then reconnect so the new group takes
effect:

```bash
sudo usermod -aG docker ubuntu
exit
ssh ubuntu@VM_PUBLIC_IP
docker --version
docker compose version
```

Both application Dockerfiles support the Ampere VM's `linux/arm64`
architecture; no platform override is required.

## 4. Configure the application

Clone the repository and create the environment file:

```bash
git clone https://github.com/OWNER/ai-code-review-assistant.git
cd ai-code-review-assistant
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

Edit `backend/.env` and replace every placeholder. For a deployment at
`review.example.com`, include:

```dotenv
POSTGRES_DB=ai_code_review_assistant
POSTGRES_USER=review_app
POSTGRES_PASSWORD=use-a-long-random-password

GITHUB_ACCESS_TOKEN=replace-with-a-github-token
GITHUB_WEBHOOK_SECRET=use-a-separate-long-random-secret
GOOGLE_API_KEY=replace-with-a-gemini-api-key
GITHUB_CLIENT_ID=replace-with-the-oauth-client-id
GITHUB_CLIENT_SECRET=replace-with-the-oauth-client-secret
ALLOWED_GITHUB_USERS=your-github-login

SESSION_COOKIE_SECURE=true
LOGIN_SUCCESS_REDIRECT=/
CORS_ALLOWED_ORIGINS=https://review.example.com
```

Leave `DATABASE_URL` and `REDIS_URL` unchanged; Compose overrides them with
internal container addresses. Replace the pgAdmin password even if pgAdmin is
unused. Never commit `backend/.env`.

In the GitHub OAuth app, set the callback URL to:

```text
https://review.example.com/api/auth/github/callback
```

## 5. Start the stack

Build and start the Arm-compatible containers:

```bash
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:3000/api/readyz
```

The backend applies Alembic migrations before starting. A healthy response is
`{"status":"ok"}`. If startup fails, inspect the logs:

```bash
docker compose logs --tail=200 backend worker
```

## 6. Enable HTTPS

Replace `/etc/caddy/Caddyfile` with the following, using the real hostname:

```caddyfile
review.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

Validate and reload Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl --fail https://review.example.com/api/readyz
```

Caddy obtains and renews TLS certificates automatically after DNS resolves to
the VM and ports 80 and 443 are reachable.

## 7. Connect GitHub

In the repository's **Settings > Webhooks**, create a webhook with:

- payload URL: `https://review.example.com/api/webhooks/github`;
- content type: `application/json`;
- secret: the exact value of `GITHUB_WEBHOOK_SECRET`; and
- pull request events enabled.

Confirm a successful delivery, open the dashboard, and sign in with the GitHub
account listed in `ALLOWED_GITHUB_USERS`. Open or update a pull request to test
the worker. Inspect both `backend` and `worker` logs if the webhook succeeds but
no review appears.

## Operations

Update the application after taking a backup:

```bash
git pull --ff-only
docker compose up --build -d
docker compose ps
curl --fail https://review.example.com/api/readyz
```

Create a compressed PostgreSQL backup outside the container:

```bash
docker compose exec -T postgres pg_dump -U review_app -d ai_code_review_assistant -Fc > review-db.dump
```

Copy backups off the VM. To restore into the intended database during a
maintenance window:

```bash
docker compose stop backend worker
docker compose exec -T postgres pg_restore -U review_app -d ai_code_review_assistant --clean --if-exists < review-db.dump
docker compose start backend worker
```

The restore replaces database objects. Verify the VM and backup before running
it.

Run retention daily by adding this with `crontab -e`:

```cron
17 3 * * * cd /home/ubuntu/ai-code-review-assistant && /usr/bin/docker compose exec -T backend python -m app.data_retention >> /var/tmp/ai-review-retention.log 2>&1
```

Prometheus remains local on port 9090. Access it through an SSH tunnel:

```bash
ssh -L 9090:127.0.0.1:9090 ubuntu@VM_PUBLIC_IP
```

Then open `http://127.0.0.1:9090` on the local computer.

The Compose stack loads Prometheus alert rules, but it does not include
Alertmanager. Firing rules are visible in the Prometheus UI and do not send
email, Slack, or other notifications. Add and configure Alertmanager before
relying on these rules for operational notification.

## Staying within Always Free

- Keep compute and storage totals within the current Always Free limits.
- Create resources only in the tenancy's home region and select items explicitly
  marked **Always Free eligible**.
- Do not enable paid backups, load balancers, extra volumes, or paid public IP
  options without checking their prices.
- Set an OCI budget alert at a very small amount. Alerts warn about charges but
  do not automatically stop paid resources.
- Recheck OCI's Free Tier terms before resizing or recreating the VM.
