import os
import json
import uuid
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from dotenv import load_dotenv

from database import get_db, UserProcess, init_db
from auth import (
    verify_password, create_new_process, get_current_process,
    SESSION_COOKIE, SESSION_MAX_AGE, contains_blocked_content,
    cookie_kwargs, IS_PRODUCTION,
)
from data import (
    BERUFSFELDER, CHARAKTEREIGENSCHAFTEN, AKTIVITAETEN, AUSSERGEWOEHNLICHE_BERUFE,
    WERTE_AUKTION, ENERGIE_STUNDEN,
    STEPS_ORDER, get_step_number, get_progress_percent, get_berufsfeld_by_id,
)
import ai

load_dotenv(override=True)
init_db()

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

VIDEO_URL = os.getenv("VIDEO_URL", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


VISIBLE_STEPS = [s for s in STEPS_ORDER if s not in ("start", "laden")]

# URL pro Schritt für die Zurück-Navigation
STEP_URLS = {
    "fakten": "/fakten",
    "reflexion": "/reflexion",
    "charakter": "/charakter",
    "werte": "/werte",
    "energie": "/energie",
    "berufsfelder": "/berufsfelder",
    "vergleich": "/vergleich",
    "ergebnis": "/ergebnis",
    "favoriten": "/favoriten",
    "pdf": "/links",
}

def prev_step_url(step: str):
    """Gibt die URL des vorigen sichtbaren Schritts zurück, oder None."""
    try:
        idx = VISIBLE_STEPS.index(step)
    except ValueError:
        return None
    if idx <= 0:
        return None
    return STEP_URLS.get(VISIBLE_STEPS[idx - 1])


def ctx(request: Request, process: UserProcess, extra: dict = None) -> dict:
    """Baut den Template-Kontext auf."""
    step = process.current_step
    try:
        visible_num = VISIBLE_STEPS.index(step) + 1
    except ValueError:
        visible_num = 0
    base = {
        "request": request,
        "current_step": step,
        "step_number": visible_num,
        "total_steps": len(VISIBLE_STEPS),
        "progress_percent": get_progress_percent(step),
        "prev_url": prev_step_url(step),
    }
    if extra:
        base.update(extra)
    return base


def redirect(path: str):
    return RedirectResponse(url=path, status_code=303)


def sync_step(process, step: str, db):
    """Aktualisiert current_step auf die gerade besuchte Seite (für Rückwärts-Navigation)."""
    if process.current_step != step:
        process.current_step = step
        db.commit()


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if process:
        return redirect("/start")
    # Testmodus-Button nur sichtbar bei ?nicola=1 (für interne Tests)
    show_testmode = request.query_params.get("nicola") == "1"
    return templates.TemplateResponse("login.html", {
        "request": request, "error": None,
        "is_production": IS_PRODUCTION, "show_testmode": show_testmode,
    })


@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    passwort: str = Form(...),
    db: Session = Depends(get_db),
):
    if not verify_password(passwort):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Das Passwort stimmt leider nicht. Bitte nochmal versuchen.", "is_production": IS_PRODUCTION}
        )
    process, signed_token = create_new_process(db)
    response = redirect("/start")
    response.set_cookie(SESSION_COOKIE, signed_token, **cookie_kwargs())
    return response


@app.get("/logout")
async def logout():
    response = redirect("/login")
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Start / Willkommen
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    if process.current_step == "start":
        return redirect("/start")
    return redirect(f"/{process.current_step}")


@app.get("/start", response_class=HTMLResponse)
async def start_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    return templates.TemplateResponse("start.html", ctx(request, process))


@app.post("/start")
async def start_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    process.current_step = "fakten"
    db.commit()
    return redirect("/fakten")


# ---------------------------------------------------------------------------
# Schritt 1: Fakten
# ---------------------------------------------------------------------------

@app.get("/fakten", response_class=HTMLResponse)
async def fakten_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "fakten", db)
    saved = process.get_json("fakten") or {}
    return templates.TemplateResponse("fakten.html", ctx(request, process, {"saved": saved}))


@app.post("/fakten")
async def fakten_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    data = dict(form)
    process.set_json("fakten", data)
    process.current_step = "reflexion"
    db.commit()
    return redirect("/reflexion")


# ---------------------------------------------------------------------------
# Schritt 2: Video
# ---------------------------------------------------------------------------

@app.get("/video", response_class=HTMLResponse)
async def video_get(request: Request, db: Session = Depends(get_db)):
    """Video-Schritt deaktiviert – direkt zu Reflexion."""
    return redirect("/reflexion")


@app.post("/video")
async def video_post(request: Request, db: Session = Depends(get_db)):
    return redirect("/reflexion")


# ---------------------------------------------------------------------------
# Schritt 3: Reflexion
# ---------------------------------------------------------------------------

@app.get("/reflexion", response_class=HTMLResponse)
async def reflexion_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "reflexion", db)
    saved = process.get_json("reflexion") or {}
    return templates.TemplateResponse("reflexion.html", ctx(request, process, {"saved": saved}))


@app.post("/reflexion")
async def reflexion_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    data = dict(form)

    for key, val in data.items():
        if contains_blocked_content(str(val)):
            return templates.TemplateResponse(
                "reflexion.html",
                ctx(request, process, {
                    "saved": data,
                    "fehler": "Bitte nutze respektvolle Sprache. Manche Wörter sind nicht erlaubt.",
                }),
            )

    process.set_json("reflexion", data)
    process.current_step = "charakter"
    db.commit()
    return redirect("/charakter")


# ---------------------------------------------------------------------------
# Schritt 4: Charakter
# ---------------------------------------------------------------------------

@app.get("/charakter", response_class=HTMLResponse)
async def charakter_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "charakter", db)
    saved = process.get_json("charakter") or {}
    return templates.TemplateResponse(
        "charakter.html",
        ctx(request, process, {
            "eigenschaften": CHARAKTEREIGENSCHAFTEN,
            "saved": saved,
        }),
    )


@app.post("/charakter")
async def charakter_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    data = {e["id"]: int(form.get(e["id"], 0)) for e in CHARAKTEREIGENSCHAFTEN}
    process.set_json("charakter", data)
    process.current_step = "werte"
    db.commit()
    return redirect("/werte")


# ---------------------------------------------------------------------------
# Schritt: Werte-Auktion
# ---------------------------------------------------------------------------

@app.get("/werte", response_class=HTMLResponse)
async def werte_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "werte", db)
    saved = process.get_json("werte") or {}
    return templates.TemplateResponse(
        "werte.html",
        ctx(request, process, {"werte": WERTE_AUKTION, "saved": saved}),
    )


@app.post("/werte")
async def werte_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    data = {}
    summe = 0
    for w in WERTE_AUKTION:
        try:
            v = int(form.get(w["id"], 0))
        except (TypeError, ValueError):
            v = 0
        v = max(0, min(100, v))
        data[w["id"]] = v
        summe += v
    if summe != 100:
        return templates.TemplateResponse(
            "werte.html",
            ctx(request, process, {
                "werte": WERTE_AUKTION,
                "saved": data,
                "fehler": f"Bitte verteile genau 100 Punkte. Aktuell sind es {summe}.",
            }),
        )
    process.set_json("werte", data)
    process.current_step = "energie"
    db.commit()
    return redirect("/energie")


# ---------------------------------------------------------------------------
# Schritt: Energiekurve
# ---------------------------------------------------------------------------

@app.get("/energie", response_class=HTMLResponse)
async def energie_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "energie", db)
    raw = process.get_json("energie") or {}
    saved = {h: int(raw.get(str(h), 0)) for h in ENERGIE_STUNDEN}
    return templates.TemplateResponse(
        "energie.html",
        ctx(request, process, {"stunden": ENERGIE_STUNDEN, "saved": saved}),
    )


@app.post("/energie")
async def energie_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    data = {}
    for h in ENERGIE_STUNDEN:
        try:
            v = int(form.get(f"h_{h}", 0))
        except (TypeError, ValueError):
            v = 0
        data[str(h)] = max(0, min(5, v))
    process.set_json("energie", data)
    process.current_step = "berufsfelder"
    db.commit()
    return redirect("/berufsfelder")


# ---------------------------------------------------------------------------
# Schritt 5: Berufsfelder
# ---------------------------------------------------------------------------

@app.get("/berufsfelder", response_class=HTMLResponse)
async def berufsfelder_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "berufsfelder", db)
    saved = process.get_json("berufsfelder") or {"ausgewaehlt": []}
    return templates.TemplateResponse(
        "berufsfelder.html",
        ctx(request, process, {
            "berufsfelder": BERUFSFELDER,
            "saved": saved,
        }),
    )


@app.post("/berufsfelder")
async def berufsfelder_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    ausgewaehlt = form.getlist("berufsfeld")
    custom_eingabe = (form.get("custom_eingabe") or "").strip()
    if len(ausgewaehlt) < 2:
        saved = {"ausgewaehlt": ausgewaehlt, "custom_eingabe": custom_eingabe}
        return templates.TemplateResponse(
            "berufsfelder.html",
            ctx(request, process, {
                "berufsfelder": BERUFSFELDER,
                "saved": saved,
                "fehler": "Bitte wähle mindestens 2 Berufsfelder aus.",
            }),
        )
    process.set_json("berufsfelder", {"ausgewaehlt": ausgewaehlt, "custom_eingabe": custom_eingabe})
    process.current_step = "vergleich"
    db.commit()
    return redirect("/vergleich")


# ---------------------------------------------------------------------------
# Schritt 6: Vergleich (Duell-System)
# ---------------------------------------------------------------------------

@app.get("/vergleich", response_class=HTMLResponse)
async def vergleich_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "vergleich", db)

    vergleich = process.get_json("vergleich")

    if not vergleich:
        vergleich = {
            "aktivitaeten": AKTIVITAETEN,
            "current_index": 0,
            "bock": [],
            "kein_bock": [],
            "vielleicht": [],
            "fertig": False,
        }
        process.set_json("vergleich", vergleich)
        db.commit()

    if vergleich.get("fertig"):
        return redirect("/laden")

    idx = vergleich["current_index"]
    aktivitaeten = vergleich["aktivitaeten"]
    aktuelle = aktivitaeten[idx] if idx < len(aktivitaeten) else None

    return templates.TemplateResponse(
        "vergleich.html",
        ctx(request, process, {
            "aktuelle": aktuelle,
            "fortschritt": idx,
            "gesamt": len(aktivitaeten),
            "bock": vergleich["bock"],
            "vielleicht": vergleich["vielleicht"],
        }),
    )


@app.post("/vergleich")
async def vergleich_post(
    request: Request,
    antwort: str = Form(...),
    db: Session = Depends(get_db),
):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")

    vergleich = process.get_json("vergleich")
    if not vergleich or vergleich.get("fertig"):
        return redirect("/laden")

    idx = vergleich["current_index"]
    aktivitaeten = vergleich["aktivitaeten"]

    if idx < len(aktivitaeten):
        aktuelle = aktivitaeten[idx]
        if antwort == "bock":
            vergleich["bock"].append(aktuelle)
        elif antwort == "vielleicht":
            vergleich["vielleicht"].append(aktuelle)
        else:
            vergleich["kein_bock"].append(aktuelle)

    vergleich["current_index"] = idx + 1

    if vergleich["current_index"] >= len(aktivitaeten):
        vergleich["fertig"] = True

    process.set_json("vergleich", vergleich)
    db.commit()

    if vergleich["fertig"]:
        return redirect("/laden")
    return redirect("/vergleich")


@app.get("/vergleich/skip")
async def vergleich_skip(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    vergleich = process.get_json("vergleich") or {}
    vergleich["fertig"] = True
    if "aktivitaeten" not in vergleich:
        vergleich["aktivitaeten"] = AKTIVITAETEN
        vergleich["bock"] = []
        vergleich["kein_bock"] = []
        vergleich["vielleicht"] = []
        vergleich["current_index"] = len(AKTIVITAETEN)
    process.set_json("vergleich", vergleich)
    db.commit()
    return redirect("/laden")


# ---------------------------------------------------------------------------
# Laden / KI-Auswertung
# ---------------------------------------------------------------------------

@app.get("/laden", response_class=HTMLResponse)
async def laden_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    already_done = process.get_json("ergebnis")
    if already_done:
        return redirect("/ergebnis")
    return templates.TemplateResponse("laden.html", ctx(request, process))


@app.post("/api/auswertung")
async def api_auswertung(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)

    if process.get_json("ergebnis"):
        return JSONResponse({"status": "already_done"})

    vergleich_raw = process.get_json("vergleich") or {}
    process_data = {
        "fakten": process.get_json("fakten"),
        "reflexion": process.get_json("reflexion"),
        "charakter": process.get_json("charakter"),
        "werte": process.get_json("werte"),
        "energie": process.get_json("energie"),
        "berufsfelder": process.get_json("berufsfelder"),
        "vergleich_bock": vergleich_raw.get("bock", []),
        "vergleich_vielleicht": vergleich_raw.get("vielleicht", []),
        "vergleich_kein_bock": vergleich_raw.get("kein_bock", []),
    }

    try:
        ergebnis = ai.generate_auswertung(process_data)
        process.set_json("ergebnis", ergebnis)
        process.current_step = "ergebnis"
        db.commit()
        return JSONResponse({"status": "ok"})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("AUSWERTUNG FEHLER:\n", tb)
        return JSONResponse({"error": str(e), "traceback": tb}, status_code=500)


# ---------------------------------------------------------------------------
# Ergebnis: Top 15 + Goldener Tropfen
# ---------------------------------------------------------------------------

@app.get("/ergebnis", response_class=HTMLResponse)
async def ergebnis_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    ergebnis = process.get_json("ergebnis")
    if not ergebnis:
        return redirect("/laden")
    sync_step(process, "ergebnis", db)

    # Personalisierte Außergewöhnliche Berufe: AI wählt 4 aus der statischen Liste
    empfehlung_namen = ergebnis.get("aussergewoehnliche_empfehlung") or []
    if empfehlung_namen:
        namen_set = set(empfehlung_namen)
        aussergewoehnliche = [b for b in AUSSERGEWOEHNLICHE_BERUFE if b["name"] in namen_set]
    else:
        aussergewoehnliche = AUSSERGEWOEHNLICHE_BERUFE[:4]

    return templates.TemplateResponse(
        "ergebnis.html",
        ctx(request, process, {
            "ergebnis": ergebnis,
            "aussergewoehnliche": aussergewoehnliche,
        }),
    )


# ---------------------------------------------------------------------------
# Favoriten: 5 auswählen
# ---------------------------------------------------------------------------

@app.get("/favoriten", response_class=HTMLResponse)
async def favoriten_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "favoriten", db)
    ergebnis = process.get_json("ergebnis")
    if not ergebnis:
        return redirect("/ergebnis")
    saved = process.get_json("favoriten") or {"ausgewaehlt": []}
    return templates.TemplateResponse(
        "favoriten.html",
        ctx(request, process, {
            "top_berufe": ergebnis.get("top_berufe", []),
            "saved": saved,
        }),
    )


@app.post("/favoriten")
async def favoriten_post(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    form = await request.form()
    ausgewaehlt = form.getlist("favorit")
    if len(ausgewaehlt) != 5:
        ergebnis = process.get_json("ergebnis") or {}
        return templates.TemplateResponse(
            "favoriten.html",
            ctx(request, process, {
                "top_berufe": ergebnis.get("top_berufe", []),
                "saved": {"ausgewaehlt": ausgewaehlt},
                "fehler": f"Bitte wähle genau 5 Favoriten aus. Du hast {len(ausgewaehlt)} ausgewählt.",
            }),
        )
    # Wenn sich die Favoritenauswahl ändert, müssen die Links neu generiert werden
    alt = process.get_json("favoriten") or {}
    if alt.get("ausgewaehlt") != ausgewaehlt:
        process.links_data = None
    process.set_json("favoriten", {"ausgewaehlt": ausgewaehlt})
    process.current_step = "pdf"
    db.commit()
    return redirect("/links")


# ---------------------------------------------------------------------------
# Links zu den 5 Favoriten
# ---------------------------------------------------------------------------

@app.get("/links", response_class=HTMLResponse)
async def links_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")
    sync_step(process, "pdf", db)  # "pdf" = links in STEPS_ORDER
    favoriten = process.get_json("favoriten")
    if not favoriten:
        return redirect("/favoriten")

    links_data = process.get_json("links_data")
    return templates.TemplateResponse(
        "links.html",
        ctx(request, process, {
            "favoriten": favoriten["ausgewaehlt"],
            "links_data": links_data,
            "laden": links_data is None,
        }),
    )


@app.post("/api/links")
async def api_links(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)

    if process.get_json("links_data"):
        return JSONResponse({"status": "already_done"})

    favoriten = process.get_json("favoriten") or {}
    ausgewaehlt = favoriten.get("ausgewaehlt", [])
    ergebnis = process.get_json("ergebnis") or {}
    goldener_tropfen = ergebnis.get("goldener_tropfen", "")

    try:
        links = ai.get_links_fuer_favoriten(ausgewaehlt, goldener_tropfen)
        process.set_json("links_data", links)
        db.commit()
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# PDF / Goldener Tropfen Ansicht
# ---------------------------------------------------------------------------

@app.get("/pdf", response_class=HTMLResponse)
async def pdf_get(request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return redirect("/login")

    fakten = process.get_json("fakten") or {}
    reflexion = process.get_json("reflexion") or {}
    charakter_data = process.get_json("charakter") or {}
    ergebnis = process.get_json("ergebnis") or {}
    favoriten = process.get_json("favoriten") or {}
    links_raw = process.get_json("links_data") or {}
    # Sicherstellen dass jeder Wert ein Dict ist
    links_data = {k: v for k, v in links_raw.items() if isinstance(v, dict)}

    from data import CHARAKTEREIGENSCHAFTEN
    charakter_list = [
        {"name": e["name"], "wert": charakter_data.get(e["id"], 0)}
        for e in CHARAKTEREIGENSCHAFTEN
        if charakter_data.get(e["id"], 0) >= 3
    ]

    # Map Berufsname → Beruf-Objekt für das Template vorberechnen
    top_berufe_map = {b["name"]: b for b in ergebnis.get("top_berufe", [])}
    favoriten_liste = favoriten.get("ausgewaehlt", [])
    favoriten_berufe = [
        {"name": name, **top_berufe_map.get(name, {})}
        for name in favoriten_liste
    ]

    return templates.TemplateResponse(
        "pdf.html",
        ctx(request, process, {
            "fakten": fakten,
            "reflexion": reflexion,
            "charakter_list": charakter_list,
            "ergebnis": ergebnis,
            "favoriten_berufe": favoriten_berufe,
            "links_data": links_data,
            "datum": datetime.now().strftime("%d.%m.%Y"),
        }),
    )


# ---------------------------------------------------------------------------
# AJAX: Kreative Ideen zu einem Beruf
# ---------------------------------------------------------------------------

@app.get("/api/kreativ/{beruf}")
async def api_kreativ(beruf: str, request: Request, db: Session = Depends(get_db)):
    process = get_current_process(request, db)
    if not process:
        return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)
    ergebnis = process.get_json("ergebnis") or {}
    profil = ergebnis.get("goldener_tropfen", "")
    # Bis zu zwei Versuche, danach ehrlich Fehler zurückgeben
    last_error = None
    for _ in range(2):
        try:
            ideen = ai.get_kreative_ideen(beruf, profil)
            return JSONResponse({"ideen": ideen})
        except Exception as e:
            last_error = str(e)
            continue
    return JSONResponse(
        {"error": "Die KI hat gerade keine Antwort geliefert. Bitte gleich nochmal versuchen.", "detail": last_error},
        status_code=503,
    )


# ---------------------------------------------------------------------------
# AJAX: Berufsfeld-Erklärung (statisch, kein AI-Call)
# ---------------------------------------------------------------------------

@app.post("/api/dokument-prefill")
async def api_dokument_prefill(request: Request, db: Session = Depends(get_db)):
    """Schreibt vorausgefüllte Dokument-Daten in die Session."""
    process = get_current_process(request, db)
    if not process:
        return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)
    try:
        daten = await request.json()
        if "fakten" in daten and isinstance(daten["fakten"], dict):
            bestehend = process.get_json("fakten") or {}
            bestehend.update({k: v for k, v in daten["fakten"].items() if v})
            process.set_json("fakten", bestehend)
        if "reflexion" in daten and isinstance(daten["reflexion"], dict):
            bestehend = process.get_json("reflexion") or {}
            bestehend.update({k: v for k, v in daten["reflexion"].items() if v})
            process.set_json("reflexion", bestehend)
        db.commit()
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/dokument-upload")
async def api_dokument_upload(
    request: Request,
    datei: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Liest ein hochgeladenes Dokument und gibt vorausgefüllte Felder zurück."""
    process = get_current_process(request, db)
    if not process:
        return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)

    inhalt = await datei.read()
    text = ""

    try:
        name = datei.filename or ""
        if name.endswith(".pdf"):
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(inhalt))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        elif name.endswith(".docx"):
            import io
            from docx import Document
            doc = Document(io.BytesIO(inhalt))
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            text = inhalt.decode("utf-8", errors="ignore")
    except Exception as e:
        return JSONResponse({"error": f"Datei konnte nicht gelesen werden: {e}"}, status_code=400)

    if len(text.strip()) < 20:
        return JSONResponse({"error": "Das Dokument scheint leer zu sein."}, status_code=400)

    try:
        extrakt = ai.extract_from_dokument(text)
    except Exception:
        return JSONResponse({"error": "Das Dokument konnte nicht ausgewertet werden. Bitte versuche es nochmal oder starte ohne Dokument."}, status_code=500)

    try:
        if "fakten" in extrakt and isinstance(extrakt["fakten"], dict):
            bestehend = process.get_json("fakten") or {}
            bestehend.update({k: v for k, v in extrakt["fakten"].items() if v})
            process.set_json("fakten", bestehend)
        if "reflexion" in extrakt and isinstance(extrakt["reflexion"], dict):
            bestehend = process.get_json("reflexion") or {}
            bestehend.update({k: v for k, v in extrakt["reflexion"].items() if v})
            process.set_json("reflexion", bestehend)
        db.commit()
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/berufsfeld/{bid}")
async def api_berufsfeld(bid: str):
    info = get_berufsfeld_by_id(bid)
    if not info:
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    return JSONResponse(info)


# ---------------------------------------------------------------------------
# Autosave: kontinuierliches Zwischenspeichern von Eingaben
# ---------------------------------------------------------------------------

ALLOWED_AUTOSAVE_STEPS = {"fakten", "reflexion", "charakter", "berufsfelder"}


@app.post("/api/autosave/{step}")
async def api_autosave(step: str, request: Request, db: Session = Depends(get_db)):
    """Speichert Zwischenstände eines Schritts (Textfelder, Auswahlen).

    Erlaubt nur die eigene Session und nur die definierten Schritte.
    """
    if step not in ALLOWED_AUTOSAVE_STEPS:
        return JSONResponse({"error": "step nicht erlaubt"}, status_code=400)
    process = get_current_process(request, db)
    if not process:
        return JSONResponse({"error": "nicht eingeloggt"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "ungültige Daten"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "ungültiges Format"}, status_code=400)

    # Nur einfache Felder akzeptieren – kein verschachteltes Zeug
    sauber = {k: v for k, v in payload.items() if isinstance(k, str) and isinstance(v, (str, int, float, bool, list))}
    bestehend = process.get_json(step) or {}
    bestehend.update(sauber)
    process.set_json(step, bestehend)
    db.commit()
    return JSONResponse({"status": "ok", "saved_at": datetime.utcnow().isoformat()})


# ---------------------------------------------------------------------------
# Entwickler-Quicktest (nur für lokale Tests – direkt zum Ergebnis springen)
# ---------------------------------------------------------------------------

@app.get("/dev/quicktest")
async def dev_quicktest(request: Request, db: Session = Depends(get_db)):
    """Legt eine neue Session mit Testdaten an und springt direkt zum Ergebnis."""
    process, signed_token = create_new_process(db)

    # Testdaten für alle Schritte
    process.set_json("fakten", {
        "vorname": "Lena",
        "alter": "19",
        "bundesland": "Wien",
        "schulform": "ahs",
        "abschluss": "reife",
        "leistungskurse": "Biologie, Deutsch",
        "note": "2,1",
        "ausbildung_ja": "nein",
        "ki_einwilligung": "ja",
        "interesse_human_design": "vielleicht",
        "interesse_numerologie": "nein",
        "interesse_astrologie": "ja",
        "sternzeichen": "Krebs",
    })
    process.set_json("reflexion", {
        "selbst_eigene_sicht": "Ich bin eher ruhig, beobachte viel und denke tief nach. Ich brauche Zeit für mich, bin aber bei Freunden sehr offen und fürsorglich.",
        "sicht_mutter": "Verantwortungsbewusst, manchmal zu selbstkritisch und sehr kreativ.",
        "sicht_freund": "Immer für andere da, verlässlich, manchmal zu bescheiden.",
        "hobbys": "Lesen, Zeichnen, Musik hören, Yoga",
        "was_macht_gluecklich": "Jemandem helfen, kreativ sein, in der Natur sein",
        "bewunderung": "Menschen, die sich trauen, ihren eigenen Weg zu gehen",
        "kann_gut": "Zuhören, komplexe Dinge einfach erklären, kreativ sein",
        "moechte_koennen": "Besser sprechen vor Gruppen, Programmieren",
        "werte": "Ehrlichkeit, Familie, Kreativität, Freiheit",
        "sinn": "Wenn ich das Gefühl habe, dass ich jemandem wirklich geholfen habe",
        "antreiber": "Das Gefühl, dass meine Arbeit einen Unterschied macht",
        "stundenlang": "Zeichnen, Bücher lesen, tiefe Gespräche führen",
        "millionen_frage": "Reisen, meine Familie absichern, dann etwas mit Kindern und Kunst aufbauen",
        "kindheitstraum": "Tierärztin oder Künstlerin",
        "jetzt_entscheidung": "Etwas mit Menschen und Kreativität",
        "geld_wichtigkeit": "mittel",
        "offenheit": "mittel",
        "lustig": "manchmal",
        "sprachen": "Deutsch, Englisch, etwas Spanisch",
        "gedanken_im_kopf": "Ich mache mir Sorgen, die falsche Wahl zu treffen und dann feststecken. Meine Eltern erwarten, dass ich studiere. Ich weiß nicht mal was. Gleichzeitig sehe ich alle aus meiner Klasse, die schon wissen was sie wollen – oder so tun als ob.",
        "angst_druck": "Definitiv Druck von zu Hause. Und Vergleich mit anderen. Ich denke manchmal, ich bin zu langsam.",
    })
    process.set_json("charakter", {
        "kreativitaet": 5, "empathie": 5, "durchsetzung": 2,
        "zuverlaessigkeit": 4, "neugier": 4, "fuehrung": 2,
        "teamarbeit": 3, "selbststaendigkeit": 4, "kommunikation": 3,
        "geduld": 4, "analytik": 3, "flexibilitaet": 4,
        "belastbarkeit": 3, "humor": 3, "ordnung": 3,
        "mut": 2, "einfuehlsamkeit": 5, "ehrgeiz": 3,
        "offenheit": 4, "verantwortung": 4,
    })
    process.set_json("werte", {
        "sinn": 25, "geld": 5, "freiheit": 15, "familie": 15, "abenteuer": 10,
        "sicherheit": 5, "anerkennung": 5, "kreativitaet": 10, "lernen": 5, "helfen": 5,
    })
    process.set_json("energie", {
        "6": 1, "7": 2, "8": 3, "9": 4, "10": 5, "11": 5, "12": 4, "13": 3,
        "14": 3, "15": 4, "16": 4, "17": 3, "18": 2, "19": 2, "20": 1, "21": 1, "22": 0,
    })
    process.set_json("berufsfelder", {
        "ausgewaehlt": ["paedagogik", "psychologie", "kunst", "medizin"]
    })
    process.set_json("vergleich", {
        "aktivitaeten": AKTIVITAETEN,
        "current_index": len(AKTIVITAETEN),
        "bock": ["Mit Kindern arbeiten", "Kreativ gestalten", "Texte schreiben", "Anderen helfen", "Draußen sein", "Musik machen"],
        "kein_bock": ["Maschinen reparieren", "Verkaufen", "Buchhalten"],
        "vielleicht": ["Präsentieren", "Programmieren"],
        "fertig": True,
    })
    # Mock-Ergebnis (kein AI-Call nötig beim Testen)
    process.set_json("ergebnis", {
        "goldener_tropfen": "Lena, dir ist es nicht egal. Du willst nicht einfach irgendwas machen, du willst, dass es sich richtig anfühlt. Das merkt man in allem, was du geschrieben hast. Und dass du noch keine Antwort hast, bedeutet nicht, dass du zu langsam bist. Es bedeutet, dass du ehrlich bist.",
        "motivationsmuster": ["Du brauchst Sinn, Geld ist dir nicht das Wichtigste", "Du musst kreativ sein dürfen, sonst geht dir die Luft aus", "Du gehst lieber in die Tiefe als an der Oberfläche zu bleiben", "Du willst etwas zurückgeben und für andere da sein", "Du gehst gerne deinen eigenen Weg, auch wenn er unbequem ist"],
        "staerken": ["Du kannst Menschen wirklich zuhören", "Du kannst dich kreativ ausdrücken", "Du bist verlässlich und nimmst Dinge ernst", "Du erklärst komplizierte Dinge so, dass sie jeder versteht"],
        "top_berufe": [
            {"name": "Kunsttherapeutin", "bereich": "Therapie & Kreativität", "warum": "Du verbindest kreatives Gestalten mit echter Hilfe für Menschen. Kunsttherapie ist genau dieser Schnittpunkt.", "ausbildungsweg": "Studium (B.A. Kunsttherapie)", "kreativ_potenzial": "Eigene Ateliers, Workshops für besondere Gruppen."},
            {"name": "Kinderbuchautorin / Illustratorin", "bereich": "Kunst & Literatur", "warum": "Deine Liebe zum Zeichnen und Lesen trifft auf dein Herz für Kinder. Kinderbücher kann man auch neben dem Beruf starten.", "ausbildungsweg": "Selbststudium + Illustration-Ausbildung", "kreativ_potenzial": "Eigener Verlag, digitale Illustrationen, Social Media."},
            {"name": "Sozialpädagogin", "bereich": "Pädagogik & Soziales", "warum": "Du willst, dass deine Arbeit etwas bewirkt. Sozialpädagogik gibt dir genau das – mit echten Menschen, echten Wirkungen.", "ausbildungsweg": "Studium oder Ausbildung", "kreativ_potenzial": "Projekte mit Kunst, Musik, Theater als Werkzeug."},
            {"name": "UX-Designerin", "bereich": "Design & Technologie", "warum": "Dein Blick für Menschen und deine Kreativität sind perfekt für User Experience Design – Produkte menschlich machen.", "ausbildungsweg": "Bootcamp, Studium oder Selbststudium", "kreativ_potenzial": "Freiberuflich für NGOs, Start-ups, internationale Teams."},
            {"name": "Hebamme", "bereich": "Medizin & Fürsorge", "warum": "Einer der wertvollsten Momente im Leben eines Menschen – du wärst dabei. Verantwortung und Empathie in Reinform.", "ausbildungsweg": "Studium (B.Sc. Hebammenwissenschaft)", "kreativ_potenzial": "Eigene Praxis, Geburtsvorbereitungskurse, Yoga für Schwangere."},
            {"name": "Psychologiestudium + Coaching", "bereich": "Psychologie & Beratung", "warum": "Dein tiefer Wunsch, Menschen zu verstehen und zu helfen, findet hier seinen Rahmen.", "ausbildungsweg": "Studium (B.Sc. Psychologie)", "kreativ_potenzial": "Eigene Praxis, Online-Angebote, Nischen für Jugendliche."},
            {"name": "Lehrerin (Kunst oder Bio)", "bereich": "Bildung", "warum": "Du kannst gut erklären, du magst Kinder, du liebst Biologie und Kunst. Das ist keine Zufallskombination.", "ausbildungsweg": "Lehramtsstudium", "kreativ_potenzial": "Schulprojekte, Kunsträume gestalten, außerschulische AGs."},
            {"name": "Tierärztin", "bereich": "Medizin & Natur", "warum": "Dein Kindheitstraum – und der kommt nicht von ungefähr. Empathie für Lebewesen ist dein Markenzeichen.", "ausbildungsweg": "Veterinärstudium (anspruchsvoll, aber machbar)", "kreativ_potenzial": "Praxis mit Fokus auf Kleintiere, Wildtiere, NGO-Arbeit."},
            {"name": "Ergotherapeutin", "bereich": "Therapie & Gesundheit", "warum": "Kreative Alltagshilfe für Menschen, die Unterstützung brauchen. Sehr bodenständig, sehr sinnvoll.", "ausbildungsweg": "Ausbildung (3 Jahre)", "kreativ_potenzial": "Spezialisierung auf Kinder, Kunst als Therapiemittel."},
            {"name": "Content Creatorin (Bildung & Kreativität)", "bereich": "Medien & Kreativwirtschaft", "warum": "Du könntest das, was du weißt und liebst, mit anderen teilen – auf YouTube, Instagram, als Blog. Das ist ein echter Beruf.", "ausbildungsweg": "Selbststudium + Learning by doing", "kreativ_potenzial": "Eigene Community, Online-Kurse, Kooperationen."},
            {"name": "Designtherapeutin / Art Director", "bereich": "Design & Kommunikation", "warum": "Wer Kreativität und Menschenkenntnis verbindet, kann Marken, Kampagnen oder Produkte gestalten, die berühren.", "ausbildungsweg": "Studium Kommunikationsdesign oder Grafikdesign", "kreativ_potenzial": "Agentur, Freelance, eigene Marke aufbauen."},
            {"name": "Social Entrepreneurin", "bereich": "Unternehmertum & Soziales", "warum": "Du willst etwas bewirken – warum nicht ein eigenes Projekt oder Unternehmen, das genau das tut? Das kann man lernen.", "ausbildungsweg": "Studium Entrepreneurship oder Selbststart", "kreativ_potenzial": "Eigene NGO, Impact Start-up, Fördergelder."},
            {"name": "Logopädin", "bereich": "Therapie & Sprache", "warum": "Sprache, Kommunikation, Geduld – du bringst alles mit, was dieser Beruf braucht.", "ausbildungsweg": "Ausbildung (3 Jahre)", "kreativ_potenzial": "Spezialisierung auf Kinder, Stottern, Stimme."},
            {"name": "Landschaftsarchitektin", "bereich": "Natur & Gestaltung", "warum": "Draußen sein, Räume für Menschen gestalten, Natur schützen – eine selten bedachte Kombination.", "ausbildungsweg": "Studium Landschaftsarchitektur", "kreativ_potenzial": "Stadtbegrünung, Schulgärten, nachhaltige Projekte."},
            {"name": "Musiktherapeutin", "bereich": "Therapie & Musik", "warum": "Musik als Heilmittel – du könntest damit arbeiten. Gerade für Kinder, ältere Menschen oder Menschen in Krisen sehr wirkungsvoll.", "ausbildungsweg": "Studium Musiktherapie (B.A.)", "kreativ_potenzial": "Eigene Praxis, Zusammenarbeit mit Kliniken, Schulen."},
        ],
    })
    process.set_json("favoriten", {
        "ausgewaehlt": ["Kunsttherapeutin", "Sozialpädagogin", "Kinderbuchautorin / Illustratorin", "Psychologiestudium + Coaching", "Tierärztin"]
    })
    process.current_step = "ergebnis"
    db.commit()

    response = redirect("/ergebnis")
    response.set_cookie(SESSION_COOKIE, signed_token, **cookie_kwargs())
    return response
