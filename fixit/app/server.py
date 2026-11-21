"""FastAPI server: single-page app + streaming analyze endpoint + live checkout creation."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import gemini, pipeline  # noqa: E402
from .shop_mcp import ShopMCP, ShopMCPError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

# All Fix-It API routes live on `router`, so the same code serves two hosts:
#   * standalone Fix-It Cam (this module's `app`): router at /api, page at /
#   * restaurant-ops copilot (backend/app/main.py): router at /api/fixit, page at /fixit/
router = APIRouter()

# Optional event sinks: callables (kind: str, payload: dict) -> None. The restaurant-ops app
# registers its SQLite journal here so Fix-It scans and buys land on the shared timeline.
EVENT_SINKS: list = []


def emit(kind: str, payload: dict) -> None:
    for sink in list(EVENT_SINKS):
        try:
            sink(kind, payload)
        except Exception:  # logging must never break a scan or a checkout
            pass


def index_response():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/health")
async def health():
    return {"ok": True, "identify_model": gemini.IDENTIFY_MODEL, "rank_model": gemini.RANK_MODEL,
            "gate_model": gemini.DECISION_MODEL, "gemini_key": bool(os.getenv("GEMINI_API_KEY"))}


def _ev(kind: str, **data) -> bytes:
    return (json.dumps({"event": kind, **data}) + "\n").encode()


async def _save_upload(f: UploadFile) -> tuple[str, str]:
    mime = f.content_type or mimetypes.guess_type(f.filename or "")[0] or "application/octet-stream"
    if mime == "application/octet-stream" and (f.filename or "").lower().endswith((".mov", ".mp4", ".webm")):
        mime = mimetypes.guess_type(f.filename)[0] or "video/mp4"
    if not (mime.startswith("video/") or mime.startswith("image/")):
        raise HTTPException(400, f"Please upload a video or photo (got {mime}).")
    suffix = Path(f.filename or "clip").suffix or (".mp4" if mime.startswith("video/") else ".jpg")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    size = 0
    while chunk := await f.read(1 << 20):
        size += len(chunk)
        if size > MAX_UPLOAD_MB << 20:
            tmp.close(); os.unlink(tmp.name)
            raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB} MB). Keep clips 5-10 s.")
        tmp.write(chunk)
    tmp.close()
    return tmp.name, mime


@router.post("/analyze")
async def analyze(files: list[UploadFile] = File(default=[]), file: UploadFile | None = File(default=None),
                  note: str = Form("")):
    """Accepts one video, one photo, or several photos (keyframes of a clip, in order)."""
    uploads = ([file] if file else []) + list(files or [])
    if not uploads:
        raise HTTPException(400, "No file uploaded")
    saved = [await _save_upload(f) for f in uploads[:16]]
    videos = [s for s in saved if s[1].startswith("video/")]
    if videos:
        path, mime = videos[0]
        extra_paths = [p for p, _ in saved if p != path]
    else:
        path, mime = saved[0]
        extra_paths = [p for p, _ in saved[1:]]
    frame_paths = [p for p, _ in saved] if not videos and len(saved) > 1 else None
    frame_names = [f.filename or "" for f in uploads[:16]]

    async def stream():
        shop = ShopMCP()
        t_all = time.time()
        timings: dict = {}
        try:
            yield _ev("stage", stage="upload", label="Sending footage to Gemini 4…")
            t = time.time()
            if frame_paths:
                part = pipeline.frames_parts(frame_paths, [m for _, m in saved], frame_names)
            else:
                part = await pipeline.media_part(path, mime)
            timings["upload_s"] = round(time.time() - t, 2)
            yield _ev("stage", stage="diagnose", label=f"{gemini.IDENTIFY_MODEL} is watching the clip…")
            t = time.time()
            diag = await gemini.diagnose(part, note)
            timings["diagnose_s"] = round(time.time() - t, 2)
            yield _ev("diagnosis", diagnosis=diag, timings=timings)
            emit("fixit.diagnosis", {"diagnosis": diag, "note": note[:200], "media": mime,
                                     "timings": dict(timings)})

            frame = None
            if pipeline.is_video(mime):
                fb = await asyncio.to_thread(pipeline.extract_frame, path, float(diag.get("best_frame_seconds") or 0))
                frame = (fb, "image/jpeg") if fb else None
            elif frame_paths:
                i = pipeline.nearest_frame(frame_names, float(diag.get("best_frame_seconds") or 0))
                frame = (open(frame_paths[i], "rb").read(), saved[i][1])
            else:
                frame = (open(path, "rb").read(), mime)
            yield _ev("stage", stage="search", label="Searching Shop catalog by words and by keyframe photo…")
            t = time.time()
            cands = await pipeline.search_offers(shop, diag, frame)
            timings["search_s"] = round(time.time() - t, 2)
            yield _ev("stage", stage="gate", label=f"Gemini Decisions checking fit of {len(cands)} offers…")
            if cands:
                t = time.time()
                try:
                    fits = await gemini.fit_gate(diag, cands)
                    for c, f in zip(cands, fits):
                        c["fit"] = round(f, 3)
                    cands.sort(key=lambda c: -c.get("fit", 0))
                except Exception as e:
                    timings["gate_error"] = str(e)[:200]
                timings["gate_s"] = round(time.time() - t, 2)
            yield _ev("stage", stage="rank", label="Gemini 4 picking the top 3 for fit…")
            shortlist = [c for c in cands if c.get("fit", 1) >= 0.05][:8] or cands[:8]
            t = time.time()
            top = await gemini.rank(diag, shortlist) if shortlist else []
            timings["rank_s"] = round(time.time() - t, 2)
            timings["total_s"] = round(time.time() - t_all, 2)
            yield _ev("results", top=top, considered=len(cands), timings=timings)
            emit("fixit.results", {
                "item": diag.get("item"), "part": diag.get("broken_part"), "replace": diag.get("replace"),
                "confidence": diag.get("confidence"), "considered": len(cands),
                "fit": [{"title": c.get("title"), "shop": c.get("shop"), "fit": c.get("fit")} for c in cands[:8]],
                "top": [{"title": o.get("title"), "shop": o.get("shop"), "price_minor": o.get("price_minor"),
                         "currency": o.get("currency"), "fit": o.get("fit"), "product_url": o.get("product_url")}
                        for o in (top or [])],
                "timings": timings})
        except Exception as e:
            yield _ev("error", message=str(e)[:400])
            emit("fixit.error", {"message": str(e)[:400]})
        finally:
            await shop.aclose()
            for p, _ in saved:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class BuyClick(BaseModel):
    path: str = "checkout_url"  # "checkout_url" (primary) or "create_checkout" (Shop fallback)
    title: str = ""
    shop: str = ""
    price_minor: int | None = None
    currency: str | None = None
    fit: float | None = None


@router.post("/buy-click")
async def buy_click(click: BuyClick):
    """Beacon from the page when a shopper taps Checkout; only logged, never completes a purchase."""
    emit("fixit.buy_click", click.model_dump())
    return {"ok": True}


class CheckoutReq(BaseModel):
    shop: str
    variant_id: str
    quantity: int = 1


@router.post("/checkout")
async def checkout(req: CheckoutReq):
    """Create a real Shop checkout for one merchant and return continue_url exactly as returned.
    The shopper reviews and pays on the merchant page; we never call complete_checkout."""
    shop = ShopMCP()
    try:
        r = await shop.create_checkout(req.shop, req.variant_id, max(1, min(req.quantity, 5)))
    except ShopMCPError as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)
    finally:
        await shop.aclose()
    url = r.get("continue_url")
    if not url:
        return JSONResponse({"error": "No checkout link returned", "messages": r.get("messages")}, status_code=502)
    total = next((t.get("amount") for t in r.get("totals", []) if t.get("type") == "total"), None)
    emit("fixit.checkout_created", {"shop": req.shop, "variant_id": req.variant_id, "status": r.get("status"),
                                    "total_minor": total, "currency": r.get("currency")})
    return {"continue_url": url, "status": r.get("status"), "total_minor": total, "currency": r.get("currency")}


# ---------------------------------------------------------------------------
# Eval clip collection: bulk-upload messy phone clips with expected part keywords.
EVAL_DIR = ROOT / "eval" / "clips"
LABELS = EVAL_DIR / "labels.json"
EVAL_UPLOAD_KEY = os.getenv("EVAL_UPLOAD_KEY", "")


def _check_key(k: str):
    if EVAL_UPLOAD_KEY and k != EVAL_UPLOAD_KEY:
        raise HTTPException(403, "Bad or missing upload key (?k=...)")


def _load_labels() -> dict:
    try:
        return json.loads(LABELS.read_text())
    except Exception:
        return {}


@router.get("/eval-upload-page")
async def eval_upload_page(k: str = ""):
    _check_key(k)
    return FileResponse(ROOT / "static" / "eval_upload.html", headers={"Cache-Control": "no-store"})


@router.get("/eval-clips")
async def eval_clips(k: str = ""):
    _check_key(k)
    return _load_labels()


@router.post("/eval-upload")
async def eval_upload(files: list[UploadFile] = File(...), keywords: str = Form(...),
                      description: str = Form(""), k: str = Form("")):
    _check_key(k)
    kws = [w.strip() for w in keywords.replace(";", ",").split(",") if w.strip()]
    if not kws:
        raise HTTPException(400, "Give at least one expected keyword")
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    labels = _load_labels()
    saved = []
    for f in files:
        mime = f.content_type or mimetypes.guess_type(f.filename or "")[0] or ""
        if not (mime.startswith("video/") or mime.startswith("image/")):
            continue
        stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(f.filename or "clip").stem)[:40]
        name = f"{time.strftime('%H%M%S')}_{len(labels):03d}_{stem}{Path(f.filename or '').suffix.lower() or '.mp4'}"
        with open(EVAL_DIR / name, "wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        labels[name] = {"keywords": kws, "description": description, "mime": mime}
        saved.append(name)
    LABELS.write_text(json.dumps(labels, indent=2))
    return {"saved": saved, "total_clips": len(labels)}


def create_standalone_app() -> FastAPI:
    standalone = FastAPI(title="Fix-It Cam")
    standalone.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    standalone.add_api_route("/", index_response, methods=["GET"])
    standalone.add_api_route("/eval-upload", eval_upload_page, methods=["GET"])
    standalone.include_router(router, prefix="/api")
    return standalone


app = create_standalone_app()


def main():
    import uvicorn
    uvicorn.run("app.server:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
