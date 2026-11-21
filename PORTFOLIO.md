# Review synthetic WAF telemetry without an AWS account

The local application and Terraform are separate: the demo never calls AWS or ingests live logs. The historical lab is preserved as a case study, not a deployment prerequisite.

## Two-minute demo

From the repository root with Docker Engine 28+ and Docker Compose:

```sh
docker compose up -d --build --wait
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS -H 'Content-Type: application/json' --data @telemetry/sample.json http://127.0.0.1:8000/events
curl -fsS http://127.0.0.1:8000/summary
docker compose down --volumes
```

Expect readiness, a created event, and one `ALLOW` count for `DemoDefault`. Reposting the same UUID returns 409 without changing the aggregate. The final command erases the demo database. On Windows PowerShell, use `curl.exe` and quote `'@telemetry/sample.json'`.

| Check | Evidence |
|---|---|
| Validation | Only UUID, timezone-aware timestamp, ALLOW/BLOCK action and a bounded rule identifier. Invalid input returns 422 without echoing the input. |
| Persistence | FastAPI injects a small repository class; parameterized SQL inserts events and returns up to 100 grouped counts. Schema is initialized once per Compose volume. |
| Troubleshooting | `/healthz` tests the process; `/readyz` tests access to the table and returns 503 on database errors. |
| Isolation | API binds to host loopback, the database has no published port, and the API container uses a non-root user. No auth or production credentials: synthetic data only. |

Run `python -m pip install -r telemetry/requirements-dev.txt` and `python -m pytest -q telemetry` in a Python 3.12 virtual environment. Set `TEST_DATABASE_URL` to a **disposable** PostgreSQL database for the integration test; it creates and drops an isolated schema. Without it, that test skips. GitHub Actions starts PostgreSQL and also smoke-tests Compose.

## Optional cloud logging

`terraform/` manages CloudWatch delivery for an **existing** regional WAFv2 ACL, with 14-day log retention and header redaction. Run `terraform -chdir=terraform fmt -check`, `terraform -chdir=terraform init -backend=false -lockfile=readonly`, then `terraform -chdir=terraform validate`; CI never applies changes. No live AWS deployment is claimed.

Do not apply over existing logging without reviewing ownership, importing existing resources where appropriate, and checking the plan, permissions and costs. [AWS WAF redaction](https://docs.aws.amazon.com/waf/latest/APIReference/API_LoggingConfiguration.html#WAFV2-Type-LoggingConfiguration-RedactedFields) applies to the rule's matching field: `SingleHeader` does not cover rules using `Headers`. It also does not protect request samples or Security Lake; it is not anonymization. Never submit live logs to this demo.

## Audit and interview evidence

The baseline contained four tracked files and no executable app, Terraform, tests or CI. Removal of the original caption notes left 22 broken historical links; screenshots and raw logs are not available for independent verification. A reported HTTP 500 is not proof of exploitability, and false positive observations are limited to the traffic tested.

| Role | Evidence to demonstrate |
|---|---|
| Adecco Software Engineer Junior | REST contract, OOP repository, SQL grouping and English docs. |
| BairesDev Python Trainee | Python validation, pytest and a PostgreSQL integration test. |
| Deloitte Cloud Junior | AWS WAF logging, CloudWatch retention and troubleshooting with health checks. |
| Stefanini Cloud Engineer JR | Terraform, logs, Git and CI transfer to cloud operations; this project does not demonstrate Azure. |
