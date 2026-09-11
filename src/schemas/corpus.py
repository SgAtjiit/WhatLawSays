import re
from typing import List, Optional
from pydantic import BaseModel, Field

# A provision that prescribes a penalty is one that can create an offence.
# Detected from the section's own verbatim text rather than asserted, so the
# flag is reproducible and auditable against the source.
_PENALTY_LANGUAGE = re.compile(
    r"shall be punish|punishable with|shall also be liable to fine|with imprisonment",
    re.I,
)


class LegalSectionDoc(BaseModel):
  act: str = Field(
      ..., description="e.g., Bharatiya Nyaya Sanhita, 2023 (BNS)"
  )
  chapter: str = Field(..., description="e.g., Chapter VI - Offenses Against the Human Body")
  section_number: str = Field(..., description="e.g., Section 103")
  title: str = Field(..., description="e.g., Punishment for Murder")
  content: str = Field(..., description="Full statutory text of the section")
  elements: List[str] = Field(
      default=[], description="Core legal ingredients required to prove offense"
  )
  punishment: Optional[str] = Field(
      None, description="Exact statutory punishment text"
  )
  bailable: Optional[bool] = None
  cognizable: Optional[bool] = None
  source_url: Optional[str] = None

  @property
  def prescribes_penalty(self) -> bool:
    """Whether this section prescribes a penalty, and so can create an offence.

    Sections like POSH s.8 (Grants and audit) or s.4 (Constitution of the
    Internal Complaints Committee) prescribe none, and must never be reported as
    offences. The BNS's own definitions and general exceptions are excluded by
    the same test.
    """
    if self.punishment:
      return True
    return bool(_PENALTY_LANGUAGE.search(self.content or ""))

  def to_search_payload(self) -> dict:
    """Combines metadata and structural fields for Qdrant payload storage."""
    return {
        "act": self.act,
        "chapter": self.chapter,
        "section_number": self.section_number,
        "title": self.title,
        "content": self.content,
        "elements": self.elements,
        "punishment": self.punishment,
        "bailable": self.bailable,
        "cognizable": self.cognizable,
        "source_url": self.source_url,
        "prescribes_penalty": self.prescribes_penalty,
        "composite_text": (
            f"{self.act} | {self.section_number}: {self.title}\n"
            f"Content: {self.content}\n"
            f"Punishment: {self.punishment or 'N/A'}"
        ),
    }