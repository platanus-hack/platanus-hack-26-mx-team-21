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

async def _authorized(env, bearer, bucket, path):
    url = f"{env.SUPABASE_URL}/rest/v1/rpc/app_authorize_object"
    headers = {"apikey": env.SUPABASE_ANON_KEY, "Authorization": bearer,
               "Content-Type": "application/json"}
    body = json.dumps({"p_bucket": bucket, "p_path": path})
    resp = await fetch(url, _json_opts("POST", headers, body))
    if not resp.ok:
        return False
    text = (await resp.text()).strip()
    return text == "true"

async def on_fetch(request, env):
    u = URL.new(request.url)
    if u.pathname != "/api/r2/object":
        return Response.new("Not found", status=404)

    bucket = u.searchParams.get("bucket")
    path = u.searchParams.get("path")
    if bucket not in BINDINGS or not path:
        return Response.new("Bad request", status=400)

    bearer = request.headers.get("Authorization")
    if not bearer:
        return Response.new("Unauthorized", status=401)

    if not await _authorized(env, bearer, bucket, path):
        return Response.new("Forbidden", status=403)

    binding = getattr(env, BINDINGS[bucket])
    rng = request.headers.get("Range")
    if rng and rng.startswith("bytes="):
        start_s, _, end_s = rng[len("bytes="):].partition("-")
        offset = int(start_s) if start_s else 0
        opts = {"range": {"offset": offset}} if not end_s else \
               {"range": {"offset": offset, "length": int(end_s) - offset + 1}}
        obj = await binding.get(path, to_js(opts, dict_converter=Object.fromEntries))
        if obj is None:
            return Response.new("Not found", status=404)
        out = Headers.new()
        out.set("Content-Type", CONTENT_TYPE[bucket])
        out.set("Accept-Ranges", "bytes")
        out.set("Cache-Control", "private, max-age=60")
        total = obj.size
        last = max(offset, offset + (obj.range.length if hasattr(obj.range, "length") else total - offset) - 1)
        out.set("Content-Range", f"bytes {offset}-{last}/{total}")
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
