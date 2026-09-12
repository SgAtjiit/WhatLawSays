"""Generate the demo sourcing events.

Written as a script rather than by hand so the events stay internally consistent
-- bid totals matching line items, award values matching the winning bid -- and
so a change to the schema is a change in one place.
"""
import json, pathlib

OUT = pathlib.Path("samples/events")
OUT.mkdir(parents=True, exist_ok=True)

ALL = ["bids", "approvals", "purchase_order", "company_profile",
       "vendor_msme_status", "prior_awards", "rfq_line_item_codes", "budget"]


def vendor(vid, name, **kw):
    base = {"vendor_id": vid, "name": name, "msme_status": "NOT_MSME",
            "on_approved_list": True, "is_related_party": False,
            "processes_personal_data": False}
    base.update(kw)
    return base


def lines(codes, prices):
    return [{"code": c, "line_no": i + 1, "description": c, "quantity": "1",
             "unit_price": str(p), "total": str(p)}
            for i, (c, p) in enumerate(zip(codes, prices))]


def bid(v, total, **kw):
    return {"vendor": v, "total": str(total), "currency": "INR", **kw}


EVENTS = {}

# 1 -- the headline demo: MSMED breach, missing quotes, retro PO, collusion signals
EVENTS["01_conveyor_spares_multiple_breaches"] = {
    "event_id": "EVT-2291", "title": "Conveyor belt spares -- Plant 1",
    "category": "MRO", "business_unit": "Plant-1", "estimated_value": "600000",
    "published_at": "2026-03-02T09:00:00", "closed_at": "2026-03-06T17:00:00",
    "bids": [
        bid(vendor("V-101", "Alpha Traders Pvt Ltd", msme_status="SMALL",
                   udyam_number="UDYAM-MH-18-0042199", msme_status_as_of="2026-01-04",
                   gstin="27AAACA1234A1Z5", pan="AAACA1234A",
                   email="sales@alphatraders.co.in"),
            640000, submitted_at="2026-03-05T11:20:00",
            line_items=lines(["BELT-450", "ROLLER-90", "BEARING-22", "MOTOR-5HP"],
                             [180000, 120000, 90000, 250000])),
        bid(vendor("V-102", "Beta Supply Co", gstin="29AAACA1234A1Z9",
                   email="tenders@alphatraders.co.in"),
            641200, submitted_at="2026-03-05T11:34:00",
            line_items=lines(["BELT-450", "ROLLER-90", "BEARING-22", "MOTOR-5HP"],
                             [180000, 120000, 90000, 251200])),
    ],
    "bids_invited": 4,
    "award": {"vendor_id": "V-101", "value": "640000", "decided_at": "2026-03-10T14:00:00"},
    "approvals": [{"approver_name": "R. Iyer", "approver_role": "MANAGER",
                   "approved_at": "2026-03-12T10:00:00", "stage": "AWARD"}],
    "purchase_order": {"po_number": "PO-2026-0900", "vendor_id": "V-101",
                       "value": "640000", "payment_terms_days": 60,
                       "has_written_agreement": True,
                       "issued_at": "2026-03-11T09:15:00",
                       "goods_accepted_at": "2026-03-28T00:00:00",
                       "linked_event_id": "EVT-2291"},
    "company_profile": {"entity_name": "Acme Manufacturing Ltd", "is_listed": False,
                        "has_audit_committee": True, "related_parties": []},
    "rfq_line_item_codes": ["BELT-450", "ROLLER-90", "BEARING-22", "MOTOR-5HP"],
    "budget_line": "MRO-PLANT1-FY26", "budget_remaining": "700000",
    "provided_collections": ALL,
}

# 2 -- structuring: three orders to one vendor, each just under the threshold
EVENTS["02_split_orders_under_threshold"] = {
    "event_id": "EVT-2310", "title": "Warehouse racking -- phase 3",
    "category": "CAPEX", "business_unit": "Logistics", "estimated_value": "480000",
    "bids": [bid(vendor("V-220", "Sterling Storage Systems"), 480000,
                 submitted_at="2026-04-08T10:00:00", is_responsive=True)],
    "single_source": True,
    "single_source_reason": None,
    "award": {"vendor_id": "V-220", "value": "480000", "decided_at": "2026-04-12T00:00:00"},
    "approvals": [{"approver_role": "MANAGER", "approved_at": "2026-04-11T00:00:00",
                   "stage": "AWARD"}],
    "purchase_order": {"po_number": "PO-2026-1044", "vendor_id": "V-220",
                       "value": "480000", "payment_terms_days": 30,
                       "has_written_agreement": True, "issued_at": "2026-04-12T00:00:00"},
    "prior_awards": [
        {"vendor_id": "V-220", "category": "CAPEX", "value": "470000",
         "decided_at": "2026-03-28T00:00:00", "po_number": "PO-2026-0988"},
        {"vendor_id": "V-220", "category": "CAPEX", "value": "465000",
         "decided_at": "2026-04-02T00:00:00", "po_number": "PO-2026-1001"},
    ],
    "company_profile": {"entity_name": "Acme Manufacturing Ltd", "has_audit_committee": True,
                        "related_parties": []},
    "budget_line": "CAPEX-LOG-FY26", "budget_remaining": "500000",
    "provided_collections": ALL,
}

# 3 -- related party award, no approval on file
EVENTS["03_related_party_award"] = {
    "event_id": "EVT-2355", "title": "Facility management services -- HO",
    "category": "SERVICES", "business_unit": "Corporate", "estimated_value": "2400000",
    "published_at": "2026-05-01T09:00:00", "closed_at": "2026-05-12T17:00:00",
    "bids": [
        bid(vendor("V-310", "Vertex Facilities LLP", is_related_party=True,
                   processes_personal_data=True, has_data_processing_agreement=False),
            2400000, submitted_at="2026-05-10T12:00:00", is_responsive=True),
        bid(vendor("V-311", "Cleanline Services"), 2180000,
            submitted_at="2026-05-11T09:00:00", is_responsive=True),
        bid(vendor("V-312", "Metro Upkeep Pvt Ltd"), 2265000,
            submitted_at="2026-05-11T16:00:00", is_responsive=True),
    ],
    "award": {"vendor_id": "V-310", "value": "2400000", "decided_at": "2026-05-18T00:00:00"},
    "approvals": [{"approver_role": "CFO", "approved_at": "2026-05-17T00:00:00",
                   "stage": "AWARD"}],
    "purchase_order": {"po_number": "PO-2026-1190", "vendor_id": "V-310",
                       "value": "2400000", "payment_terms_days": 45,
                       "has_written_agreement": True, "issued_at": "2026-05-19T00:00:00"},
    "company_profile": {"entity_name": "Acme Manufacturing Ltd", "is_listed": True,
                        "cin": "L27100MH1998PLC114321", "has_audit_committee": True,
                        "related_parties": ["V-310"],
                        "interested_directors": ["S. Vertex"]},
    "provided_collections": ALL,
}

# 4 -- the clean one. Precision is only demonstrable against events that pass.
EVENTS["04_clean_competitive_award"] = {
    "event_id": "EVT-2402", "title": "Industrial lubricants -- annual",
    "category": "MRO", "business_unit": "Plant-2", "estimated_value": "820000",
    "published_at": "2026-06-01T09:00:00", "closed_at": "2026-06-15T17:00:00",
    "bids": [
        bid(vendor("V-401", "Nord Lubricants Ltd"), 790000,
            submitted_at="2026-06-12T11:00:00", is_responsive=True, payment_terms_days=45,
            line_items=lines(["LUB-EP90", "LUB-HY46", "GRS-LT2"], [310000, 280000, 200000])),
        bid(vendor("V-402", "Kavach Petrochem"), 845000,
            submitted_at="2026-06-13T15:30:00", is_responsive=True,
            line_items=lines(["LUB-EP90", "LUB-HY46", "GRS-LT2"], [335000, 295000, 215000])),
        bid(vendor("V-403", "Deccan Oils Pvt Ltd"), 902000,
            submitted_at="2026-06-14T10:10:00", is_responsive=True,
            line_items=lines(["LUB-EP90", "LUB-HY46", "GRS-LT2"], [358000, 314000, 230000])),
    ],
    "bids_invited": 4,
    "award": {"vendor_id": "V-401", "value": "790000", "decided_at": "2026-06-20T00:00:00"},
    "approvals": [{"approver_name": "P. Nandy", "approver_role": "CFO",
                   "approved_at": "2026-06-19T00:00:00", "stage": "AWARD"}],
    "purchase_order": {"po_number": "PO-2026-1288", "vendor_id": "V-401",
                       "value": "790000", "payment_terms_days": 45,
                       "has_written_agreement": True, "issued_at": "2026-06-21T00:00:00",
                       "linked_event_id": "EVT-2402",
                       "line_items": lines(["LUB-EP90", "LUB-HY46", "GRS-LT2"],
                                           [310000, 280000, 200000])},
    "company_profile": {"entity_name": "Acme Manufacturing Ltd", "has_audit_committee": False,
                        "related_parties": []},
    "rfq_line_item_codes": ["LUB-EP90", "LUB-HY46", "GRS-LT2"],
    "budget_line": "MRO-PLANT2-FY26", "budget_remaining": "900000",
    "provided_collections": ALL,
}

# 5 -- the honest-gaps case: almost nothing supplied
EVENTS["05_sparse_payload_mostly_gaps"] = {
    "event_id": "EVT-2450", "title": "Transformer overhaul", "category": "SERVICES",
    "estimated_value": "1800000",
    "bids": [bid(vendor("V-501", "Powergrid Services", msme_status="UNKNOWN",
                        on_approved_list=None, is_related_party=None,
                        processes_personal_data=None), 1800000)],
    "award": {"vendor_id": "V-501", "value": "1800000", "decided_at": "2026-07-04T00:00:00"},
    "provided_collections": ["bids"],
}

# 6 -- supplier's view: a PO whose terms are void against them
EVENTS["06_supplier_view_payment_terms"] = {
    "event_id": "EVT-2480", "title": "Precision machined components",
    "category": "DIRECT", "estimated_value": "1250000",
    "bids": [bid(vendor("V-601", "Sharda Precision Works", msme_status="MICRO",
                        udyam_number="UDYAM-GJ-03-0011884",
                        msme_status_as_of="2025-11-20"),
                 1250000, is_responsive=True, payment_terms_days=45)],
    "award": {"vendor_id": "V-601", "value": "1250000", "decided_at": "2026-07-15T00:00:00"},
    "approvals": [{"approver_role": "CFO", "approved_at": "2026-07-14T00:00:00",
                   "stage": "AWARD"}],
    "purchase_order": {"po_number": "PO-2026-1501", "vendor_id": "V-601",
                       "value": "1250000", "payment_terms_days": 90,
                       "has_written_agreement": True, "issued_at": "2026-07-16T00:00:00",
                       "goods_accepted_at": "2026-08-20T00:00:00"},
    "company_profile": {"entity_name": "Northline Auto Ltd", "has_audit_committee": False,
                        "related_parties": []},
    "provided_collections": ALL,
}

for name, event in EVENTS.items():
    (OUT / f"{name}.json").write_text(json.dumps(event, indent=2) + "\n")
    print(f"  wrote samples/events/{name}.json")
