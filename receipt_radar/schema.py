"""The Receipt: the form Claude must fill in for every photo (Phase 1).

Passing this class as `output_schema` makes Claude answer in exactly this
shape: Agno sends it as Claude's structured-output format and turns the reply
back into a Receipt object.

Schema rules that bite beginners:
  * No numeric or length limits (no Field(gt=0), no max_length). Structured
    outputs reject them, so "amount above 0" is checked in gate.py instead.
  * Fixed choices go in a Literal, which becomes a JSON enum.
"""
from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["Food", "Transport", "Bills", "Load", "Shopping", "Health", "Other"]
UnsureField = Literal["date", "vendor", "amount", "category"]


class Receipt(BaseModel):
    # TODO 1: add the six fields of the form. Give each one a Field(description=...),
    # because Claude reads the descriptions too.
    #
    #   field          type               rule
    #   date           Date               the receipt date as printed, YYYY-MM-DD
    #   vendor         str                the store or biller name
    #   amount_php     float              the grand total, never a subtotal; no peso sign
    #   category       Category           one of the seven categories above
    #   sure           bool               False if any field was guessed
    #   unsure_about   list[UnsureField]  which fields were guessed
    #
    # The first one, to show the pattern:
    #   date: Date = Field(description="The receipt date as printed, YYYY-MM-DD.")
    pass
