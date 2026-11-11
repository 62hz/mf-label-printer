"""Web server: login, JSON API, label downloads.

Run (from the project folder):
  vault run dealpos mf-label-printer -- uv run python -m labelprinter.server --port 8794
Binds 127.0.0.1; reach it from the store through Tailscale Funnel (see README).
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dealpos_mcp.client import DealPOSError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import auth, outputs, tspl
from .catalog import Catalog, read_only_client
from .designs import DEFAULT_SLUG, DesignStore
from .model import Label
from .render import available_fonts, notes, png_bytes

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
MAX_ROWS = 200       # label rows per request
MAX_TOTAL = 500      # printed labels per request, copies included
MAX_CODES = 500      # distinct codes per resolve request
_CODE = re.compile(r"[^\s,;]+")  # a code is whatever sits between spaces, commas, semicolons and new lines
MAX_UPLOAD = 5 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
MAX_LOGIN_BODY = 4096
MIN_PASSWORD = 12    # characters
LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver", "[::1]", "::1"}  # "::1": urlsplit drops the brackets
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class BadRequest(Exception):
    pass


async def json_body(request: Request) -> dict:
    """The request body as a JSON object. Reads at most MAX_JSON bytes, so a huge body is refused as it arrives."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_JSON:
            raise BadRequest("Request is too large.")
    try:
        payload = json.loads(bytes(body))
    except RecursionError:  # absurdly deep nesting; other malformed JSON is a ValueError, handled as a 400 by `guarded`
        raise BadRequest("Invalid JSON.") from None
    if not isinstance(payload, dict):
        raise BadRequest("Expected a JSON object.")
    return payload


def check_code_count(text: str) -> None:
    """At most MAX_CODES distinct codes (same splitting and case rules as Catalog.resolve), stopping as soon as it is over."""
    seen = set()
    for token in _CODE.finditer(text):
        seen.add(token.group().casefold())
        if len(seen) > MAX_CODES:
            raise BadRequest(f"Too many codes (limit {MAX_CODES}).")


def parse_labels(payload) -> list[Label]:
    rows = payload.get("labels") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise BadRequest("No labels in the request.")
    if len(rows) > MAX_ROWS:
        raise BadRequest(f"Too many rows ({len(rows)}). Limit is {MAX_ROWS}.")
    labels = [Label.from_dict(r) for r in rows if isinstance(r, dict)]
    for n, label in enumerate(labels, 1):
        if not label.sku:
            raise BadRequest(f"Row {n} has no SKU.")
    total = sum(l.copies for l in labels)
    if total > MAX_TOTAL:
        raise BadRequest(f"{total} labels is too many. Limit is {MAX_TOTAL} per print.")
    return labels


def create_app(catalog, password: str, session_key: bytes, store: DesignStore | None = None) -> Starlette:
    throttle = auth.Throttle()
    store = store or DesignStore(ROOT / "data" / "designs")

    def design_from(payload) -> dict:
        """The working design the page sends (an object), a saved design's slug, or the default."""
        wanted = payload.get("design") if isinstance(payload, dict) else None
        if isinstance(wanted, dict):
            return wanted  # validated by whoever draws with it
        try:
            return store.get(wanted if isinstance(wanted, str) and wanted else DEFAULT_SLUG)
        except KeyError:
            raise BadRequest("Unknown design.") from None

    def authed(request: Request) -> bool:
        return auth.valid_token(request.cookies.get(auth.COOKIE), session_key)

    def guarded(handler):
        async def wrapper(request: Request):
            if not authed(request):
                if request.url.path.startswith("/api/"):
                    return JSONResponse({"error": "Not signed in."}, status_code=401)
                return RedirectResponse("/login", status_code=303)
            if request.url.path == "/api/sheet":  # refuse a big or unsized upload before the form is parsed
                length = request.headers.get("content-length", "")
                if not length.isdigit() or int(length) > MAX_UPLOAD + 65536:
                    return JSONResponse({"error": "File is over 5 MB."}, status_code=413)
            try:
                return await handler(request)
            except BadRequest as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except ValueError as exc:  # unprintable SKU etc. from the renderer
                return JSONResponse({"error": str(exc)}, status_code=400)
            except DealPOSError as exc:
                return JSONResponse({"error": f"DealPOS: {exc}"}, status_code=502)
            except KeyError:
                return JSONResponse({"error": "Not found."}, status_code=404)
        return wrapper

    def client_id(request: Request) -> str:
        # request.client is the TCP peer: main() starts uvicorn with proxy_headers=False, and this code never
        # reads X-Forwarded-For, which the sender controls.
        return request.client.host if request.client else "?"

    async def login_page(request: Request):
        return FileResponse(STATIC / "login.html")

    async def login(request: Request):
        who = client_id(request)
        if throttle.blocked(who):
            return JSONResponse({"error": "Too many wrong passwords. Try again in 10 minutes."}, status_code=429)
        # The page posts a small urlencoded form. Refuse anything else before the body is parsed (multipart spools to disk).
        kind = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if kind != "application/x-www-form-urlencoded":
            return JSONResponse({"error": "Unsupported content type."}, status_code=415)
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > MAX_LOGIN_BODY:
            return JSONResponse({"error": "Request is too large."}, status_code=413)
        form = await request.form()
        if not auth.password_ok(str(form.get("password", "")), password):
            throttle.record_failure(who)
            return RedirectResponse("/login?bad=1", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        secure = request.url.hostname not in LOCAL_HOSTS  # any non-local host is reached over https (Tailscale Funnel)
        resp.set_cookie(auth.COOKIE, auth.make_token(session_key), max_age=auth.EXPIRY_SECONDS,
                        httponly=True, samesite="lax", secure=secure)
        return resp

    async def logout(request: Request):
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE)
        return resp

    @guarded
    async def index(request: Request):
        return FileResponse(STATIC / "index.html")

    @guarded
    async def status(request: Request):
        await catalog.ensure()  # first page load reads the product list
        return JSONResponse(catalog.status())

    @guarded
    async def refresh(request: Request):
        count, refreshed = await catalog.refresh_if_stale()
        return JSONResponse({"products": count, "refreshed": refreshed})

    @guarded
    async def resolve(request: Request):
        text = str((await json_body(request)).get("text", ""))
        check_code_count(text)
        labels, missing = await catalog.resolve(text)
        return JSONResponse({"labels": [l.to_dict() for l in labels], "missing": missing})

    @guarded
    async def search(request: Request):
        labels = await catalog.search(request.query_params.get("q", ""))
        return JSONResponse({"labels": [l.to_dict() for l in labels]})

    @guarded
    async def enrich(request: Request):
        sku = str((await json_body(request)).get("sku", "")).strip()
        if not sku:
            raise BadRequest("No SKU.")
        return JSONResponse(await catalog.enrich(sku))

    @guarded
    async def sheet(request: Request):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise BadRequest("No file uploaded.")
        data = await upload.read()
        if len(data) > MAX_UPLOAD:
            raise BadRequest("File is over 5 MB.")
        labels, sheet_name = outputs.read_sheet(data, upload.filename or "")
        return JSONResponse({"labels": [l.to_dict() for l in labels], "sheet": sheet_name})

    @guarded
    async def label_png(request: Request):
        payload = await json_body(request)
        raw = payload.get("label", {})
        if not isinstance(raw, dict):
            raise BadRequest("Expected a label object.")
        label, design = Label.from_dict(raw), design_from(payload)
        png = await run_in_threadpool(png_bytes, label, design)
        warnings = await run_in_threadpool(notes, label, design)
        return Response(png, media_type="image/png", headers={"X-Label-Notes": " | ".join(warnings)})

    @guarded
    async def labels_pdf(request: Request):
        payload = await json_body(request)
        data = await run_in_threadpool(outputs.pdf_bytes, parse_labels(payload), design_from(payload))
        return Response(data, media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="mf-labels.pdf"'})

    @guarded
    async def labels_xlsx(request: Request):
        data = outputs.xlsx_bytes(parse_labels(await json_body(request)))
        return Response(data, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="mf-labels.xlsx"'})

    @guarded
    async def labels_tspl(request: Request):
        payload = await json_body(request)
        data = await run_in_threadpool(tspl.job, parse_labels(payload), design_from(payload))
        return Response(data, media_type="application/octet-stream")

    @guarded
    async def check_tspl(request: Request):
        design = store.get(DEFAULT_SLUG)
        data = await run_in_threadpool(tspl.check_job, design["gap_mm"], design["direction"])
        return Response(data, media_type="application/octet-stream")

    @guarded
    async def check_pdf(request: Request):
        data = await run_in_threadpool(lambda: outputs.pdf_from_images(tspl.check_images()))
        return Response(data, media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="mf-test-labels.pdf"'})

    @guarded
    async def designs_list(request: Request):
        return JSONResponse({"designs": store.list(), "default": DEFAULT_SLUG, "fonts": available_fonts()})

    @guarded
    async def design_one(request: Request):
        slug = request.path_params["slug"]
        if request.method == "DELETE":
            store.delete(slug)
            return JSONResponse({"deleted": slug})
        return JSONResponse(store.get(slug))

    @guarded
    async def design_save(request: Request):
        try:
            return JSONResponse({"slug": store.save(await json_body(request))})
        except ValueError as exc:
            raise BadRequest(str(exc)) from None

    routes = [
        Route("/login", login_page, methods=["GET"]),
        Route("/login", login, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/", index),
        Route("/api/status", status),
        Route("/api/refresh", refresh, methods=["POST"]),
        Route("/api/resolve", resolve, methods=["POST"]),
        Route("/api/search", search),
        Route("/api/enrich", enrich, methods=["POST"]),
        Route("/api/sheet", sheet, methods=["POST"]),
        Route("/api/label.png", label_png, methods=["POST"]),
        Route("/api/labels.pdf", labels_pdf, methods=["POST"]),
        Route("/api/labels.xlsx", labels_xlsx, methods=["POST"]),
        Route("/api/labels.tspl", labels_tspl, methods=["POST"]),
        Route("/api/test.tspl", check_tspl),
        Route("/api/test.pdf", check_pdf),
        Route("/api/designs", designs_list),
        Route("/api/designs", design_save, methods=["POST"]),
        Route("/api/designs/{slug}", design_one, methods=["GET", "DELETE"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    return Starlette(routes=routes)


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description="MF label printer web app")
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    password = os.environ.get("LABELPRINTER_PASSWORD", "")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Set LABELPRINTER_PASSWORD ({MIN_PASSWORD}+ characters), e.g. run with: vault run dealpos mf-label-printer -- ...")
    app = create_app(Catalog(read_only_client()), password, auth.get_session_key(ROOT / "data"))
    # proxy_headers=False: no forwarded header is ever trusted, so the login throttle keys on the real TCP peer.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
