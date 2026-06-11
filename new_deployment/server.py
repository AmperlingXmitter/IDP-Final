# =============================================================================
#  PERSISTENT INFERENCE SERVER  -  deployment/server.py   (the "alternative call")
# -----------------------------------------------------------------------------
#  Loads BOTH models ONCE and answers over localhost HTTP, so a Java/PHP/C++/Node
#  app can get results without paying the ~3-10s model-load cost on every call.
#  Pure standard library - no Flask, no extra pip installs (Pi-friendly).
#
#  Start it:   python deployment/server.py            (keep it running)
#  Endpoints (INPUT = ?image=<path>, OUTPUT = JSON):
#     GET /classify?image=/path/foot.jpg  -> {"highest_level":..,"highest_label":..}
#     GET /segment?image=/path/foot.jpg   -> {"wound_pct":..,"foot_pct":..,..}
#     GET /health                         -> {"status":"ok"}
#
#  Optional tuning params (all have sensible defaults - usually omit them):
#     /classify : &conf=0.5
#     /segment  : &thresh=0.5 &necrosis_v=60 &necrosis_reach=0.045
#                 &no_necrosis=1 (U-Net only) &no_slough=1 (eschar only)
#                 &overlay=1 (also save the overlay PNG) &closeup=1 (save wound crop)
#                 - by default the server writes NO image files (fast); request them
#                   with overlay=1 / closeup=1 and read the paths from the JSON.
#
#  WHEN TO USE: best when a non-Python app processes MANY images. For one-off
#  calls, the simpler `python <script> <image> --json` subprocess is fine.
# =============================================================================
import os, sys, json
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # import siblings

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import predict_severity_class as pc
import segment_wound_size as sw

HOST, PORT = "127.0.0.1", 8077


def _get(q, key, cast, default):
    """Read an optional typed query param; fall back to default on missing/bad."""
    v = q.get(key, [None])[0]
    if v is None:
        return default
    try:
        return cast(v)
    except (ValueError, TypeError):
        return default


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        image = q.get("image", [None])[0]
        try:
            if u.path == "/health":
                self._json({"status": "ok"})
            elif image is None:
                self._json({"error": "missing ?image=<path>"}, 400)
            elif u.path == "/classify":
                self._json(pc.classify(image, conf=_get(q, "conf", float, 0.5)))
            elif u.path == "/segment":
                self._json(sw.segment(
                    image,
                    save_overlay=bool(_get(q, "overlay", int, 0)),     # default: no disk writes
                    save_closeup=bool(_get(q, "closeup", int, 0)),
                    thresh=_get(q, "thresh", float, 0.5),
                    grow_necrosis=not _get(q, "no_necrosis", int, 0),
                    recover_slough=not _get(q, "no_slough", int, 0),
                    necrosis_v=_get(q, "necrosis_v", int, 60),
                    necrosis_reach=_get(q, "necrosis_reach", float, 0.025)))
            else:
                self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def log_message(self, *a):       # keep stdout/stderr quiet
        pass


if __name__ == "__main__":
    print("[server] loading models (one time)...", file=sys.stderr)
    pc._get_model(); sw._get_model()            # warm both so first request is fast
    print(f"[server] ready on http://{HOST}:{PORT}", file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
