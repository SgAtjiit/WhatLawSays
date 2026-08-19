from typing import List, Optional
from pydantic import BaseModel, Field


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
        "composite_text": (
            f"{self.act} | {self.section_number}: {self.title}\n"
            f"Content: {self.content}\n"
            f"Punishment: {self.punishment or 'N/A'}"
        ),
    }