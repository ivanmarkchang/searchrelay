"""Localhost-only HTTP wrapper. No browser cross-origin access."""
import os
import secrets
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from pydantic import Field

from .config import Config, TEMPLATE, config_dir, save_config, tomllib
from .models import SearchRequest, Model
from .router import Router


class Credential(Model):
    value: str = Field(min_length=1, max_length=512)


def create_app(config: Config, router_factory=Router, config_path: Path | None = None):
    assets = Path(__file__).parent / "dashboard"
    session_secret = secrets.token_urlsafe(32)
    lock = asyncio.Lock()
    defaults = Config.model_validate(tomllib.loads(TEMPLATE))
    config = config.model_copy(deep=True)
    for name, value in defaults.providers.items():
        if name not in config.providers:
            config.providers[name] = value
    target = config_path or config_dir() / "config.toml"
    @asynccontextmanager
    async def lifespan(app):
        async with router_factory(config) as router:
            app.state.router = router
            yield

    app = FastAPI(title="SearchRelay", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if (host not in {"127.0.0.1", "localhost"} or (origin and origin != expected_origin)
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse({"error": "local_clients_only"}, status_code=403)
        token = os.environ.get("SEARCHRELAY_API_TOKEN")
        public_asset = request.method == "GET" and (
            request.url.path == "/" or request.url.path.startswith("/assets/"))
        if token and not public_asset and not secrets.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {token}"
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.url.path.startswith("/v1/dashboard") and request.method != "GET":
            if not secrets.compare_digest(request.headers.get("x-searchrelay-session", ""), session_secret):
                return JSONResponse({"error": "dashboard_session_required"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI's default error body can echo input; keep queries and unknown credentials private.
        return JSONResponse({"error": "invalid_search_request"}, status_code=422)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return HTMLResponse((assets / "index.html").read_text().replace("SESSION_SECRET", session_secret))

    @app.get("/assets/{filename}")
    async def asset(filename: str):
        if filename not in {"dashboard.css", "dashboard.js"}:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return FileResponse(assets / filename)

    @app.get("/v1/dashboard/settings")
    async def settings(request: Request):
        return request.app.state.router.config.model_dump()

    @app.put("/v1/dashboard/settings")
    async def update_settings(body: Config, request: Request):
        if any(cfg.enabled and name != "you" and not cfg.free_plan_confirmed
               for name, cfg in body.providers.items()):
            return JSONResponse({"error": "confirm_free_account_before_enabling"}, status_code=409)
        async with lock:
            try:
                save_config(body, target)
            except OSError:
                return JSONResponse({"error": "settings_not_saved"}, status_code=500)
            request.app.state.router.config = body
            request.app.state.router.state.prune(body.retention_days)
        return {"saved": True}

    @app.put("/v1/dashboard/credentials/{provider}")
    async def credential(provider: str, body: Credential, request: Request):
        if provider not in {"tavily", "firecrawl", "serpapi"}:
            return JSONResponse({"error": "unknown_keyed_provider"}, status_code=404)
        async with lock:
            request.app.state.router.credentials[provider] = body.value.strip()
        return {"configured": True, "storage": "server_memory_until_restart"}

    @app.delete("/v1/dashboard/credentials/{provider}")
    async def remove_credential(provider: str, request: Request):
        async with lock:
            request.app.state.router.credentials.pop(provider, None)
        return {"removed_session_key": True, "environment_key_may_still_apply": True}

    @app.get("/v1/dashboard/activity")
    async def activity(request: Request):
        state = request.app.state.router.state
        state.prune(request.app.state.router.config.retention_days)
        rows = state.db.execute("SELECT at, provider, outcome FROM events ORDER BY at DESC LIMIT 30").fetchall()
        return {"events": [{"at": at, "provider": provider, "outcome": outcome}
                            for at, provider, outcome in rows]}

    @app.delete("/v1/dashboard/cache")
    async def clear_cache(request: Request):
        async with lock:
            state = request.app.state.router.state
            state.db.execute("DELETE FROM cache")
            state.db.execute("DELETE FROM events")
        return {"cleared": True, "quota_counters_retained": True}

    @app.get("/health")
    async def health():
        return {"status": "ok", "free_only": True}

    @app.get("/v1/providers")
    async def providers(request: Request):
        return request.app.state.router.status()

    @app.post("/v1/search")
    async def search(body: SearchRequest, request: Request):
        async with lock:
            return await request.app.state.router.search(body)

    return app


def serve(config: Config, port: int, config_path: Path | None = None):
    import uvicorn
    uvicorn.run(create_app(config, config_path=config_path), host="127.0.0.1", port=port, access_log=False)
