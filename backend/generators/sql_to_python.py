"""
generators/sql_to_python.py — SQL-to-API Python function generator
======================================================================
Given a validated, read-only SELECT statement and DB connection type, builds
the *entire* func.py source (ASGI wrapper included) for a SQL-to-API
function. Pure code generation — no subprocess, no kubectl, no filesystem
I/O. The caller (services/sql_pipeline.py) is responsible for writing the
returned string to disk.

The SQL-to-API flow never goes through the browser's CodeMirror editor or
frontend/js/templates.js's wrapCode(), so the ASGI wrapper is duplicated here
in Python — keep it behaviorally in sync with wrapCode()'s python branch
(same header/status-tuple contract).
"""

import json

DB_DRIVER_CONFIG = {
    "postgres": {"drivername": "postgresql+pg8000", "dependency": "pg8000==1.31.2", "default_port": 5432},
    "mysql": {"drivername": "mysql+pymysql", "dependency": "pymysql==1.1.1", "default_port": 3306},
}
SQLALCHEMY_DEPENDENCY = "sqlalchemy==2.0.35"


def get_dependencies(db_type: str) -> list[str]:
    """Library specs to inject via the existing dependencies.apply_dependencies() —
    same mechanism the "Add Libraries" UI uses for the code-editor flow."""
    cfg = DB_DRIVER_CONFIG[db_type]
    return [SQLALCHEMY_DEPENDENCY, cfg["dependency"]]


def generate_function_code(db_type: str, validated_sql: str) -> str:
    """
    Returns the full func.py source. `validated_sql` MUST already have passed
    services.sql_validator.validate_select_only() — this function does not
    re-validate, it only generates code around the given text.
    """
    if db_type not in DB_DRIVER_CONFIG:
        raise ValueError(f"Unsupported db_type '{db_type}'. Choose from: {list(DB_DRIVER_CONFIG)}")

    drivername = DB_DRIVER_CONFIG[db_type]["drivername"]
    # json.dumps() produces a valid Python string literal — safe regardless of
    # quotes/backslashes/newlines in the query, no manual-escaping bug surface.
    sql_literal = json.dumps(validated_sql)
    drivername_literal = json.dumps(drivername)

    return f'''import json
import inspect
import hmac
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# create_engine() is lazy — no connection attempt at import/cold-start time,
# so a temporarily-unreachable DB doesn't break cold start. The error surfaces
# per-request from inside handler() instead, same as everywhere else on this
# platform.
_db_url = URL.create(
    drivername={drivername_literal},
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    database=os.environ["DB_NAME"],
)
_engine = create_engine(_db_url, pool_pre_ping=True, pool_recycle=280)
_query = text({sql_literal})


def handler(req_data, headers):
    provided_key = headers.get("x-api-key", "")
    expected_key = os.environ.get("API_KEY", "")
    if not expected_key or not hmac.compare_digest(provided_key, expected_key):
        return {{"error": "Unauthorized"}}, 401

    try:
        with _engine.connect() as conn:
            rows = [dict(row._mapping) for row in conn.execute(_query)]
    except Exception as e:
        return {{"error": f"Query failed: {{e}}"}}, 500

    return {{"rows": rows, "count": len(rows)}}, 200


# --- ASGI wrapper — keep in sync with wrapCode()'s python branch in
#     frontend/js/templates.js ---
def new(): return Function()

_handler_wants_headers = len(inspect.signature(handler).parameters) >= 2

class Function:
    def __init__(self): pass
    async def handle(self, scope, receive, send):
        headers = {{k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers', [])}}
        body_bytes = b""
        while True:
            message = await receive()
            if message['type'] == 'http.request':
                body_bytes += message.get('body', b'')
                if not message.get('more_body', False): break
        try: req_data = json.loads(body_bytes)
        except: req_data = {{}}

        try:
            response_data = handler(req_data, headers) if _handler_wants_headers else handler(req_data)
            status_code = 200
            if isinstance(response_data, tuple) and len(response_data) == 2:
                response_data, status_code = response_data
        except Exception as e:
            response_data = {{"error": str(e)}}
            status_code = 500

        content_type = b'application/json'
        if isinstance(response_data, str):
            if response_data.strip().lower().startswith(('<!doctype html', '<html')):
                content_type = b'text/html; charset=utf-8'
            else:
                content_type = b'text/plain; charset=utf-8'
            body_payload = response_data.encode('utf-8')
        else:
            body_payload = json.dumps(response_data).encode('utf-8')

        await send({{
            'type': 'http.response.start',
            'status': status_code,
            'headers': [[b'content-type', content_type]],
        }})
        await send({{
            'type': 'http.response.body',
            'body': body_payload,
        }})
'''
