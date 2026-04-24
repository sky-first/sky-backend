"""W8 — SQL AST guard for LLM tool-use.

Master plan §7.3.

The LLM may emit SQL (either as a direct "tool call" or echoed inside an
answer). Before we EVER execute that SQL, it passes through this guard:

  1. AST parse via ``sqlparse`` (tokenising + basic typing).
  2. Must be a single statement (no semicolons outside strings).
  3. Must be a SELECT — every DML / DDL keyword rejected.
  4. Every referenced table must appear in ``authorized_tables``.
  5. Must carry ``LIMIT <=`` ``max_rows`` (auto-appended when missing).
  6. Comments rejected (``--`` or ``/* */``) — common obfuscation.

Raises ``SQLGuardViolation`` (maps to ``CHAT_TOOL_DENIED`` or
``CHAT_MALFORMED_INPUT`` depending on severity).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Set

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Statement, Token
from sqlparse.tokens import DDL, DML, Keyword, Punctuation


# ---------------------------------------------------------------------------
#  Errors
# ---------------------------------------------------------------------------


class SQLGuardViolation(Exception):
    code: str = "CHAT_TOOL_DENIED"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class SQLMalformed(SQLGuardViolation):
    code = "CHAT_MALFORMED_INPUT"


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

# Hard deny-list of DML / DDL / TCL keywords. If any appears at the top of a
# statement, reject. This set is deliberately broad — "if in doubt, reject".
_FORBIDDEN_KEYWORDS: Set[str] = {
    # DML (except SELECT)
    "INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE", "UPSERT",
    # DDL
    "CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "COMMENT",
    # TCL
    "COMMIT", "ROLLBACK", "SAVEPOINT", "BEGIN", "START",
    # DCL
    "GRANT", "REVOKE", "DENY",
    # Dangerous pg / mysql extensions
    "COPY", "LOAD", "EXECUTE", "CALL", "DO", "VACUUM", "ANALYZE",
    "EXPLAIN", "PREPARE", "DEALLOCATE", "LISTEN", "NOTIFY", "SET",
    "RESET", "SHOW",
}

DEFAULT_MAX_ROWS = 1_000


# ---------------------------------------------------------------------------
#  Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardedSQL:
    sql: str
    tables_referenced: List[str]
    rewrote_limit: bool


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------


def guard_sql(
    sql: str,
    *,
    authorized_tables: Iterable[str] = (),
    max_rows: int = DEFAULT_MAX_ROWS,
) -> GuardedSQL:
    """Validate + rewrite a SELECT statement. Raise on violation.

    The caller (tool executor) passes the returned ``sql`` — not the
    original — to the DB driver. We prefer rewriting over rejecting when
    the change is mechanical (adding a LIMIT) so the LLM doesn't need to
    round-trip a retry for a benign omission.
    """
    if not sql or not sql.strip():
        raise SQLMalformed("Empty SQL.")

    # Reject SQL comments — they're a common obfuscation vector.
    if "--" in sql or "/*" in sql:
        raise SQLGuardViolation("SQL comments are not allowed.")

    # Parse. sqlparse tolerates multi-statement; we explicitly ban it.
    statements = [s for s in sqlparse.parse(sql) if s.tokens and not _is_only_whitespace(s)]
    if not statements:
        raise SQLMalformed("Unparseable SQL.")
    if len(statements) > 1:
        raise SQLGuardViolation("Multiple statements are not allowed.")

    stmt: Statement = statements[0]

    # Must be a SELECT. ``get_type`` returns "SELECT" / "INSERT" / ...
    stmt_type = (stmt.get_type() or "").upper()
    if stmt_type != "SELECT":
        raise SQLGuardViolation(f"Only SELECT is allowed (got {stmt_type or 'UNKNOWN'}).")

    # Scan every keyword-token for forbidden keywords (including nested
    # subqueries — sqlparse returns them as tokens at various depths).
    for token in stmt.flatten():
        if token.ttype in (DML, DDL, Keyword.DML, Keyword.DDL):
            word = token.value.upper()
            if word in _FORBIDDEN_KEYWORDS:
                raise SQLGuardViolation(
                    f"Keyword `{word}` is not allowed in tool-use SQL."
                )
        # Keyword-class catchall (sqlparse uses Keyword for SET / BEGIN / etc.)
        if token.ttype is Keyword:
            word = token.value.upper()
            if word in _FORBIDDEN_KEYWORDS:
                raise SQLGuardViolation(
                    f"Keyword `{word}` is not allowed in tool-use SQL."
                )
        # Explicit semicolon inside the statement body — sqlparse already
        # splits on top-level ones; an inner semi is suspicious.
        if token.ttype is Punctuation and token.value == ";":
            raise SQLGuardViolation("Embedded semicolons are not allowed.")

    # Extract referenced tables — FROM + JOIN identifiers.
    tables = _extract_tables(stmt)
    allowed = {t.lower() for t in authorized_tables}
    for table in tables:
        if table.lower() not in allowed:
            raise SQLGuardViolation(
                f"Table `{table}` is not in the authorized list for this call."
            )

    # Append or enforce LIMIT.
    rewritten, rewrote_limit = _enforce_limit(stmt.normalized, max_rows)

    return GuardedSQL(sql=rewritten, tables_referenced=tables, rewrote_limit=rewrote_limit)


# ---------------------------------------------------------------------------
#  Internals
# ---------------------------------------------------------------------------


def _is_only_whitespace(stmt: Statement) -> bool:
    return all(t.is_whitespace for t in stmt.tokens)


def _extract_tables(stmt: Statement) -> List[str]:
    """Walk the parse tree for tokens that follow FROM / JOIN and collect
    the identifier names. This is not a full parser — subqueries, CTEs,
    schema-qualified names and aliases all cascade through. We strip
    aliases and ``schema.table`` prefixes so the caller's whitelist can
    use either form.
    """
    tables: List[str] = []
    tokens = list(stmt.tokens)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        kw = (tok.value or "").upper()
        if tok.ttype is Keyword and kw in {"FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "CROSS JOIN"}:
            # Find next non-whitespace / non-punctuation token — that's
            # the table reference.
            j = i + 1
            while j < len(tokens) and (tokens[j].is_whitespace or tokens[j].ttype is Punctuation):
                j += 1
            if j < len(tokens):
                table_tok = tokens[j]
                for name in _table_names_from(table_tok):
                    tables.append(name)
        # Recurse into grouped tokens (subqueries, parenthesised lists).
        if hasattr(tok, "tokens"):
            sub_tables = _extract_tables(tok)  # type: ignore[arg-type]
            tables.extend(sub_tables)
        i += 1

    # De-duplicate while preserving order.
    seen: Set[str] = set()
    out: List[str] = []
    for t in tables:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _table_names_from(token: Token) -> List[str]:
    """Normalise an Identifier / IdentifierList into bare table names."""
    if isinstance(token, IdentifierList):
        return [_bare_name(i) for i in token.get_identifiers()]
    if isinstance(token, Identifier):
        return [_bare_name(token)]
    # Plain name token
    val = (token.value or "").strip("`\"[]")
    if "." in val:
        val = val.split(".")[-1]
    return [val] if val else []


def _bare_name(ident: Identifier) -> str:
    real = ident.get_real_name() or ident.get_name() or ident.value
    real = real.strip("`\"[]")
    if "." in real:
        real = real.split(".")[-1]
    return real


def _enforce_limit(sql: str, max_rows: int) -> tuple[str, bool]:
    """Check for an existing ``LIMIT n`` and clamp it; add one when
    missing. Handles upper/lower case but not complex expressions like
    ``LIMIT x OFFSET y`` rewrites — in that case we leave the limit as-is
    if it's a number we can parse and clamp, otherwise we append a new
    ``LIMIT max_rows`` which most SQL dialects treat as a no-op if a
    later one is present."""
    import re

    normalised = sql.rstrip(";").rstrip()
    m = re.search(r"(?is)\blimit\s+(\d+)\b", normalised)
    if m:
        current = int(m.group(1))
        if current <= max_rows:
            return normalised, False
        # Clamp down.
        new_sql = (
            normalised[: m.start(1)]
            + str(max_rows)
            + normalised[m.end(1):]
        )
        return new_sql, True

    return f"{normalised} LIMIT {max_rows}", True
