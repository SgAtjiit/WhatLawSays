from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ScenarioDomain(str, Enum):
    POTENTIAL_CRIMINAL = "POTENTIAL_CRIMINAL"
    CIVIL = "CIVIL"
    CONSTITUTIONAL = "CONSTITUTIONAL"
    PROCEDURAL = "PROCEDURAL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class OffenseStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    UNDETERMINED = "UNDETERMINED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScenarioRequest(BaseModel):
    scenario_text: str = Field(
        ..., description="Raw text description from the citizen."
    )
    jurisdiction: str = Field(
        default="India", description="Applicable legal jurisdiction"
    )


class ExtractedFacts(BaseModel):
    explicit_facts: List[str] = Field(
        default=[], description="Facts explicitly stated by the user without modification"
    )
    established_facts: List[str] = Field(
        default=[], description="Objective, undisputed facts explicitly stated by user"
    )
    user_allegations: List[str] = Field(
        default=[], description="Subjective claims or accusations made by the user/actor"
    )
    unknown_facts: List[str] = Field(
        default=[], description="Facts that are indeterminate/unknown. UNKNOWN != FALSE and UNKNOWN != TRUE"
    )
    actor: str = Field(..., description="Primary actor who committed the action")
    action: str = Field(..., description="Core action performed")
    object_involved: Optional[str] = Field(
        None, description="Object or property involved"
    )
    scenario_domain: str = Field(
        default="POTENTIAL_CRIMINAL",
        description="POTENTIAL_CRIMINAL, CIVIL, CONSTITUTIONAL, PROCEDURAL, MIXED, or UNKNOWN",
    )
    offense_status: str = Field(
        default="UNDETERMINED",
        description="ESTABLISHED, NOT_ESTABLISHED, UNDETERMINED, or NOT_APPLICABLE",
    )
    should_early_exit: bool = Field(
        False, description="True ONLY if prompt is completely vacuous/unintelligible"
    )


class ElementAudit(BaseModel):
    element_name: str = Field(..., description="Required statutory element text")
    status: str = Field(
        ..., description="SUPPORTED, UNPROVEN, or CONTRADICTED_BY_FACT"
    )
    evidence_quote: Optional[str] = Field(
        None, description="Direct quote or fact reference supporting status"
    )


class StatutoryExceptionEvaluation(BaseModel):
    exception_name: str = Field(..., description="e.g. Exception 1 - Grave and Sudden Provocation")
    status: str = Field(..., description="EVALUATED_APPLICABLE, EVALUATED_INAPPLICABLE, or UNPROVEN")
    legal_effect: str = Field(..., description="e.g. Reduces charge from Murder (BNS 103) to Culpable Homicide (BNS 101)")


class OffenseAnalysis(BaseModel):
    act_name: str = Field(
        ..., description="Statute name, e.g., Bharatiya Nyaya Sanhita (BNS)"
    )
    section_number: str = Field(..., description="Exact section number")
    offense_description: str
    potential_punishment: str
    punishment_severity: Optional[str] = Field(None, description="CAPITAL_LIFE, SERIOUS, or MINOR")
    cognizable: Optional[bool] = Field(None, description="True if police can arrest without warrant")
    bailable: Optional[bool] = Field(None, description="True if bailable as a matter of right")
    applicability_status: str = Field(
        default="ESTABLISHED", description="ESTABLISHED, POTENTIAL_UNDER_INVESTIGATION, or EXCLUDED"
    )
    reasoning_chain: List[str] = Field(
        ..., description="Step-by-step logical derivation"
    )
    element_audits: List[ElementAudit] = Field(
        default=[], description="Audit table mapping facts against statutory elements"
    )
    statutory_exceptions: List[StatutoryExceptionEvaluation] = Field(
        default=[], description="Evaluation of section-specific statutory exceptions"
    )
    relevance_level: str = Field(
        default="DIRECT", description="DIRECT, CROSS_REFERENCE, or BACKGROUND"
    )
    provision_category: str = Field(
        default="OFFENSE", description="OFFENSE, DEFENCE_EXCEPTION, PROCEDURAL, or DEFINITIONAL"
    )
    source_verified: bool = Field(
        False, description="Passed verification check against source text"
    )


class ImmediateActionStep(BaseModel):
    step_number: int = Field(..., description="Numerical step sequence")
    title: str = Field(..., description="Action title e.g. Call Emergency Helpline 112")
    action_details: str = Field(..., description="Detailed actionable guidance for citizen")
    statutory_duty_reference: Optional[str] = Field(
        None, description="Statutory reference e.g. BNSS Section 33 (Duty to inform police)"
    )
    urgency: str = Field("HIGH", description="CRITICAL, HIGH, or MEDIUM")


class LegalAnalysisResponse(BaseModel):
    status: str = Field(..., description="SUCCESS, UNDETERMINED, or NEEDS_CLARIFICATION")
    scenario_domain: str = Field(default="POTENTIAL_CRIMINAL", description="Evaluated scenario domain")
    offense_status: str = Field(default="UNDETERMINED", description="Evaluated offense status")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reason: Optional[str] = Field(None, description="Primary legal justification or explanation for the status")
    extracted_facts: ExtractedFacts
    identified_offenses: List[OffenseAnalysis] = []
    applied_defences: List[str] = Field(
        default=[], description="General exceptions or legal defences applicable e.g. Right of Private Defence (BNS Sec 38-44)"
    )
    procedural_provisions: List[str] = Field(
        default=[], description="Applicable procedural rules e.g. BNSS Section 185, BSA Section 63"
    )
    immediate_action_steps: List[ImmediateActionStep] = Field(
        default=[], description="Step-by-step immediate legal and practical actions for citizen/witness"
    )
    citizen_duties: List[str] = Field(
        default=[], description="Statutory duties under Indian law (e.g. BNSS Section 33 obligation to report)"
    )
    clarification_questions: List[str] = []
    disclaimer: str = (
        "This platform provides legal information based on BNS/BNSS/BSS, not formal legal advice."
    )