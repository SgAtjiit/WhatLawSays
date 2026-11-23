from src.agents.contract_state import ContractGraphState
from src.core.logger import pipeline_logger
from src.core.red_flag_rules import verify_quotes

STAGE = "CONTRACT AGENT 8: GROUNDING VERIFIER (QUOTE -> DOCUMENT JUDGE)"


async def run_grounding_verifier(state: ContractGraphState) -> ContractGraphState:
    findings = state.get("findings", [])
    document_text = state.get("document_text", "")
    retry_count = state.get("retry_count", 0)

    pipeline_logger.log_step(
        STAGE,
        f"Auditing {len(findings)} findings against the uploaded document text...",
    )

    # Deliberately not an LLM judge. Whether a quote appears in the document is
    # decided by string comparison, which is exact, free, and cannot itself
    # hallucinate. A model asked to check quotes would introduce the very failure
    # mode this node exists to catch.
    problems = verify_quotes(findings, document_text)

    ungrounded_ids = set()
    ungrounded_clauses = set()
    for finding in findings:
        span = " ".join(document_text[finding.match_start : finding.match_end].split())
        if span != finding.matched_quote:
            ungrounded_ids.add(finding.rule_id)
            if finding.clause_index is not None:
                ungrounded_clauses.add(finding.clause_index)

    # A rule finding that fails to ground is an offset bug, not a hallucination:
    # the rules quote the document by construction. Retrying the model cannot fix
    # it, so it is reported rather than looped on.
    rule_problems = [
        f for f in findings
        if f.detector == "rule"
        and " ".join(document_text[f.match_start : f.match_end].split()) != f.matched_quote
    ]

    # Only a model finding can be repaired by re-prompting. A rule finding that
    # fails to ground is an offset bug: the rules quote the document by
    # construction, so retrying spent three more analyst passes changing nothing.
    # It is still reported -- the compiler drops it -- but it does not drive the loop.
    passed = not [f for f in findings if f.detector == "llm" and f.rule_id in ungrounded_ids]
    feedback = None
    if not passed:
        model_side = [f for f in findings if f.detector == "llm" and f.rule_id in ungrounded_ids]
        feedback = (
            f"{len(problems)} finding(s) quote text that is not present at the offsets given. "
            "Every quote must be copied character for character from the clause text you were "
            "shown. Offending quotes: "
            + "; ".join(f'"{f.matched_quote[:80]}"' for f in model_side[:5])
        )

    pipeline_logger.log_step(
        STAGE,
        (
            f"All {len(findings)} findings verified against the document -> Next: Contract Compiler"
            if passed
            else f"{len(problems)} ungrounded finding(s) across {len(ungrounded_clauses)} clause(s) "
                 f"-> Returning to Red Flag Analyst (attempt {retry_count}/3)"
        ),
        details={
            "quote_problems": problems[:5],
            "rule_finding_problems": len(rule_problems),
        } if problems else None,
        status="SUCCESS" if passed else "RETRY",
    )

    return {
        **state,
        "grounding_passed": passed,
        "grounding_feedback": feedback,
        "ungrounded_clause_indices": sorted(ungrounded_clauses),
        "quote_problems": problems,
    }
