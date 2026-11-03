# Deployment, Configuration & Operational Runbook

This document provides a guide for environment setup, configuration options, performance tuning, operational verification, and troubleshooting.

---

## 1. Environment Variable Reference

The application loads configuration from a `.env` file located at the repository root. A template is provided in `.env.example`.

### A. Live Tracking (MySQL HTTP API & Direct DB)

| Variable | Default Value | Required? | Description |
| :--- | :--- | :---: | :--- |
| `MYSQL_API_URL` | `http://cabs-incabs-ryde-reports.prd.mmt.internal/scripts/mysql/runQuery` | **Yes** | Primary internal HTTP query service for live tracking rows and supplier joins. |
| `MYSQL_API_TIMEOUT_SECONDS` | `60.0` | No | HTTP request timeout for database queries. |
| `MYSQL_DATABASE` | `incabs_blocks_and_confirms` | **Yes** | Database name hosting tracking and supplier tables. |
| `MYSQL_TABLE_NAME` | `tracking_reports_raw` | **Yes** | Live tracking table name. |
| `MYSQL_SUPPLIERS_TABLE_NAME` | `incabs_suppliers` | **Yes** | Supplier metadata table for vendor name resolution. |
| `MYSQL_BATCH_SIZE` | `100` | No | Batch size for `IN (...)` booking ID lookups. |
| `MYSQL_HOST` | `10.212.92.159` | No | Legacy fallback host if `MYSQL_API_URL` is omitted. |
| `MYSQL_PORT` | `3307` | No | Legacy fallback MySQL port. |
| `MYSQL_USER` | `incabs_blocks_and_confirms_stg` | No | Legacy fallback MySQL username. |
| `MYSQL_PASSWORD` | *(empty)* | No | Legacy fallback MySQL password. |

---

### B. Customer Call Transcripts (Redash API)

| Variable | Default Value | Required? | Description |
| :--- | :--- | :---: | :--- |
| `REDASH_API_KEY` | *(empty)* | **Recommended** | API key for Redash. If omitted, jobs proceed with empty comments. |
| `REDASH_HOST` | `http://common-redash.mmt.com` | No | Redash instance URL. |
| `REDASH_SOURCE_IDS` | `10` | No | Redash data source ID for MyDesk / vortex call tables. |
| `REDASH_BATCH_SIZE` | `250` | No | Batch size for Redash booking ID queries. |

---

### C. Azure OpenAI & LLM Concurrency

| Variable | Default Value | Required? | Description |
| :--- | :--- | :---: | :--- |
| `AZURE_OPENAI_CHAT_COMPLETIONS_URL` | *(empty)* | **Yes** | Full chat completions deployment endpoint. |
| `AZURE_OPENAI_API_KEY` | *(empty)* | **Yes** | Secret API key for Azure OpenAI. |
| `CATEGORY_PROCESSING_CONCURRENCY` | `4` | No | Parallel subcategory batches processed concurrently. |
| `LLM_CONCURRENCY` | `3` | No | Parallel LLM calls allowed across all subcategories. |
| `CAB_DELAY_LLM_CONCURRENCY` | `3` | No | Deprecated fallback alias for `LLM_CONCURRENCY`. |

---

### D. LLM Pricing & Cost Estimation

| Variable | Default Value | Description |
| :--- | :---: | :--- |
| `LLM_INPUT_USD_PER_1M` | **1.25** | Uncached prompt input rate ($ USD per 1M tokens). |
| `LLM_OUTPUT_USD_PER_1M` | **10.00** | Completion output rate ($ USD per 1M tokens). |
| `LLM_CACHED_INPUT_USD_PER_1M` | **0.13** | Cached prompt input rate ($ USD per 1M tokens). |
| `LLM_MODEL_NAME` | *(Auto-detected)* | Model name override (defaults to deployment name from URL or `gpt-5`). |

---

### E. Vendor Penalty Mailer (SMTP)

| Variable | Default Value | Required? | Description |
| :--- | :--- | :---: | :--- |
| `SMTP_HOST` | `smtpmail.mmt.com` | **Yes** | Corporate SMTP server. |
| `SMTP_PORT` | `587` | **Yes** | Standard SMTP submission port. |
| `SMTP_USER` | `noreply-depot@makemytrip.com` | **Yes** | SMTP account username. |
| `SMTP_PASSWORD` | *(empty)* | **Yes** | Secret SMTP password (stored only in `.env`). |
| `SMTP_FROM` | `noreply-depot@makemytrip.com` | **Yes** | Sender email address. |
| `SMTP_STARTTLS` | `true` | No | Whether to negotiate STARTTLS encryption. |
| `SMTP_TLS_VERIFY` | `false` | No | Set to `false` for internal enterprise CA (`smtpmail.mmt.com`). |
| `SMTP_TIMEOUT_SECONDS` | `30` | No | Socket timeout for SMTP network calls. |
| `MAILER_RECIPIENTS` | *(comma-separated)* | **Yes** | Comma-separated list of recipient emails receiving penalty drafts. |

---

## 2. Installation & Local Development

### Prerequisites
- Python 3.12+ with `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Node.js 18+ and `npm`.

### Quickstart Commands

```bash
# 1. Clone repository and enter directory
cd vendor_payout_and_penalty_automation-git

# 2. Configure environment variables
cp .env.example .env
# Edit .env with your credentials

# 3. Install backend dependencies
uv sync

# 4. Install frontend dependencies
cd frontend && npm install && cd ..

# 5. Start Backend API Server (Port 8000)
uv run uvicorn backend.app.main:app --reload

# 6. Start Frontend Development Server (Port 5173)
cd frontend && npm run dev
```

---

## 3. Concurrency Tuning & Scaling

When processing workbooks covering wide date ranges (thousands of bookings), tune concurrency in `.env`:

1. **High-Throughput Setting:**
   ```bash
   CATEGORY_PROCESSING_CONCURRENCY=6
   LLM_CONCURRENCY=10
   ```
   *Caution:* Ensure your Azure OpenAI quota supports the peak request rate to prevent `429 Too Many Requests`.
2. **Conservative / Rate-Limited Setting:**
   ```bash
   CATEGORY_PROCESSING_CONCURRENCY=2
   LLM_CONCURRENCY=2
   ```

Always restart Uvicorn after modifying `.env`.

---

## 4. Verification & Testing Runbook

Before deploying changes, run the automated verification suite:

```bash
# 1. Execute full backend test suite (153 unit & integration tests)
uv run pytest

# 2. Verify frontend TypeScript types and production build
cd frontend && npm run build
```

The Pytest suite uses an `InMemoryTrackingRepository` and mock transports; it never requires live database or SMTP connectivity to pass.

---

## 5. Troubleshooting & Operational Guidance

### A. Warning: `supplier_id_missing`
- **Cause:** One or more bookings have tracking rows where `supplier_id` is entirely NULL, empty, or missing.
- **Behavior:** These bookings are safely discarded before category processing because no vendor can be identified for penalty deduction.
- **Action:** No action required; the system logs the discarded IDs in the job warnings banner.

### B. Warning: `tracking_not_found`
- **Cause:** Bookings present in the uploaded workbook were not found in `tracking_reports_raw`.
- **Behavior:** The pipeline continues, processing the cases with available Excel data while logging a warning.

### C. SMTP Connection Refused or Certificate Errors
- **Issue:** `SmtpError: [SSL: CERTIFICATE_VERIFY_FAILED]`
- **Resolution:** Set `SMTP_TLS_VERIFY=false` in `.env`. Internal enterprise servers like `smtpmail.mmt.com` utilize private CAs that standard OS root stores do not recognize.

### D. Redash Call Comments Missing
- **Cause:** `REDASH_API_KEY` is omitted or invalid.
- **Behavior:** Jobs complete normally, but the `comments` column remains empty.
- **Resolution:** Set a valid API key in `REDASH_API_KEY`.

