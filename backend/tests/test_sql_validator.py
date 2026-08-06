import pytest

from services.sql_validator import SqlValidationError, validate_select_only


def test_accepts_simple_select():
    assert validate_select_only("SELECT id, name FROM users") == "SELECT id, name FROM users"


def test_accepts_select_with_literal_containing_forbidden_word():
    # 'please delete this' is a string literal, not a DELETE statement
    validate_select_only("SELECT * FROM users WHERE note = 'please delete this'")


def test_accepts_cte():
    validate_select_only("WITH x AS (SELECT * FROM users) SELECT * FROM x")


def test_rejects_empty_query():
    with pytest.raises(SqlValidationError):
        validate_select_only("")
    with pytest.raises(SqlValidationError):
        validate_select_only("   ")


@pytest.mark.parametrize("sql", [
    "INSERT INTO users (name) VALUES ('x')",
    "UPDATE users SET active = false",
    "DELETE FROM users",
    "DROP TABLE users",
    "ALTER TABLE users ADD COLUMN x int",
    "GRANT ALL ON users TO public",
    "TRUNCATE TABLE users",
])
def test_rejects_non_select_statements(sql):
    with pytest.raises(SqlValidationError):
        validate_select_only(sql)


def test_rejects_stacked_statements():
    with pytest.raises(SqlValidationError):
        validate_select_only("SELECT * FROM users; DROP TABLE users;")


def test_semicolon_inside_string_literal_does_not_trigger_stacked_statement_rejection():
    validate_select_only("SELECT * FROM t WHERE x = 'a;b'")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM users INTO OUTFILE '/tmp/x.csv'",
    "SELECT * INTO new_table FROM users",
])
def test_rejects_select_into_disguised_write(sql):
    with pytest.raises(SqlValidationError):
        validate_select_only(sql)


def test_rejects_data_modifying_cte():
    with pytest.raises(SqlValidationError):
        validate_select_only("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")
