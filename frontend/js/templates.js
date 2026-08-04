// ═══════════════════════════════════════════════════════════════
// CODE TEMPLATES
// ═══════════════════════════════════════════════════════════════
const TEMPLATES = {
  python: `def handler(req_data):
    name = req_data.get("name", "World")
    return {
        "message": f"Hello, {name}! 👋",
        "platform": "VakıfBank FaaS",
        "language": "Python"
    }`,
  node: `const handler = (body) => {
  const name = body?.name || 'World';
  return {
    message: \`Hello, \${name}! 👋\`,
    platform: 'VakıfBank FaaS',
    language: 'Node.js'
  };
};`,
  go: `package function

import (
	"encoding/json"
	"net/http"
)

type MyFunction struct{}

func New() *MyFunction {
	return &MyFunction{}
}

func (f *MyFunction) Handle(res http.ResponseWriter, req *http.Request) {
	var body map[string]interface{}
	json.NewDecoder(req.Body).Decode(&body)
	if body == nil {
		body = make(map[string]interface{})
	}

	name, _ := body["name"].(string)
	if name == "" {
		name = "World"
	}

	res.Header().Set("Content-Type", "application/json")
	json.NewEncoder(res).Encode(map[string]interface{}{
		"message":  "Hello, " + name + "! 👋",
		"platform": "VakıfBank FaaS",
		"language": "Go",
	})
}`,
  typescript: `const handler = (body: any): any => {
  const name = body?.name || 'World';
  return {
    message: \`Hello, \${name}! 👋\`,
    platform: 'VakıfBank FaaS',
    language: 'TypeScript'
  };
};`,
  quarkus: `package functions;

import io.quarkus.funqy.Funq;

public class Function {

    @Funq
    public Output function(Input input) {
        String name = (input != null && input.getMessage() != null)
            ? input.getMessage() : "World";

        Output out = new Output();
        out.setMessage("Hello, " + name + "! 👋 from VakıfBank FaaS");
        return out;
    }

}`,
  rust: `pub fn handler(body: serde_json::Value) -> serde_json::Value {
    let name = body.get("name")
                   .and_then(|v| v.as_str())
                   .unwrap_or("World");

    serde_json::json!({
        "message": format!("Hello, {}! 👋", name),
        "platform": "VakıfBank FaaS",
        "language": "Rust"
    })
}`
};

function wrapCode(lang, userCode) {
  if (lang === 'python') {
    const indented = userCode.split('\n').map(l => l ? '    ' + l : '').join('\n');
    return `import json
import uuid
import platform
from datetime import datetime

# --- USER CODE START ---
${userCode}
# --- USER CODE END ---

def new(): return Function()

class Function:
    def __init__(self): pass
    async def handle(self, scope, receive, send):
        body_bytes = b""
        while True:
            message = await receive()
            if message['type'] == 'http.request':
                body_bytes += message.get('body', b'')
                if not message.get('more_body', False): break
        try: req_data = json.loads(body_bytes)
        except: req_data = {}

        try:
            response_data = handler(req_data)
            status_code = 200
        except Exception as e:
            response_data = {"error": str(e)}
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

        await send({
            'type': 'http.response.start',
            'status': status_code,
            'headers': [[b'content-type', content_type]],
        })
        await send({
            'type': 'http.response.body',
            'body': body_payload,
        })
`;
  }

  if (lang === 'node') {
    return `
// --- USER CODE START ---
${userCode}
// --- USER CODE END ---

const handle = async (context, body) => {
  try {
    const responseBody = handler(body);
    let contentType = 'application/json';
    if (typeof responseBody === 'string') {
      const trimmed = responseBody.trim().toLowerCase();
      if (trimmed.startsWith('<!doctype html') || trimmed.startsWith('<html')) {
        contentType = 'text/html; charset=utf-8';
      } else {
        contentType = 'text/plain; charset=utf-8';
      }
    }
    return { body: responseBody, headers: { 'content-type': contentType } };
  } catch(e) {
    return { body: {error: e.message}, headers: { 'content-type': 'application/json' }, statusCode: 500 };
  }
}
module.exports = { handle };
`;
  }

  if (lang === 'go') {
    // Go: user edits the full function.go file directly.
    return userCode;
  }

  if (lang === 'typescript') {
    return `
// --- USER CODE START ---
${userCode}
// --- USER CODE END ---

export const handle = async (context: any, body: any) => {
  try {
    const responseBody = handler(body);
    return { body: responseBody, headers: { 'content-type': 'application/json' } };
  } catch(e: any) {
    return { body: {error: e.message}, headers: { 'content-type': 'application/json' }, statusCode: 500 };
  }
}
`;
  }

  if (lang === 'quarkus') {
    // Quarkus: user edits the full Function.java file directly.
    return userCode;
  }

  if (lang === 'rust') {
    return `use serde_json::Value;

// --- USER CODE START ---
${userCode}
// --- USER CODE END ---

pub async fn handle(req: actix_web::web::Json<Value>) -> impl actix_web::Responder {
    let response = handler(req.into_inner());
    actix_web::web::Json(response)
}
`;
  }

  return userCode; // Fallback
}

const LANG_META = {
  python: { label: 'python · func.py', mode: 'python' },
  node: { label: 'javascript · index.js', mode: 'javascript' },
  go: { label: 'go · function.go', mode: 'text/x-go' },
  typescript: { label: 'typescript · index.ts', mode: 'javascript' },
  quarkus: { label: 'java · Function.java', mode: null },
  rust: { label: 'rust · src/main.rs', mode: null },
};

const TEMPLATE_MARKERS = {
  python: [ { from: 0, to: 0 } ],
  node: [ { from: 0, to: 0 }, { from: 7, to: 7 } ],
  go: [ { from: 0, to: 19 }, { from: 25, to: 31 } ],
  typescript: [ { from: 0, to: 0 }, { from: 7, to: 7 } ],
  quarkus: [ { from: 0, to: 7 }, { from: 11, to: 16 } ],
  rust: [ { from: 0, to: 0 }, { from: 9, to: 9 } ]
};

// Locks the boilerplate lines (function signature / closing brace) for the
// given language so only the handler body stays editable. Must be re-run
// after any setValue() call — CodeMirror drops all marks on setValue.
// `cm` defaults to the main create-function editor; the Edit modal passes
// its own CodeMirror instance so the same locking applies there too.
function applyReadOnlyMarkers(lang, cm = editor) {
  cm.getAllMarks().forEach(m => m.clear());
  const markers = TEMPLATE_MARKERS[lang];
  if (markers) {
    markers.forEach(range => {
      cm.markText(
        { line: range.from, ch: 0 },
        { line: range.to, ch: 9999 },
        { readOnly: true, className: 'read-only-code', atomic: false }
      );
    });
  }
}
