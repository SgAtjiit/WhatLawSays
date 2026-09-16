"""Pattern helpers shared by clause classification and red-flag detection."""

import re


def whitespace_tolerant(pattern: str) -> str:
    """Let every literal space in `pattern` match any run of whitespace.

    Contracts arrive line-wrapped, and the wrap lands mid-phrase as often as not:
    the extracted text of a perfectly ordinary IP clause reads
    "... employment, whether\\nor not such creation ...". A pattern written with
    an ordinary space then fails on precisely the clause it was written for, and
    fails silently, which is the worst way for a red-flag rule to fail.

    Spaces inside a character class are left alone, so `[ \\t]` keeps meaning what
    it says.
    """
    out, in_class, escaped = [], False, False
    for char in pattern:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        out.append(r"\s+" if char == " " and not in_class else char)
    return "".join(out)


def compile_loose(pattern: str, flags: int = re.I | re.S) -> re.Pattern:
    """Compile a pattern that tolerates line wrapping."""
    return re.compile(whitespace_tolerant(pattern), flags)
