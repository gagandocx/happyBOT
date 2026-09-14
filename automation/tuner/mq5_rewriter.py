"""Read and rewrite `input TYPE Name = value;` lines in HappyBot.mq5.

The rewriter is deliberately conservative and line-based:
  * It matches an input line by EXACT name using a word boundary, so a name
    that is a substring of another identifier is never clobbered.
  * It replaces ONLY the value literal, preserving all leading whitespace,
    alignment around `=`, and any trailing `// comment`.
  * Rewriting with the same value yields a byte-identical file.
  * int values are emitted as ints; double values keep a decimal point so the
    literal style matches existing doubles (e.g. 1.0, not 1).
  * A requested input name that is not present raises MissingInputError rather
    than silently corrupting or appending.
"""

import re

try:
    from . import params as params_mod
except ImportError:  # flat import (tools/-style: package dir on sys.path)
    import params as params_mod


class MissingInputError(Exception):
    """Raised when a requested input name is not found in the file text."""


# Group 1: everything up to and including `= ` (prefix, keeps alignment).
# Group 2: the value literal (no semicolon).
# Group 3: the semicolon and any trailing comment.
def _line_regex(name):
    return re.compile(
        r"^(\s*input\s+\S+\s+" + re.escape(name) + r"\s*=\s*)([^;]*?)(\s*;.*)$"
    )


def _format_value(name, value):
    """Format a numeric value in the correct int-vs-double literal style.

    For known params, use the declared type. For unknown names, infer from the
    Python type of value (float -> decimal literal, int -> integer literal).
    """
    param = params_mod.PARAMS.get(name)
    if param is not None:
        ptype = param.ptype
    else:
        ptype = params_mod.DOUBLE if isinstance(value, float) else params_mod.INT

    if ptype == params_mod.INT:
        return str(int(round(float(value))))

    # Double: emit with a decimal point. Use repr-ish formatting but ensure a
    # trailing '.0' when the value is integral (e.g. 1 -> "1.0").
    fval = float(value)
    if fval == int(fval):
        return "%.1f" % fval
    # Trim to a compact but exact-ish representation without scientific notation.
    text = ("%f" % fval).rstrip("0")
    if text.endswith("."):
        text += "0"
    return text


def read_values(text, names=None):
    """Return {name: value} for the requested input names found in text.

    Values are typed per params (int/float) when the name is known, else parsed
    heuristically (float if it has a dot, else int). Names not present are
    omitted from the result (use read_current_vector to seed with defaults).
    """
    if names is None:
        names = params_mod.PARAM_NAMES
    out = {}
    lines = text.splitlines()
    for name in names:
        rx = _line_regex(name)
        for line in lines:
            m = rx.match(line)
            if m:
                literal = m.group(2).strip()
                out[name] = _parse_literal(name, literal)
                break
    return out


def _parse_literal(name, literal):
    param = params_mod.PARAMS.get(name)
    try:
        if param is not None:
            if param.ptype == params_mod.INT:
                return int(round(float(literal)))
            return float(literal)
        if "." in literal or "e" in literal or "E" in literal:
            return float(literal)
        return int(literal)
    except (TypeError, ValueError):
        return literal


def read_current_vector(text):
    """Return the full tunable vector seeded from text, defaulting anything
    that is missing from the file to its param default."""
    found = read_values(text, params_mod.PARAM_NAMES)
    vector = params_mod.defaults()
    vector.update(found)
    return vector


def rewrite_text(text, updates):
    """Return new text with each named input's value literal replaced.

    updates: {input_name: new_value}. Raises MissingInputError if any name is
    absent. Preserves trailing newline presence of the original text.
    """
    had_trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if had_trailing_newline:
        # split leaves a trailing empty element for the final newline.
        pass

    remaining = set(updates.keys())
    for name, new_value in updates.items():
        rx = _line_regex(name)
        replaced = False
        for i, line in enumerate(lines):
            m = rx.match(line)
            if m:
                literal = _format_value(name, new_value)
                lines[i] = m.group(1) + literal + m.group(3)
                replaced = True
                remaining.discard(name)
                break
        if not replaced:
            raise MissingInputError(
                "input name not found in file: %s" % name
            )

    return "\n".join(lines)


def read_file(path, names=None):
    """Read values for names from the file at path."""
    with open(path, "r") as fh:
        text = fh.read()
    return read_values(text, names)


def read_file_vector(path):
    """Read the full tunable vector (defaulted) from the file at path."""
    with open(path, "r") as fh:
        text = fh.read()
    return read_current_vector(text)


def rewrite_file(path, updates):
    """Rewrite the named inputs in the file at path in place.

    Raises MissingInputError before writing anything if a name is absent, so a
    failed rewrite never corrupts the file.
    """
    with open(path, "r") as fh:
        text = fh.read()
    new_text = rewrite_text(text, updates)  # may raise before we write
    if new_text != text:
        with open(path, "w") as fh:
            fh.write(new_text)
    return new_text
