# Sample contracts

Eight contracts for driving the review by hand, across the three formats a user
actually uploads. Regenerate with:

```bash
uv run python -m scripts.generate_sample_contracts
```

The wording lives in `scripts/generate_sample_contracts.py`, so what each file
says is readable and reviewable rather than locked in a binary.

These are *not* the evaluation set. `tests/fixtures/eval/` holds the ten
hand-labelled contracts the scoring harness asserts against; these are for
seeing the product work.

## What to upload, and what you should see

Findings below are the deterministic rules, which fire with or without Groq.
With the model reachable you should also get plain-language explanations per
clause and some additional model findings.

| # | File | Review as | Expect |
|---|---|---|---|
| 01 | `01_employment_loaded.pdf` | EMPLOYMENT / EMPLOYEE | **CRITICAL**, 6 findings: non-compete, bond, unilateral arbitrator, IP overreach, perpetual confidentiality, one-sided termination. Plus a **notice-period conflict** (30 days for the Company, 90 for you). |
| 02 | `02_rental_table_terms.docx` | LEASE / TENANT | **HIGH**, 4 findings. The deposit terms exist **only inside a table** — if `EXCESSIVE_SECURITY_DEPOSIT` is missing, table extraction has regressed. Also flags a missing maintenance clause. |
| 03 | `03_freelance_contract.txt` | FREELANCE / SERVICE_PROVIDER | **CRITICAL**, 5 findings incl. uncapped indemnity. Missing: liability cap, confidentiality. |
| 04 | `04_employment_fair.pdf` | EMPLOYMENT / EMPLOYEE | **LOW, zero findings.** The false-positive check. Anything firing here is a bug — a review that cries wolf on a fair contract teaches people to ignore it. |
| 05 | `05_offer_letter_unnumbered.txt` | EMPLOYMENT / EMPLOYEE | **CRITICAL**, 2 findings. No clause numbering at all, so this forces the paragraph fallback; clause numbers will read as `paragraph N`. |
| 06 | `06_scanned_no_text_layer.pdf` | — | **Refused with 422**, "most likely a scan or an image". It must not come back as a clean review. |
| 07 | `07_master_services_long.pdf` | SAAS / CLIENT | **HIGH**, 8 findings over **30 clauses** — exercises the HOT/WARM/COLD triage caps. All three consistency checks fire: a notice conflict, a reference to clause 47 that doesn't exist, and a Schedule A that was never attached. |
| 08 | `08_loan_agreement.docx` | LOAN / BORROWER | **CRITICAL**, 5 findings: unilateral interest variation, ouster of remedy, waiver of statutory rights, unilateral arbitrator, daily penalty. |

## Driving them

**UI** — `uv run streamlit run frontend/app.py`, open Contract Review, upload,
and pick the type and side from the table above. The side is not cosmetic: try
01 as EMPLOYEE and then as EMPLOYER and watch the severities invert.

**API** —

```bash
curl -X POST http://localhost:8000/api/v1/contracts \
  -F "file=@samples/01_employment_loaded.pdf" \
  -F "contract_type=EMPLOYMENT" -F "position=EMPLOYEE"
```

Then, with the `contract_id` it returns:

```bash
curl -X POST http://localhost:8000/api/v1/contracts/$CID/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "what is my notice period"}'

curl -o review.pdf http://localhost:8000/api/v1/contracts/$CID/report.pdf
curl -X DELETE http://localhost:8000/api/v1/contracts/$CID
```

## Worth trying deliberately

- **Upload 04 and 01 back to back.** Same contract type, same side, opposite
  verdicts. This is the clearest demonstration that the rules discriminate.
- **Upload 01 twice, once as EMPLOYEE and once as EMPLOYER.** `BROAD_IP_ASSIGNMENT`
  goes CRITICAL → INFO. The non-compete only drops to MEDIUM, because it is void
  under Contract Act s.27 whoever it favours.
- **Omit the `position` field.** Confidence is capped at 0.65 and the review asks
  you which side you are on, rather than guessing.
- **Ask 07 "what happens if I want to cancel".** The answer cites the clauses it
  used; ask it something the contract is silent on and it says so instead of
  inventing an answer.

Two of these samples found real bugs when first generated: 02 exposed a trailing
schedule being absorbed into the clause above it, and 05 exposed that
`after you leave` was not recognised where `leaving` was. Both are fixed and
covered by `tests/test_regressions.py`.
