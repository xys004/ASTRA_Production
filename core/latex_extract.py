"""Heuristic LaTeX -> plain-text extractor for research drafts.

ASTRA ingests uploaded documents as free-text "intuition". A raw ``.tex`` file
dumped verbatim drowns the physics in markup (preamble, layout commands,
comments). This module strips the scaffolding while *preserving the science*:
section titles, prose, and inline/display math are kept, because for a physics
draft the equations are the content.

This is deliberately a heuristic cleaner, not a full LaTeX parser (LaTeX is
Turing-complete and not regex-parseable). It targets the common structure of
article-class manuscripts and degrades gracefully on anything else.
"""

from __future__ import annotations

import re

# Math environments whose bodies are preserved verbatim (wrapped in $$…$$).
_MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "math", "displaymath",
}

# Inline text-formatting commands: unwrap to their argument content.
_TEXT_CMDS = (
    "textbf", "textit", "emph", "texttt", "textsc", "textrm", "underline",
    "mathrm", "mathbf", "mathit", "text",
)

# Metadata / layout commands to remove (with optional [..] and {..} arguments).
_DROP_CMDS = (
    "documentclass", "usepackage", "author", "date", "maketitle", "newpage",
    "clearpage", "pagebreak", "centering", "noindent", "label", "ref", "eqref",
    "cite", "citep", "citet", "bibliographystyle", "bibliography",
    "tableofcontents", "hrule", "vspace", "hspace", "includegraphics",
    "caption", "footnote", "thanks", "affiliation", "email",
)


def extract_text_from_latex(source: str) -> str:
    """Return readable prose + math extracted from a LaTeX ``source`` string."""
    text = source.replace("\r\n", "\n").replace("\r", "\n")

    # 1) Strip comments (unescaped '%' to end of line).
    text = re.sub(r"(?<!\\)%.*", "", text)

    # 2) Capture the title from the (usually preamble) \title{...} before it is
    #    trimmed away with the rest of the preamble.
    title_match = re.search(r"\\title\{([^{}]*)\}", text)
    title_header = f"# {title_match.group(1).strip()}\n\n" if title_match else ""

    # 3) Keep the document body when delimiters exist; else drop an obvious
    #    preamble up to the first sectioning command.
    body = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.DOTALL)
    if body:
        text = body.group(1)
    elif "\\section" in text:
        text = re.sub(r"^.*?(?=\\(?:sub)*section\b)", "", text, count=1, flags=re.DOTALL)

    # 4) Sectioning -> readable headers (title already captured above).
    text = re.sub(r"\\title\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:sub)*section\*?\{([^{}]*)\}", lambda m: f"\n\n## {m.group(1)}\n", text)
    text = re.sub(r"\\(?:sub)*paragraph\*?\{([^{}]*)\}", lambda m: f"\n\n{m.group(1)}: ", text)

    # 4) Unwrap inline text-formatting commands to their content.
    for cmd in _TEXT_CMDS:
        text = re.sub(r"\\%s\{([^{}]*)\}" % cmd, r"\1", text)

    # 5) Remove metadata / layout commands and their arguments.
    drop = "|".join(_DROP_CMDS)
    text = re.sub(
        r"\\(?:%s)\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?" % drop, "", text
    )

    # 6) Unwrap remaining environments, keeping inner content. Math environments
    #    are preserved verbatim as $$…$$. Repeat until stable to handle nesting.
    def _strip_env(match: "re.Match[str]") -> str:
        env, inner = match.group(1), match.group(2)
        if env in _MATH_ENVS:
            return f"\n$$ {inner.strip()} $$\n"
        return inner

    prev = None
    while prev != text:
        prev = text
        text = re.sub(
            r"\\begin\{([A-Za-z*]+)\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}",
            _strip_env,
            text,
            flags=re.DOTALL,
        )

    # 7) List items and line breaks -> plain markers. Leave real math commands
    #    (\alpha, \frac, $…$) intact — they carry the physics.
    text = re.sub(r"\\item\b", "\n- ", text)
    text = re.sub(r"\\\\(?:\[[^\]]*\])?", "\n", text)
    text = re.sub(r"\\[,;:! ]", " ", text)

    # 8) Whitespace tidy-up.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return (title_header + text.strip()).strip()
