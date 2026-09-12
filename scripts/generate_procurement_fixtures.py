"""Build the labelled procurement evaluation set.

The events are generated so they stay internally consistent; the labels are
hand-written, because an answer key derived from the engine would only prove the
engine agrees with itself.

Balance follows the contract set: cases with known breaches, plus deliberately
clean ones. The clean events are the ones that matter. A compliance engine that
flags everything is useless, and only an event that ought to pass can show that
it does not.
"""

import json
import pathlib

OUT = pathlib.Path("tests/fixtures/procurement_eval")
EVENTS = OUT / "events"
EVENTS.mkdir(parents=True, exist_ok=True)

ALL = ["bids", "approvals", "purchase_order", "company_profile", "vendor_msme_status",
       "prior_awards", "rfq_line_item_codes", "budget"]


def v(vid, name, **kw):
    base = {"vendor_id": vid, "name": name, "msme_status": "NOT_MSME",
            "on_approved_list": True, "is_related_party": False,
            "processes_personal_data": False}
    base.update(kw)
    return base


def b(vendor, total, **kw):
    return {"vendor": vendor, "total": str(total), "currency": "INR", **kw}


def li(codes, prices):
    return [{"code": c, "line_no": i + 1, "description": c, "quantity": "1",
             "unit_price": str(p), "total": str(p)}
            for i, (c, p) in enumerate(zip(codes, prices))]


def po(number, vendor_id, value, **kw):
    base = {"po_number": number, "vendor_id": vendor_id, "value": str(value),
            "payment_terms_days": 30, "has_written_agreement": True,
            "issued_at": "2026-03-20T00:00:00"}
    base.update(kw)
    return base


def profile(**kw):
    base = {"entity_name": "Acme Manufacturing Ltd", "has_audit_committee": False,
            "related_parties": []}
    base.update(kw)
    return base


def three_good_bids(prefix, base_price):
    """A responsive, ordinary three-bid field that trips nothing on its own."""
    return [
        b(v(f"{prefix}-1", "Nord Industrial Ltd"), base_price, is_responsive=True,
          submitted_at="2026-03-10T10:00:00"),
        b(v(f"{prefix}-2", "Kavach Engineering"), int(base_price * 1.19), is_responsive=True,
          submitted_at="2026-03-11T10:00:00"),
        b(v(f"{prefix}-3", "Deccan Works Pvt Ltd"), int(base_price * 1.41), is_responsive=True,
          submitted_at="2026-03-12T10:00:00"),
    ]


CASES = {}
LABELS = {}


def case(name, event, labels, clean=False):
    event.setdefault("provided_collections", ALL)
    CASES[name] = event
    LABELS[name] = {"clean": clean, "expected": labels}


# --- 1. MSMED: term beyond the 45-day ceiling -------------------------------
case(
    "msmed_term_60_days",
    {
        "event_id": "EV-01", "title": "Bearings", "category": "MRO",
        "bids": three_good_bids("A", 600000),
        "award": {"vendor_id": "A-1", "value": "600000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-01", "A-1", 600000, payment_terms_days=60,
                             goods_accepted_at="2026-04-01T00:00:00",
                             paid_at="2026-06-30T00:00:00"),
        "company_profile": profile(),
    },
    [
        ("MSMED_TERM_EXCEEDS_STATUTORY_CAP", "A-1", "BREACH"),
        ("MSMED_PAYMENT_OVERDUE", "A-1", "BREACH"),
        ("MSMED_INTEREST_QUANTUM", "A-1", "UNDETERMINED"),
    ],
)
CASES["msmed_term_60_days"]["bids"][0]["vendor"].update(
    {"msme_status": "SMALL", "udyam_number": "UDYAM-MH-18-0001", "msme_status_as_of": "2026-01-01"}
)

# --- 2. MSMED: 30 days with no written agreement is already outside s.15 ----
case(
    "msmed_no_written_agreement",
    {
        "event_id": "EV-02", "title": "Gaskets", "category": "MRO",
        "bids": three_good_bids("B", 520000),
        "award": {"vendor_id": "B-1", "value": "520000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-02", "B-1", 520000, payment_terms_days=30,
                             has_written_agreement=False),
        "company_profile": profile(),
    },
    [("MSMED_TERM_EXCEEDS_STATUTORY_CAP", "B-1", "BREACH")],
)
CASES["msmed_no_written_agreement"]["bids"][0]["vendor"].update(
    {"msme_status": "MICRO", "udyam_number": "UDYAM-GJ-03-0002"}
)

# --- 3. MSME status unknown: a gap, never a pass ----------------------------
case(
    "msmed_status_unknown",
    {
        "event_id": "EV-03", "title": "Valves", "category": "MRO",
        "bids": three_good_bids("C", 700000),
        "award": {"vendor_id": "C-1", "value": "700000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-03", "C-1", 700000, payment_terms_days=75),
        "company_profile": profile(),
    },
    [
        ("MSMED_TERM_EXCEEDS_STATUTORY_CAP", "C-1", "UNDETERMINED"),
        ("PAYMENT_TERMS_CAP", None, "BREACH"),
    ],
)
CASES["msmed_status_unknown"]["bids"][0]["vendor"]["msme_status"] = "UNKNOWN"

# --- 4. Medium enterprise: outside Chapter V entirely -----------------------
case(
    "msmed_medium_enterprise_not_applicable",
    {
        "event_id": "EV-04", "title": "Castings", "category": "DIRECT",
        "bids": three_good_bids("D", 900000),
        "award": {"vendor_id": "D-1", "value": "900000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-04", "D-1", 900000, payment_terms_days=90),
        "company_profile": profile(),
    },
    [("MSMED_TERM_EXCEEDS_STATUTORY_CAP", "D-1", "NOT_APPLICABLE")],
)
CASES["msmed_medium_enterprise_not_applicable"]["bids"][0]["vendor"]["msme_status"] = "MEDIUM"

# --- 5. Related party, no approval; plus no DPA -----------------------------
case(
    "related_party_no_approval",
    {
        "event_id": "EV-05", "title": "Facility management", "category": "SERVICES",
        "bids": three_good_bids("E", 2400000),
        "award": {"vendor_id": "E-1", "value": "2400000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-05", "E-1", 2400000),
        "company_profile": profile(is_listed=True, has_audit_committee=True,
                                   related_parties=["E-1"]),
    },
    [
        ("RELATED_PARTY_AWARD_UNAPPROVED", "E-1", "BREACH"),
        ("RELATED_PARTY_AUDIT_COMMITTEE_APPROVAL", "E-1", "BREACH"),
        ("VENDOR_PROCESSES_DATA_WITHOUT_DPA", "E-1", "BREACH"),
    ],
)
CASES["related_party_no_approval"]["bids"][0]["vendor"].update(
    {"is_related_party": True, "processes_personal_data": True,
     "has_data_processing_agreement": False}
)

# --- 6. No company profile: the RPT checks cannot run -----------------------
case(
    "related_party_no_company_profile",
    {
        "event_id": "EV-06", "title": "Consultancy", "category": "SERVICES",
        "bids": three_good_bids("F", 800000),
        "award": {"vendor_id": "F-1", "value": "800000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-06", "F-1", 800000),
        "provided_collections": ["bids", "approvals", "purchase_order", "vendor_msme_status"],
    },
    [
        ("RELATED_PARTY_AWARD_UNAPPROVED", "F-1", "UNDETERMINED"),
        ("RELATED_PARTY_AUDIT_COMMITTEE_APPROVAL", "F-1", "UNDETERMINED"),
    ],
)

# --- 7. Policy: too few quotes, wrong approver, retrospective PO ------------
case(
    "policy_quotes_approval_and_retro_po",
    {
        "event_id": "EV-07", "title": "Pumps", "category": "MRO",
        "bids": [b(v("G-1", "Single Source Ltd"), 640000, is_responsive=True,
                   submitted_at="2026-03-10T10:00:00")],
        "award": {"vendor_id": "G-1", "value": "640000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "MANAGER", "approved_at": "2026-03-22T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-07", "G-1", 640000, issued_at="2026-03-20T00:00:00"),
        "company_profile": profile(),
    },
    [
        ("MIN_QUOTES_BY_VALUE", None, "BREACH"),
        ("APPROVAL_AUTHORITY", None, "BREACH"),
        ("APPROVAL_BEFORE_COMMITMENT", None, "BREACH"),
    ],
)

# --- 8. Structuring across a threshold --------------------------------------
case(
    "split_orders_structuring",
    {
        "event_id": "EV-08", "title": "Racking phase 3", "category": "CAPEX",
        "bids": [b(v("H-1", "Sterling Storage"), 480000, is_responsive=True,
                   submitted_at="2026-04-08T10:00:00")],
        "award": {"vendor_id": "H-1", "value": "480000", "decided_at": "2026-04-12T00:00:00"},
        "approvals": [{"approver_role": "MANAGER", "approved_at": "2026-04-11T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-08", "H-1", 480000, issued_at="2026-04-12T00:00:00"),
        "prior_awards": [
            {"vendor_id": "H-1", "category": "CAPEX", "value": "470000",
             "decided_at": "2026-03-28T00:00:00"},
            {"vendor_id": "H-1", "category": "CAPEX", "value": "465000",
             "decided_at": "2026-04-02T00:00:00"},
        ],
        "company_profile": profile(),
    },
    [("SPLIT_PO_AVOIDANCE", "H-1", "BREACH")],
)

# --- 9. Lowest bid passed over, PO uplifted, scope added, over budget -------
case(
    "award_and_order_irregularities",
    {
        "event_id": "EV-09", "title": "Switchgear", "category": "CAPEX",
        "published_at": "2026-03-01T09:00:00", "closed_at": "2026-03-09T17:00:00",
        "bids": [
            b(v("I-1", "Highline Electric"), 1200000, is_responsive=True,
              submitted_at="2026-03-05T10:00:00"),
            b(v("I-2", "Budget Power Systems"), 980000, is_responsive=True,
              submitted_at="2026-03-06T10:00:00"),
            b(v("I-3", "Volt Systems Pvt Ltd"), 1410000, is_responsive=True,
              submitted_at="2026-03-07T10:00:00"),
        ],
        "award": {"vendor_id": "I-1", "value": "1200000", "decided_at": "2026-03-14T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-13T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-09", "I-1", 1320000,
                             line_items=li(["SWG-11KV", "PANEL-A", "EXTRA-CABLE"],
                                           [600000, 500000, 220000])),
        "rfq_line_item_codes": ["SWG-11KV", "PANEL-A"],
        "budget_line": "CAPEX-EL-FY26", "budget_remaining": "1000000",
        "company_profile": profile(),
    },
    [
        ("LOWEST_RESPONSIVE_AWARD", "I-1", "BREACH"),
        ("PO_EXCEEDS_AWARDED_VALUE", None, "BREACH"),
        ("SCOPE_DRIFT", "EXTRA-CABLE", "BREACH"),
        ("BUDGET_AVAILABILITY", None, "BREACH"),
    ],
)

# --- 10. Late bid, short window, unapproved vendor, single source -----------
case(
    "process_irregularities",
    {
        "event_id": "EV-10", "title": "Emergency crane hire", "category": "SERVICES",
        "published_at": "2026-05-10T09:00:00", "closed_at": "2026-05-11T17:00:00",
        "bids": [
            b(v("J-1", "Rapid Lift Services", on_approved_list=False), 420000,
              is_responsive=True, submitted_at="2026-05-12T09:00:00"),
            b(v("J-2", "Metro Cranes"), 455000, is_responsive=True,
              submitted_at="2026-05-11T09:00:00"),
        ],
        "single_source": True, "single_source_reason": None,
        "award": {"vendor_id": "J-1", "value": "420000", "decided_at": "2026-05-14T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-05-13T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-10", "J-1", 420000, issued_at="2026-05-15T00:00:00"),
        "company_profile": profile(),
    },
    [
        ("LATE_BID_REJECTION", "J-1", "BREACH"),
        ("MANDATORY_BID_WINDOW", None, "BREACH"),
        ("APPROVED_VENDOR_REQUIRED", "J-1", "BREACH"),
        ("SINGLE_SOURCE_JUSTIFICATION", None, "BREACH"),
    ],
)

# --- 11. Bid-integrity signals ----------------------------------------------
case(
    "bid_integrity_signals",
    {
        "event_id": "EV-11", "title": "Fabrication", "category": "DIRECT",
        "published_at": "2026-03-01T09:00:00", "closed_at": "2026-03-15T17:00:00",
        "bids": [
            b(v("K-1", "Alpha Fabricators", gstin="27AAACA1234A1Z5", pan="AAACA1234A"),
              1000000, is_responsive=True, submitted_at="2026-03-10T10:00:00",
              submitted_from_ip="10.1.1.5",
              line_items=li(["FAB-A", "FAB-B", "FAB-C"], [400000, 300000, 300000])),
            b(v("K-2", "Beta Fabricators", gstin="29AAACA1234A1Z9"),
              1001200, is_responsive=True, submitted_at="2026-03-10T10:14:00",
              line_items=li(["FAB-A", "FAB-B", "FAB-C"], [400000, 300000, 301200])),
            b(v("K-3", "Gamma Metalworks"), 1400000, is_responsive=True,
              submitted_at="2026-03-11T10:00:00", submitted_from_ip="10.1.1.5"),
        ],
        "award": {"vendor_id": "K-1", "value": "1000000", "decided_at": "2026-03-18T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-03-17T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-11", "K-1", 1000000),
        "company_profile": profile(),
    },
    [
        ("NEAR_IDENTICAL_TOTALS", "K-1,K-2", "INDICATOR"),
        ("IDENTICAL_UNIT_PRICES", "K-1,K-2", "INDICATOR"),
        ("SHARED_IDENTIFIERS", "K-1,K-2", "INDICATOR"),
        ("COVER_BIDDING", "K-3", "INDICATOR"),
    ],
)

# --- 12. Rotation and a competitive-looking single-bid event ----------------
case(
    "rotation_and_single_responsive",
    {
        "event_id": "EV-12", "title": "Painting contract", "category": "SERVICES",
        "published_at": "2026-05-01T09:00:00", "closed_at": "2026-05-15T17:00:00",
        "bids": [
            b(v("L-1", "Colourfast Ltd"), 500000, is_responsive=True,
              submitted_at="2026-05-10T10:00:00"),
            b(v("L-2", "Brushline Co"), 480000, is_responsive=False,
              submitted_at="2026-05-11T10:00:00", disqualified_reason="no EMD"),
            b(v("L-3", "Coatwell Services"), 495000, is_responsive=False,
              submitted_at="2026-05-12T10:00:00", disqualified_reason="late licence"),
        ],
        "award": {"vendor_id": "L-1", "value": "500000", "decided_at": "2026-05-20T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-05-19T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-12", "L-1", 500000, issued_at="2026-05-21T00:00:00"),
        "prior_awards": [
            {"vendor_id": "L-2", "category": "SERVICES", "value": "1", "decided_at": "2026-01-10T00:00:00"},
            {"vendor_id": "L-3", "category": "SERVICES", "value": "1", "decided_at": "2026-02-10T00:00:00"},
            {"vendor_id": "L-1", "category": "SERVICES", "value": "1", "decided_at": "2026-03-10T00:00:00"},
            {"vendor_id": "L-2", "category": "SERVICES", "value": "1", "decided_at": "2026-04-10T00:00:00"},
        ],
        "company_profile": profile(),
    },
    [
        ("ROTATING_WINNERS", None, "INDICATOR"),
        ("SINGLE_RESPONSIVE_BID", "L-1", "INDICATOR"),
    ],
)

# --- 13-15. The clean ones. Precision is only demonstrable against these. ---
case(
    "clean_competitive_award",
    {
        "event_id": "EV-13", "title": "Lubricants", "category": "MRO",
        "published_at": "2026-06-01T09:00:00", "closed_at": "2026-06-15T17:00:00",
        "bids": three_good_bids("M", 790000),
        "award": {"vendor_id": "M-1", "value": "790000", "decided_at": "2026-06-20T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-06-19T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-13", "M-1", 790000, payment_terms_days=45,
                             issued_at="2026-06-21T00:00:00",
                             line_items=li(["LUB-A", "LUB-B"], [400000, 390000])),
        "rfq_line_item_codes": ["LUB-A", "LUB-B"],
        "rate_contract_refs": {"LUB-A": "RC-2026-11", "LUB-B": "RC-2026-11"},
        "budget_line": "MRO-FY26", "budget_remaining": "900000",
        "company_profile": profile(),
    },
    # Clean of breaches, but the rate-contract check cannot run without the
    # contracted prices. A clean event may still carry an honest gap -- that is
    # the point of counting gaps separately from findings.
    [("RATE_CONTRACT_ADHERENCE", "LUB-A,LUB-B", "UNDETERMINED")],
    clean=True,
)

case(
    "clean_msme_supplier_within_terms",
    {
        "event_id": "EV-14", "title": "Machined parts", "category": "DIRECT",
        "published_at": "2026-06-01T09:00:00", "closed_at": "2026-06-20T17:00:00",
        "bids": three_good_bids("N", 1250000),
        "award": {"vendor_id": "N-1", "value": "1250000", "decided_at": "2026-06-25T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-06-24T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-14", "N-1", 1250000, payment_terms_days=45,
                             issued_at="2026-06-26T00:00:00",
                             line_items=li(["MCH-A", "MCH-B"], [700000, 550000])),
        "rfq_line_item_codes": ["MCH-A", "MCH-B"],
        "budget_line": "DIR-FY26", "budget_remaining": "1400000",
        "company_profile": profile(),
    },
    [],
    clean=True,
)
CASES["clean_msme_supplier_within_terms"]["bids"][0]["vendor"].update(
    {"msme_status": "SMALL", "udyam_number": "UDYAM-GJ-03-0099"}
)

case(
    "clean_single_source_justified",
    {
        "event_id": "EV-15", "title": "OEM spare -- proprietary", "category": "MRO",
        "published_at": "2026-07-01T09:00:00", "closed_at": "2026-07-20T17:00:00",
        "bids": [b(v("O-1", "OEM Spares India"), 350000, is_responsive=True,
                   submitted_at="2026-07-10T10:00:00")],
        "single_source": True,
        "single_source_reason": "Proprietary part; OEM is the only authorised supplier in India.",
        "award": {"vendor_id": "O-1", "value": "350000", "decided_at": "2026-07-25T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-07-24T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-15", "O-1", 350000, payment_terms_days=30,
                             issued_at="2026-07-26T00:00:00",
                             line_items=li(["OEM-778"], [350000])),
        "rfq_line_item_codes": ["OEM-778"],
        "budget_line": "MRO-FY26", "budget_remaining": "400000",
        "company_profile": profile(),
    },
    [],
    clean=True,
)

# --- 16. Constant spread needs four bids; three gaps, not two ---------------
case(
    "constant_spread_four_bids",
    {
        "event_id": "EV-16", "title": "Steel plate", "category": "DIRECT",
        "published_at": "2026-08-01T09:00:00", "closed_at": "2026-08-15T17:00:00",
        "bids": [
            b(v("P-1", "Ferro Steels"), 1000000, is_responsive=True,
              submitted_at="2026-08-10T10:00:00"),
            b(v("P-2", "Ispat Traders"), 1050000, is_responsive=True,
              submitted_at="2026-08-11T10:00:00"),
            b(v("P-3", "Metalix Pvt Ltd"), 1102500, is_responsive=True,
              submitted_at="2026-08-12T10:00:00"),
            b(v("P-4", "Girder Supply Co"), 1157625, is_responsive=True,
              submitted_at="2026-08-13T10:00:00"),
        ],
        "award": {"vendor_id": "P-1", "value": "1000000", "decided_at": "2026-08-20T00:00:00"},
        "approvals": [{"approver_role": "CFO", "approved_at": "2026-08-19T00:00:00",
                       "stage": "AWARD"}],
        "purchase_order": po("PO-16", "P-1", 1000000, payment_terms_days=45,
                             issued_at="2026-08-21T00:00:00"),
        "company_profile": profile(),
    },
    [("CONSTANT_SPREAD", None, "INDICATOR")],
)


for name, event in CASES.items():
    (EVENTS / f"{name}.json").write_text(json.dumps(event, indent=2) + "\n")

(OUT / "labels.json").write_text(json.dumps(LABELS, indent=2) + "\n")
flagged = sum(1 for m in LABELS.values() if not m["clean"])
total_labels = sum(len(m["expected"]) for m in LABELS.values())
print(f"[+] {len(CASES)} events ({flagged} with expected findings, "
      f"{len(CASES) - flagged} deliberately clean), {total_labels} labelled outcomes")
