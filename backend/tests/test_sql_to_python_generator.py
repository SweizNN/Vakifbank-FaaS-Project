import ast

import pytest

from generators.sql_to_python import DB_DRIVER_CONFIG, generate_function_code, get_dependencies


@pytest.mark.parametrize("db_type", list(DB_DRIVER_CONFIG))
def test_generated_code_is_valid_python(db_type):
    code = generate_function_code(db_type, "SELECT id, name FROM users")
    ast.parse(code)  # raises SyntaxError if invalid


def test_generated_code_checks_api_key_with_constant_time_compare():
    code = generate_function_code("postgres", "SELECT 1")
    assert "hmac.compare_digest" in code


def test_generated_code_embeds_query_as_safe_string_literal():
    tricky_sql = 'SELECT * FROM t WHERE name = "quo\'te" -- and a\nbackslash \\'
    code = generate_function_code("postgres", tricky_sql)
    ast.parse(code)  # would fail to parse if the query text broke out of its literal


def test_get_dependencies_includes_sqlalchemy_and_driver():
    deps = get_dependencies("postgres")
    assert any(d.startswith("sqlalchemy") for d in deps)
    assert any(d.startswith("pg8000") for d in deps)

    deps = get_dependencies("mysql")
    assert any(d.startswith("pymysql") for d in deps)


def test_unsupported_db_type_raises():
    with pytest.raises(ValueError):
        generate_function_code("oracle", "SELECT 1")
