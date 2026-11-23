// Vocabulary shared by every screen: how the backend's enums read to a person.

export const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

export const SEVERITY_LABEL = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  INFO: "Note",
};

export function bySeverity(a, b) {
  return SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity);
}

export const CONTRACT_TYPE_LABEL = {
  EMPLOYMENT: "Employment agreement",
  NDA: "Non-disclosure agreement",
  LEASE: "Lease or rental agreement",
  SERVICE: "Services agreement",
  FREELANCE: "Freelance contract",
  VENDOR: "Vendor or supply agreement",
  SAAS: "Software subscription (SaaS)",
  LOAN: "Loan agreement",
  OTHER: "Something else",
  UNKNOWN: "Contract",
};

// The weaker side first: they are who asks for a review, and the default must
// not quietly score the document from the drafter's point of view.
const WEAKER_SIDE_FIRST = {
  EMPLOYMENT: ["EMPLOYEE", "EMPLOYER"],
  NDA: ["RECEIVING_PARTY", "DISCLOSING_PARTY"],
  LEASE: ["TENANT", "LANDLORD"],
  SERVICE: ["SERVICE_PROVIDER", "CLIENT"],
  FREELANCE: ["SERVICE_PROVIDER", "CLIENT"],
  VENDOR: ["SERVICE_PROVIDER", "CLIENT"],
  SAAS: ["CLIENT", "SERVICE_PROVIDER"],
  LOAN: ["BORROWER", "LENDER"],
};

/** The sides a person can take in this kind of contract, weaker side first. */
export function sidesFor(contractType, positionsByType = {}) {
  const offered = positionsByType[contractType] || [];
  const preferred = WEAKER_SIDE_FIRST[contractType] || [];
  const ordered = [
    ...preferred.filter((side) => offered.length === 0 || offered.includes(side)),
    ...offered.filter((side) => !preferred.includes(side)),
  ];
  return ordered.filter((side) => side !== "UNKNOWN");
}

export const POSITION_LABEL = {
  EMPLOYEE: "the employee",
  EMPLOYER: "the employer",
  DISCLOSING_PARTY: "the party sharing information",
  RECEIVING_PARTY: "the party receiving information",
  LANDLORD: "the landlord",
  TENANT: "the tenant",
  CLIENT: "the client",
  SERVICE_PROVIDER: "the service provider",
  LENDER: "the lender",
  BORROWER: "the borrower",
  UNKNOWN: "no particular side",
};

export function sideOption(position) {
  const label = POSITION_LABEL[position] || humanize(position);
  return label.replace(/^the /, "").replace(/^\w/, (c) => c.toUpperCase());
}

export function humanize(value) {
  if (!value) return "";
  const words = String(value).toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const TIER_LABEL = {
  HOT: "Read closely",
  WARM: "Explained",
  COLD: "Rule checks only",
};

export const CONTRACT_COMPONENT_LABEL = {
  segmentation: "Splitting the document into clauses",
  coverage: "Share of clauses analysed",
  grounding: "Quotes found word for word in your document",
  provenance: "Findings backed by fixed rules",
  profile: "Knowing the contract type and your side",
  text_fidelity: "Accuracy of the text we read",
};

export const SCENARIO_COMPONENT_LABEL = {
  offense_support: "How well the facts support each offence",
  retrieval: "How closely the statutes found match the facts",
  verification: "Independent check of the analysis",
  fact_completeness: "How complete the facts are",
  exclusion_evidence: "Evidence for ruling offences out",
};

/** "llm_fallback<=0.60" -> a sentence a person can act on. */
export function explainCap(cap) {
  const [name, limit] = String(cap).split("<=");
  const at = limit ? ` at ${Math.round(Number(limit) * 100)}%` : "";
  // Every cap the backend emits (backend/src/core/confidence.py and
  // contract_confidence.py).
  const reasons = {
    llm_fallback: "The language model was unavailable, so only fixed rules ran",
    reranker_fallback: "The statute ranking model was unavailable",
    ungrounded_quotes: "Some proposed quotes could not be found in your document and were dropped",
    unknown_position: "You did not say which side you are on",
    guessed_clause_boundaries: "The document has no clause numbering, so clause boundaries are a guess",
    read_by_ocr: "The document was read from an image",
    ungrounded_citation: "A cited section could not be matched to the statute text",
    undetermined: "The facts do not settle whether an offence was committed",
  };
  const reason = reasons[name] || humanize(name);
  return `${reason}. Confidence is capped${at}.`;
}

export function percent(score) {
  return `${Math.round((score ?? 0) * 100)}%`;
}

export function confidenceWord(score) {
  if (score >= 0.8) return "High";
  if (score >= 0.6) return "Moderate";
  if (score >= 0.4) return "Limited";
  return "Low";
}

/**
 * Split text into plain runs and highlighted passages.
 *
 * Offsets come from Python, which counts code points; JavaScript strings count
 * UTF-16 units, which differ for any character outside the basic plane. So the
 * text is sliced as an array of code points. Overlapping findings keep the
 * first passage, as the reviewer reads it from the top.
 */
export function segmentDocument(text, findings) {
  const chars = Array.from(text);
  const spans = findings
    .map((finding, order) => ({ finding, order }))
    .filter(({ finding }) => finding.match_end > finding.match_start)
    .sort((a, b) => a.finding.match_start - b.finding.match_start || a.order - b.order);

  const segments = [];
  let cursor = 0;
  for (const { finding } of spans) {
    const start = Math.max(finding.match_start, 0);
    const end = Math.min(finding.match_end, chars.length);
    if (start < cursor || start >= end) continue;
    if (start > cursor) segments.push({ text: chars.slice(cursor, start).join("") });
    segments.push({ text: chars.slice(start, end).join(""), finding });
    cursor = end;
  }
  if (cursor < chars.length) segments.push({ text: chars.slice(cursor).join("") });
  return segments;
}

export function findingKey(finding) {
  return `${finding.rule_id}:${finding.match_start}:${finding.match_end}`;
}

export function formatBytes(bytes) {
  if (bytes >= 1_048_576) return `${Math.round(bytes / 1_048_576)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

export function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

// A line that starts something new: a numbered clause ("4." "4.2" "4)"), a
// lettered item ("(a)"), a bullet, a named division, or a heading in capitals.
const CLAUSE_MARKER = /^\s*(?:\d+(?:\.\d+)*[.)]\s|\((?:[a-z]|[ivx]{1,4}|\d{1,2})\)\s|[-•*]\s)/;
const DIVISION = /^\s*(?:article|clause|section|schedule|annexure|appendix)\s+[\w.]+/i;
const CAPS_HEADING = /^\s*[A-Z][A-Z0-9 ,&'()-]{2,}$/;
const ENDS_A_SENTENCE_BLOCK = /[:;]\s*$/;

function startsABlock(line) {
  return CLAUSE_MARKER.test(line) || DIVISION.test(line) || CAPS_HEADING.test(line);
}

/**
 * Text lifted from a PDF keeps the PDF's line breaks, which break again in a
 * narrower column. Join wrapped lines back into paragraphs, keeping blank lines
 * and any break before a clause or heading.
 *
 * Each joined newline becomes exactly one space, so the result has the same
 * length and every finding's offsets still point at the same characters.
 */
export function reflow(text) {
  const lines = text.split("\n");
  let out = "";
  for (let i = 0; i < lines.length; i++) {
    out += lines[i];
    if (i === lines.length - 1) break;
    const here = lines[i];
    const next = lines[i + 1];
    const keep =
      !here.trim() ||
      !next.trim() ||
      startsABlock(next) ||
      CAPS_HEADING.test(here) ||
      ENDS_A_SENTENCE_BLOCK.test(here) ||
      /[-–]$/.test(here);
    out += keep ? "\n" : " ";
  }
  return out;
}
