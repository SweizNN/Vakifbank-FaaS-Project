"""routers/proxy.py — bypass CORS so the browser Test modal can call deployed functions."""

import json
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException

from models import ProxyRequest

router = APIRouter(tags=["proxy"])


@router.post("/proxy", summary="Proxy requests to bypass CORS for testing functions")
async def proxy_request(req: ProxyRequest):
    data = json.dumps(req.body).encode("utf-8")
    headers = req.headers
    headers["Content-Type"] = "application/json"

    request = urllib.request.Request(req.url, data=data, headers=headers, method=req.method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.getcode()
            body_bytes = response.read()
    except urllib.error.HTTPError as e:
        status = e.code
        body_bytes = e.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        resp_json = json.loads(body_bytes)
        return {"status": status, "body": resp_json}
    except json.JSONDecodeError:
        return {"status": status, "body": body_bytes.decode("utf-8")}
