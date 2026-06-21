from js import fetch, Response, Headers, URL, Object
from pyodide.ffi import to_js
import json

BINDINGS = {
    "sweep-video": "SWEEP_VIDEO",
    "observation-thumbnails": "OBSERVATION_THUMBNAILS",
    "tenant-tiles": "TENANT_TILES",
}
CONTENT_TYPE = {
    "sweep-video": "video/mp4",
    "observation-thumbnails": "image/jpeg",
    "tenant-tiles": "application/octet-stream",
}

def _json_opts(method, headers, body):
    return to_js({"method": method, "headers": headers, "body": body},
                 dict_converter=Object.fromEntries)

def _valid_path(path):
    # Canonicalize what the broker treats as an R2 key BEFORE authz/fetch, so the
    # SQL split_part view of the path in app_authorize_object cannot diverge from
    # the actual key handed to binding.get(). R2 keys are flat (no real traversal),
    # but un-canonicalized paths could otherwise authorize one key and fetch another.
    # Reject: empty, leading "/", any ".." segment, "//" (empty segments),
    # backslashes, and control chars / NUL. Returns True only for a clean key.
    if not path or path[0] == "/":
        return False
    if ".." in path.split("/"):
        return False
    if "//" in path or "\\" in path:
        return False
    for ch in path:
        if ord(ch) < 0x20 or ord(ch) == 0x7f:
            return False
    return True

async def _authorized(env, bearer, bucket, path):
    url = f"{env.SUPABASE_URL}/rest/v1/rpc/app_authorize_object"
    headers = {"apikey": env.SUPABASE_ANON_KEY, "Authorization": bearer,
               "Content-Type": "application/json"}
    body = json.dumps({"p_bucket": bucket, "p_path": path})
    resp = await fetch(url, _json_opts("POST", headers, body))
    if not resp.ok:
        return False
    # Contract: app_authorize_object RETURNS boolean. PostgREST serializes a scalar
    # RPC result as bare JSON, so the response body is exactly `true` or `false`.
    # Fail closed: allow ONLY when the parsed JSON is the boolean `true` itself.
    # Any other shape (JSON `[true]`, "true" string, 1, null), whitespace quirks,
    # or a parse error must DENY rather than risk silently flipping allow/deny.
    text = await resp.text()
    try:
        return json.loads(text) is True
    except (ValueError, TypeError):
        return False

async def on_fetch(request, env):
    u = URL.new(request.url)
    if u.pathname != "/api/r2/object":
        return Response.new("Not found", status=404)

    bucket = u.searchParams.get("bucket")
    path = u.searchParams.get("path")
    if bucket not in BINDINGS or not path:
        return Response.new("Bad request", status=400)
    if not _valid_path(path):
        # Reject un-canonicalized paths before authz/fetch (see _valid_path).
        return Response.new("Bad request", status=400)

    bearer = request.headers.get("Authorization")
    if not bearer:
        return Response.new("Unauthorized", status=401)

    if not await _authorized(env, bearer, bucket, path):
        return Response.new("Forbidden", status=403)

    binding = getattr(env, BINDINGS[bucket])
    rng = request.headers.get("Range")
    if rng and rng.startswith("bytes="):
        # Parse a single byte range; fail closed to 416 on anything malformed.
        spec = rng[len("bytes="):].split(",")[0].strip()
        start_s, _, end_s = spec.partition("-")
        try:
            if start_s == "":
                suffix = int(end_s)            # bytes=-N  -> last N bytes
                if suffix <= 0:
                    raise ValueError
                ropts = {"range": {"suffix": suffix}}
            else:
                offset = int(start_s)          # bytes=A-  or  bytes=A-B
                if offset < 0:
                    raise ValueError
                if end_s == "":
                    ropts = {"range": {"offset": offset}}
                else:
                    end = int(end_s)
                    if end < offset:
                        raise ValueError
                    ropts = {"range": {"offset": offset, "length": end - offset + 1}}
        except ValueError:
            return Response.new("Range Not Satisfiable",
                                to_js({"status": 416}, dict_converter=Object.fromEntries))
        obj = await binding.get(path, to_js(ropts, dict_converter=Object.fromEntries))
        if obj is None:
            return Response.new("Not found", status=404)
        out = Headers.new()
        out.set("Content-Type", CONTENT_TYPE[bucket])
        out.set("Accept-Ranges", "bytes")
        out.set("Cache-Control", "private, max-age=60")
        total = obj.size
        # Derive the actually-served window from R2's resolved range (covers suffix too).
        r = obj.range
        rstart = int(r.offset) if hasattr(r, "offset") and r.offset is not None else 0
        rlen = int(r.length) if hasattr(r, "length") and r.length is not None else (total - rstart)
        last = max(rstart, rstart + rlen - 1)
        out.set("Content-Range", f"bytes {rstart}-{last}/{total}")
        return Response.new(obj.body, to_js({"status": 206, "headers": out},
                                            dict_converter=Object.fromEntries))
    else:
        obj = await binding.get(path)
        if obj is None:
            return Response.new("Not found", status=404)

        out = Headers.new()
        out.set("Content-Type", CONTENT_TYPE[bucket])
        out.set("Cache-Control", "private, max-age=60")
        return Response.new(obj.body, to_js({"status": 200, "headers": out},
                                            dict_converter=Object.fromEntries))
