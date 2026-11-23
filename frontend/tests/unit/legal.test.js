import { describe, expect, it } from "vitest";

import { reflow, segmentDocument, sidesFor } from "@/lib/legal";

const finding = (start, end, extra = {}) => ({
  rule_id: "R",
  severity: "HIGH",
  title: "t",
  match_start: start,
  match_end: end,
  ...extra,
});

describe("segmentDocument", () => {
  it("highlights exactly the characters the backend pointed at", () => {
    const text = "Pay Rs. 500 within 7 days.";
    const parts = segmentDocument(text, [finding(4, 11)]);
    expect(parts.map((p) => p.text).join("")).toBe(text);
    expect(parts.find((p) => p.finding).text).toBe("Rs. 500");
  });

  it("counts characters the way Python does, not in UTF-16 units", () => {
    // "𝐀" is outside the basic plane: one character to Python, two units to JS.
    const text = "𝐀 term: never compete.";
    const start = Array.from(text).indexOf("n");
    const parts = segmentDocument(text, [finding(start, start + 5)]);
    expect(parts.find((p) => p.finding).text).toBe("never");
  });

  it("keeps the first of two overlapping passages and loses no text", () => {
    const text = "abcdefghij";
    const parts = segmentDocument(text, [finding(2, 6, { rule_id: "A" }), finding(4, 8, { rule_id: "B" })]);
    expect(parts.map((p) => p.text).join("")).toBe(text);
    expect(parts.filter((p) => p.finding).map((p) => p.finding.rule_id)).toEqual(["A"]);
  });

  it("ignores empty and out-of-range spans", () => {
    const parts = segmentDocument("short", [finding(3, 3), finding(2, 99)]);
    expect(parts.map((p) => p.text).join("")).toBe("short");
    expect(parts.find((p) => p.finding).text).toBe("ort");
  });
});

describe("reflow", () => {
  it("keeps every character in place, so offsets still line up", () => {
    const text = "1. TERM\nThe Employee shall\nbe liable to pay\nsalary.\n\n2. PAY\nRs. 24,00,000";
    const flowed = reflow(text);
    expect(flowed).toHaveLength(text.length);
    for (let i = 0; i < text.length; i++) {
      if (text[i] !== "\n") expect(flowed[i]).toBe(text[i]);
    }
  });

  it("joins lines a PDF wrapped mid-sentence", () => {
    expect(reflow("made at Bengaluru on 12 August 2025 between\nVantage Systems India Private Limited, a company"))
      .toBe("made at Bengaluru on 12 August 2025 between Vantage Systems India Private Limited, a company");
    expect(reflow("shall remain in force from\n1 September 2025.")).toBe("shall remain in force from 1 September 2025.");
  });

  it("keeps breaks before clauses, items and headings", () => {
    expect(reflow("first part.\n2. REMUNERATION")).toBe("first part.\n2. REMUNERATION");
    expect(reflow("as follows\n(a) the first")).toBe("as follows\n(a) the first");
    expect(reflow("EMPLOYMENT AGREEMENT\nThis Agreement")).toBe("EMPLOYMENT AGREEMENT\nThis Agreement");
    expect(reflow("end\nSchedule 1 Fees")).toBe("end\nSchedule 1 Fees");
  });
});

describe("sidesFor", () => {
  it("puts the weaker side first, which is who asks for a review", () => {
    const offered = { EMPLOYMENT: ["EMPLOYER", "EMPLOYEE"], LEASE: ["LANDLORD", "TENANT"] };
    expect(sidesFor("EMPLOYMENT", offered)).toEqual(["EMPLOYEE", "EMPLOYER"]);
    expect(sidesFor("LEASE", offered)).toEqual(["TENANT", "LANDLORD"]);
  });

  it("offers only sides the server accepts for that type", () => {
    expect(sidesFor("NDA", { NDA: ["DISCLOSING_PARTY"] })).toEqual(["DISCLOSING_PARTY"]);
    expect(sidesFor("OTHER", { OTHER: ["UNKNOWN"] })).toEqual([]);
  });
});
