// Response shapes, mirroring the backend's Pydantic models in
// backend/src/schemas. Only what this app reads is required; anything else
// passes through untouched.
import { z } from "zod";

const text = z.string();
const maybeText = z.string().nullish();
const list = (item) => z.array(item).default([]);

export const severity = z.enum(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]);

const citation = z.looseObject({
  act: text,
  section_number: text,
  note: z.string().default(""),
});

export const finding = z.looseObject({
  rule_id: text,
  title: text,
  severity,
  clause_index: z.number().int().nullish(),
  clause_number: maybeText,
  matched_quote: text,
  match_start: z.number().int(),
  match_end: z.number().int(),
  harms: list(z.string()),
  citations: list(citation),
  plain_summary: z.string().default(""),
  why_it_matters: z.string().default(""),
  detector: z.string().default("rule"),
  read_confidence: z.number().nullish(),
  evidence_image: maybeText,
});

const clause = z.looseObject({
  index: z.number().int(),
  number: maybeText,
  heading: maybeText,
  category: text,
  tier: text,
  text,
  start_offset: z.number().int(),
  end_offset: z.number().int(),
  page: z.number().int().nullish(),
  plain_english: z.string().default(""),
  obligations: list(z.string()),
  watch_outs: list(z.string()),
  findings: list(finding),
  citations: list(citation),
});

const missingClause = z.looseObject({
  category: text,
  severity,
  title: text,
  why_it_matters: text,
  citations: list(citation),
});

const consistencyIssue = z.looseObject({
  kind: z.string().default(""),
  description: text,
  clause_indices: list(z.number().int()),
  quotes: list(z.string()),
  severity: severity.default("MEDIUM"),
});

const redline = z.looseObject({
  rule_id: text,
  clause_index: z.number().int().nullish(),
  clause_number: maybeText,
  title: text,
  severity,
  ask: text,
  suggested_wording: maybeText,
  fallback: maybeText,
  source: z.string().default("rule"),
});

const confidenceBasis = z
  .looseObject({
    components: z.record(z.string(), z.number()).default({}),
    caps_applied: list(z.string()),
    notes: list(z.string()),
  })
  .nullish();

export const contractReview = z.looseObject({
  contract_id: text,
  status: text,
  contract_type: text,
  position: text,
  position_source: text,
  party_names: z.record(z.string(), z.string()).default({}),
  governing_law: maybeText,
  confidence_score: z.number(),
  confidence_basis: confidenceBasis,
  overall_risk: text,
  risk_counts: z.record(z.string(), z.number()).default({}),
  clause_count: z.number().int(),
  analysed_clause_count: z.number().int(),
  clauses: list(clause),
  findings: list(finding),
  missing_clauses: list(missingClause),
  consistency_issues: list(consistencyIssue),
  redlines: list(redline),
  source: z.string().default("text_layer"),
  ocr_confidence: z.number().nullish(),
  ocr_basis: z.looseObject({ low_confidence_words: z.number().optional() }).nullish(),
  extraction_warnings: list(z.string()),
  degraded_nodes: list(z.string()),
  clarification_questions: list(z.string()),
  disclaimer: z.string().default(""),
});

// GET /contracts/{id} answers with the review once it exists, and with a
// status record while a queued review is still running or has failed.
export const contractRecord = z.union([
  contractReview,
  z.looseObject({
    contract_id: text,
    status: text,
    error: maybeText,
    filename: maybeText,
  }),
]);

export const contractSummary = z.looseObject({
  contract_id: text,
  filename: text,
  contract_type: maybeText,
  position: maybeText,
  status: text,
  overall_risk: maybeText,
  confidence_score: z.number().nullish(),
  clause_count: z.number().int().nullish(),
  created_at: maybeText,
});

export const contractList = z.looseObject({
  items: z.array(contractSummary),
  has_more: z.boolean(),
});

export const contractDocument = z.looseObject({
  contract_id: text,
  text,
  source: z.string().default("text_layer"),
});

export const contractAnswer = z.looseObject({
  contract_id: text,
  question: text,
  answer: text,
  answered_from_contract: z.boolean().default(true),
  cited_clauses: list(
    z.looseObject({
      index: z.number().int(),
      number: maybeText,
      heading: maybeText,
    }),
  ),
  statutory_context: list(citation),
  degraded: z.boolean().default(false),
  disclaimer: z.string().default(""),
});

export const supportedOptions = z.looseObject({
  media_types: z.array(z.string()),
  max_file_bytes: z.number().int(),
  ocr_available: z.boolean(),
  contract_types: z.array(z.string()),
  positions_by_type: z.record(z.string(), z.array(z.string())),
});

const elementAudit = z.looseObject({
  element_name: text,
  status: text,
  evidence_quote: maybeText,
});

const offense = z.looseObject({
  act_name: text,
  section_number: text,
  offense_description: z.string().default(""),
  potential_punishment: z.string().default(""),
  punishment_severity: maybeText,
  cognizable: z.boolean().nullish(),
  bailable: z.boolean().nullish(),
  applicability_status: z.string().default("ESTABLISHED"),
  reasoning_chain: list(z.string()),
  element_audits: list(elementAudit),
  statutory_exceptions: list(
    z.looseObject({ exception_name: text, status: text, legal_effect: z.string().default("") }),
  ),
  relevance_level: z.string().default("DIRECT"),
  provision_category: z.string().default("OFFENSE"),
  source_verified: z.boolean().default(false),
});

export const scenarioAnalysis = z.looseObject({
  status: text,
  scenario_domain: z.string().default("UNKNOWN"),
  offense_status: z.string().default("UNDETERMINED"),
  confidence_score: z.number(),
  confidence_basis: confidenceBasis,
  reason: maybeText,
  extracted_facts: z.looseObject({
    explicit_facts: list(z.string()),
    established_facts: list(z.string()),
    user_allegations: list(z.string()),
    unknown_facts: list(z.string()),
    actor: z.string().default(""),
    action: z.string().default(""),
    object_involved: maybeText,
  }),
  identified_offenses: list(offense),
  applied_defences: list(z.string()),
  procedural_provisions: list(z.string()),
  immediate_action_steps: list(
    z.looseObject({
      step_number: z.number().int(),
      title: text,
      action_details: z.string().default(""),
      statutory_duty_reference: maybeText,
      urgency: z.string().default("HIGH"),
    }),
  ),
  citizen_duties: list(z.string()),
  clarification_questions: list(z.string()),
  excluded_provisions: list(
    z.looseObject({
      act_name: z.string().default(""),
      section_number: z.string().default(""),
      offense_description: z.string().default(""),
      contradicted_elements: list(z.string()),
    }),
  ),
  disclaimer: z.string().default(""),
});

// --- Legal companion ------------------------------------------------------------

export const chatSource = z.looseObject({
  n: z.number().int(),
  act: text,
  short_act: text,
  section_number: text,
  title: z.string().default(""),
  text: z.string().default(""),
  truncated: z.boolean().default(false),
  source_url: maybeText,
  weak: z.boolean().default(false),
});

export const chatMessage = z.looseObject({
  message_id: text,
  role: z.enum(["user", "assistant"]),
  content: text,
  sources: list(chatSource),
  cited: list(z.number().int()),
  degraded: z.boolean().default(false),
  created_at: maybeText,
});

export const conversationSummary = z.looseObject({
  conversation_id: text,
  title: maybeText,
  created_at: maybeText,
  updated_at: maybeText,
});

export const conversation = conversationSummary.extend({ messages: list(chatMessage) });

export const conversationList = z.looseObject({
  items: list(conversationSummary),
  has_more: z.boolean(),
});

/** The events a reply streams, by name. */
export const chatEvents = {
  sources: z.looseObject({ sources: list(chatSource) }),
  delta: z.looseObject({ text: z.string() }),
  done: z.looseObject({ question: chatMessage, answer: chatMessage, title: maybeText }),
  error: z.looseObject({ detail: z.string() }),
};
