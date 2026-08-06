"""
services/sql_validator.py — enforce single-statement, read-only SELECT
=========================================================================
The SQL-to-API feature deploys a fixed query, chosen at deploy time by
whoever fills out the form, as a public (API-key-gated) HTTP endpoint. This
module is the policy gate before anything gets deployed: exactly one SELECT
statement, nothing else.

`sqlparse` is a lenient tokenizer, not a syntax validator — it won't catch a
malformed SELECT. That's fine: a genuine syntax error surfaces naturally when
SQLAlchemy executes the query against the live DB at request time, and the
generated handler already returns that as a JSON error (see
generators/sql_to_python.py). This module's only job is the policy check.
"""

import sqlparse
from sqlparse.tokens import Keyword

# INSERT/UPDATE/DELETE/DDL/etc are the obvious ones. INTO is included
# specifically because `SELECT ... INTO new_table` (SQL Server / Postgres) and
# `SELECT ... INTO OUTFILE` (MySQL) are write operations that sqlparse's
# Statement.get_type() still classifies as "SELECT" — the outer-statement
# classification alone isn't a strong enough signal, so every token gets
# checked, not just the first one.
FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "GRANT", "REVOKE", "MERGE", "REPLACE", "CALL", "EXEC", "EXECUTE",
    "INTO", "ATTACH", "DETACH", "VACUUM", "PRAGMA", "COPY", "LOCK",
}


class SqlValidationError(ValueError):
    pass


def validate_select_only(sql: str) -> str:
    """
    Validates that `sql` is exactly one read-only SELECT statement.
    Returns the stripped statement text on success; raises
    SqlValidationError with a human-readable reason otherwise.
    """
    if not sql or not sql.strip():
        raise SqlValidationError("SQL query cannot be empty.")

    statements = [s for s in sqlparse.parse(sql) if s.token_first(skip_cm=True) is not None]
    if not statements:
        raise SqlValidationError("SQL query cannot be empty.")
    if len(statements) > 1:
        raise SqlValidationError(
            "Only a single SQL statement is allowed (multiple/stacked statements detected)."
        )

    stmt = statements[0]
    if stmt.get_type() != "SELECT":
        raise SqlValidationError(
            f"Only SELECT statements are allowed (detected: {stmt.get_type()})."
        )

    # String literals tokenize as Token.Literal.String, not Keyword — so a
    # column value like 'please delete this' is never falsely flagged here.
    for token in stmt.flatten():
        if token.ttype in Keyword and token.value.upper() in FORBIDDEN_KEYWORDS:
            raise SqlValidationError(f"Disallowed keyword detected: '{token.value}'.")

    return str(stmt).strip()
