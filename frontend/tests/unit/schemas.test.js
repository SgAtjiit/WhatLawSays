import { describe, expect, it } from "vitest";

import {
  contractAnswer,
  contractDocument,
  contractList,
  contractRecord,
  contractReview,
  scenarioAnalysis,
  supportedOptions,
} from "@/api/schemas";

import answer from "../fixtures/contract-answer.json";
import document from "../fixtures/contract-document.json";
import list from "../fixtures/contract-list.json";
import review from "../fixtures/contract-review.json";
import freelance from "../fixtures/contract-review-freelance.json";
import scenario from "../fixtures/scenario-analysis.json";
import supported from "../fixtures/supported.json";

// These fixtures were recorded from the live backend, and a backend test checks
// them against its Pydantic models, so passing here means passing against it.
describe("responses recorded from the backend", () => {
  it.each([
    ["contract review", contractReview, review],
    ["freelance review", contractReview, freelance],
    ["contract record", contractRecord, review],
    ["document", contractDocument, document],
    ["answer", contractAnswer, answer],
    ["list", contractList, list],
    ["supported options", supportedOptions, supported],
    ["scenario analysis", scenarioAnalysis, scenario],
  ])("%s parses", (_name, schema, data) => {
    expect(schema.safeParse(data).success).toBe(true);
  });

  it("a queued review's status record is told apart from a finished review", () => {
    const queued = contractRecord.parse({ contract_id: "c1", status: "QUEUED", filename: "x.pdf" });
    expect("clauses" in queued).toBe(false);
    expect("clauses" in contractRecord.parse(review)).toBe(true);
  });

  it("a renamed field fails, naming the field", () => {
    const { match_start, ...rest } = review.findings[0];
    const broken = { ...review, findings: [{ ...rest, start: match_start }] };
    const result = contractReview.safeParse(broken);
    expect(result.success).toBe(false);
    expect(result.error.issues[0].path).toEqual(["findings", 0, "match_start"]);
  });
});
