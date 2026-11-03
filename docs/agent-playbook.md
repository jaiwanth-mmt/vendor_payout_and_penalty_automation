# Agent Playbook & Change Recipes

This playbook provides actionable, step-by-step recipes for software engineers and AI coding agents extending or maintaining the **Agentic Loss Recovery Copilot**.

For in-depth architectural and domain specifications, refer to the modular documentation:
- [System Architecture](architecture.md)
- [Data Pipeline & ETL Engine](pipeline-and-etl.md)
- [Category Processors & SOP Fine Engine](category-processors.md)
- [Complaint Mapping & Message Synthesis](complaint-classification.md)
- [LangGraph Multi-Agent Investigation](langgraph-investigation.md)
- [Human Edit Workspace & Decision Stage](edit-stage-and-human-in-the-loop.md)
- [Packaging & Output Artifacts](packaging-and-artifacts.md)
- [Vendor Penalty Mailer](vendor-mailer.md)
- [LLM Token Usage & Cost Tracking](llm-usage-and-cost.md)
- [REST & SSE API Reference](api-reference.md)
- [Deployment & Operational Runbook](deployment-and-configuration.md)

---

## 1. Common Change Recipes

### Recipe 1: Adding a New Subcategory Processor
1. Define output column requirements in `backend/app/domain/category_processors.py` and register in `CATEGORY_PROCESSORS`.
2. Implement the enrichment worker in a dedicated domain module (e.g. `backend/app/domain/new_category.py`).
3. Register the async worker in `CATEGORY_ASYNC_ENRICHERS`.
4. The pipeline will automatically split batches, invoke the enricher, apply common tracking fields, compute `message`, and run LangGraph per-case investigation.

### Recipe 2: Modifying Vendor No Show SOP Fine Rules
1. Edit `backend/app/domain/fulfillment_not_done.py` (`compute_vendor_no_show_sop_fine`).
2. Current rules:
   - Airport / Local (`ttrip_type` in `{"airport", "local"}`): $\min(0.50 \times \text{amount}, 500)$.
   - Other trip types: $\min(0.25 \times \text{amount}, 2000)$.
   - Quantized to integer with `Decimal ROUND_HALF_UP`.
3. If changing formula or rounding, update unit tests in `backend/tests/test_fulfillment_sop_fine.py`.
4. Ensure `fine_before_sop` and `fine_after_sop` columns remain available for the Edit UI, while `final_output.xlsx` exports only the after-SOP value in `fine`.

### Recipe 3: Modifying Complaint Categories or Aliases
1. Update `ALLOWED_COMPLAINT_CATEGORIES` or `_ALIASES` in `backend/app/domain/complaint_message.py`.
2. If adding aliases or fuzzy matching rules, add corresponding tests to `backend/tests/test_complaint_message.py`.
3. Keep the Remarks-first deterministic priority intact: `Remarks` $\rightarrow$ `Sub Category` (call comments must **never** be used for `message`).

### Recipe 4: Updating the Human Edit Workspace
1. **Backend Routing:** Modify `resolve_edit_bucket` in `backend/app/services/edit_cases.py` to adjust how cases are sorted into `needs_check`, `auto_approved`, or `unhandled`.
2. **Patch Rules:** Adjust `patch_edit_case` in `edit_cases.py` if new editable fields are permitted.
3. **Packaging Integration:** Ensure edits correctly map onto processed frames in `package_builder.apply_case_edits_to_processed_frame`.
4. **Frontend UI:** Update `frontend/src/pages/JobEditPage.tsx` and `frontend/src/components/EditCaseCard.tsx`.
5. Keep contract in sync with `frontend/src/types/jobs.ts` and `backend/app/models.py`.

### Recipe 5: Modifying Live Tracking Queries
1. Edit `backend/app/integrations/tracking_reports.py` or `backend/app/integrations/tracking/repository.py`.
2. In-memory repository for unit tests: Update `InMemoryTrackingRepository` and test fixtures in `backend/tests/factories.py`.
3. Remember that bookings missing `supplier_id` across all tracking rows must be discarded before category processing.

### Recipe 6: Modifying Vendor Penalty Mailer
1. **Templates:** Edit plain-text or HTML email tables in `backend/app/domain/mail_templates.py`. Ensure table keys remain bold (`<strong>`).
2. **Assignment:** Edit recipient-to-booking assignment rules in `backend/app/domain/mail_assignment.py`.
3. **Graph Nodes:** Edit `backend/app/agents/mailer/nodes.py`. Keep template synthesis 100% deterministic (no LLM rewriting).
4. **Dispatch Lifecycle:** Edit preview/send orchestration in `backend/app/services/mailer.py`. Keep SHA-256 `preview_token` verification intact.

### Recipe 7: Modifying LLM Token Accounting & Pricing
1. Update rates or purpose mapping in `backend/app/integrations/llm_usage.py`.
2. When creating new agent nodes or category enrichers, wrap LLM calls in `with llm_purpose("your_purpose"):`.
3. Update `frontend/src/pages/JobUsagePage.tsx` if displaying new usage dimensions.

---

## 2. Invariant Checklist Before Handoff

Before submitting code changes, ensure all of the following hold true:
- [ ] `uv run pytest` passes (all 153 tests green).
- [ ] `cd frontend && npm run build` completes without TypeScript or Vite errors.
- [ ] Final output contract (`final_output.xlsx`) contains exactly 7 columns in order: `booking_id`, `complaint_reasons`, `complaint_against`, `complaint_against_id`, `title`, `message`, `fine`.
- [ ] Excluded cases (`edit_outcome == "exclude"`) are omitted from `final_output.xlsx` and zeroed out in portfolio totals.
- [ ] No external network calls (MySQL, Redash, SMTP) are executed inside LangGraph nodes.
- [ ] No LLMs are invoked in the vendor penalty mailer graph.
- [ ] All new API response fields are reflected in `backend/app/models.py` and `frontend/src/types/jobs.ts`.
