"""Jumelage avec le téléphone, comme WhatsApp Web (version PC seulement).

Le PC garde une connexion ouverte vers un petit relais gratuit (Cloudflare Worker, dossier
relais/). Le téléphone scanne une fois un QR code, puis il peut :
  - envoyer un lien au PC (« télécharge ça »), depuis n'importe où, en 4G comme en wifi ;
  - suivre les téléchargements et récupérer les fichiers.

Confidentialité : tous les messages sont chiffrés (AES-GCM) avec une clé qui ne passe que par
le QR code. Le relais transmet des données illisibles. Les fichiers ne passent jamais par lui :
ils vont directement du PC au téléphone (WebRTC). Si la connexion directe est impossible sur le
réseau, le fichier reste simplement sur le PC.

Réglages : ~/.mediavior/jumelage.json (ne pas partager : il permet de se faire passer pour ce PC).
Variable MEDIAVIOR_RELAIS : adresse d'un autre relais (par exemple le sien).
"""
import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import secrets
import ssl
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

RELAIS = os.environ.get("MEDIAVIOR_RELAIS", "https://mediavior-tel.elie.place").rstrip("/")
CONFIG = Path.home() / ".mediavior" / "jumelage.json"
INVITE_TTL = 10 * 60  # un QR code sert une fois, pendant 10 minutes (comme côté relais)
CHUNK = 60 * 1024  # taille d'un morceau de fichier sur la connexion directe
MAX_ITEMS = 30  # fichiers récents montrés au téléphone
DEFAULT_ICE = [{"urls": ["stun:stun.cloudflare.com:3478"]}]

router = APIRouter()
web = None  # le module app/main.py, donné par setup()

_cfg: dict = {}
_ws = None
_wake = asyncio.Event()
_invite_until = 0.0
_online: set = set()  # téléphones connectés en ce moment
_status = {"connecte": False, "erreur": None, "nouveau": 0.0}
_answers: dict = {}  # réponses WebRTC attendues, par numéro de transfert
_ice_waiting: dict = {}
_transfers: dict = {}
_last_state: Optional[str] = None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------------------
# Réglages du jumelage
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        if all(isinstance(cfg.get(k), str) for k in ("p", "s", "c")):
            return cfg
    except (OSError, ValueError):
        pass
    return {}


def _save() -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(_cfg), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(CONFIG)


def _new_identity() -> None:
    """Nouvelle paire : identifiant, code d'accès du PC et clé de chiffrement."""
    _cfg.clear()
    _cfg.update(p=_b64(secrets.token_bytes(16)), s=_b64(secrets.token_bytes(32)),
                c=_b64(secrets.token_bytes(32)), tels=0)
    _save()


def _available() -> Optional[str]:
    """None si tout est prêt, sinon la raison."""
    try:
        import cryptography  # noqa: F401
        import segno  # noqa: F401
        import websockets  # noqa: F401
    except ImportError:
        return "Il manque un module : relance MediaVior pour finir sa mise à jour."
    return None


def _should_run() -> bool:
    return bool(_cfg) and (_cfg.get("tels", 0) > 0 or time.time() < _invite_until)


# ---------------------------------------------------------------------------
# Chiffrement
# ---------------------------------------------------------------------------

def _seal(obj: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = secrets.token_bytes(12)
    data = json.dumps(obj, ensure_ascii=False).encode()
    return _b64(iv + AESGCM(_unb64(_cfg["c"])).encrypt(iv, data, b"pc>tel"))


def _unseal(text: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = _unb64(text)
    return json.loads(AESGCM(_unb64(_cfg["c"])).decrypt(raw[:12], raw[12:], b"tel>pc"))


async def _send_raw(msg: dict) -> None:
    if _ws is not None:
        try:
            await _ws.send(json.dumps(msg))
        except Exception:
            pass


async def _send(obj: dict, phone: Optional[str] = None) -> None:
    msg = {"t": "m", "d": _seal(obj)}
    if phone:
        msg["a"] = phone
    await _send_raw(msg)


# ---------------------------------------------------------------------------
# Connexion au relais
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # certificats à jour, même là où le système n'en fournit pas (Mac)
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


async def _loop() -> None:
    global _ws
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    delay = 1
    while True:
        if not _should_run():
            _wake.clear()
            await _wake.wait()
            continue
        url = RELAIS.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url = f"{url}/ws/pc/{_cfg['p']}?k={_cfg['s']}"
        try:
            async with connect(url, ssl=_ssl_context() if url.startswith("wss") else None,
                               open_timeout=15, ping_interval=25, ping_timeout=20,
                               max_size=1 << 16, user_agent_header="MediaVior") as ws:
                _ws = ws
                _status.update(connecte=True, erreur=None)
                delay = 1
                if time.time() < _invite_until and _cfg.get("invite_h"):
                    await _send_raw({"t": "invitation", "h": _cfg["invite_h"]})
                while _should_run():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        await _on_relay(raw)
                    except Exception as exc:  # un message abîmé ne doit pas couper la connexion
                        print(f"Jumelage : message ignoré ({exc})")
        except asyncio.CancelledError:
            raise
        except InvalidStatus as exc:
            code = exc.response.status_code
            _status["erreur"] = "Relais saturé, nouvel essai bientôt." if code == 429 else f"Relais : erreur {code}."
            if code == 403:  # le relais ne reconnaît plus ce PC : on repart de zéro
                _new_identity()
        except Exception:
            _status["erreur"] = "Pas de connexion au relais (Internet coupé ?)."
        finally:
            _ws = None
            _online.clear()
            _status["connecte"] = False
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


async def _on_relay(raw) -> None:
    global _last_state
    msg = json.loads(raw)
    t = msg.get("t")
    if t == "etat":
        _online.clear()
        _online.update(msg.get("tels") or [])
        _set_phones(int(msg.get("jumeles") or 0))
    elif t == "tel":
        if msg.get("en_ligne"):
            _online.add(msg["id"])
            if msg.get("nouveau"):
                _set_phones(_cfg.get("tels", 0) + 1)
                _status["nouveau"] = time.time()
                _cfg.pop("invite_h", None)
                _save()
            _last_state = None  # renvoyer l'état au nouveau venu
        else:
            _online.discard(msg.get("id"))
    elif t == "ice":
        fut = _ice_waiting.pop(msg.get("r"), None)
        if fut and not fut.done():
            fut.set_result(msg.get("serveurs") or DEFAULT_ICE)
    elif t == "m":
        phone = msg.get("de")
        try:
            data = _unseal(msg["d"])
        except Exception:
            return  # pas chiffré avec notre clé : ignoré
        await _on_phone(phone, data)


def _set_phones(n: int) -> None:
    if _cfg.get("tels") != n:
        _cfg["tels"] = n
        _save()


async def _on_phone(phone: str, msg: dict) -> None:
    t = msg.get("t")
    if t == "bonjour":
        await _send(_snapshot(), phone)
    elif t == "dl":
        await _start_download(phone, msg)
    elif t == "get" and isinstance(msg.get("tid"), str):
        if len(_transfers) >= 2:
            await _send({"t": "erreur", "tid": msg["tid"], "texte": "Le PC envoie déjà des fichiers, réessaie dans un instant."}, phone)
        else:
            task = asyncio.create_task(_send_file(phone, str(msg.get("id")), msg["tid"]))
            _transfers[msg["tid"]] = task
            task.add_done_callback(lambda _t, tid=msg["tid"]: _transfers.pop(tid, None))
    elif t == "reponse":
        fut = _answers.get(msg.get("tid"))
        if fut and not fut.done() and isinstance(msg.get("sdp"), str):
            fut.set_result(msg["sdp"])


async def _start_download(phone: str, msg: dict) -> None:
    mode = "audio" if msg.get("mode") == "audio" else "video"
    try:
        req = web.DownloadRequest(
            url=str(msg.get("url") or "")[:2000], mode=mode,
            container="mp3" if mode == "audio" else "mp4",
            audio_quality="320" if mode == "audio" else None,
        )
        await web.start_download(req)
        await _send({"t": "recu"}, phone)
    except HTTPException as exc:
        await _send({"t": "erreur", "texte": str(exc.detail)}, phone)
    except Exception:
        await _send({"t": "erreur", "texte": "Lien refusé par le PC."}, phone)


# ---------------------------------------------------------------------------
# État envoyé aux téléphones (téléchargements en cours, fichiers récents)
# ---------------------------------------------------------------------------

def _snapshot() -> dict:
    jobs = []
    for j in list(web.JOBS.values())[-10:]:
        if j["status"] == "done" and time.time() - (j.get("finished") or 0) > 300:
            continue
        p = j.get("_payload") or {}
        jobs.append({"id": j["id"], "title": str(j.get("title") or "")[:200], "status": j["status"],
                     "progress": j.get("progress") or 0, "error": j.get("error"),
                     "mode": p.get("mode") if j["kind"] == "download" else "archive"})
    items = []
    try:
        dirs = [d for d in web.ITEMS_DIR.iterdir() if d.is_dir() and web.ITEM_ID.match(d.name)]
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs[: MAX_ITEMS * 2]:
            item = web._item_view(d)
            if item:
                items.append({k: item.get(k) for k in ("id", "title", "filename", "ext", "size", "mode")})
            if len(items) >= MAX_ITEMS:
                break
    except OSError:
        pass
    return {"t": "etat", "taches": jobs, "fichiers": items}


async def _pusher() -> None:
    """Tant qu'un téléphone regarde, lui envoie les changements (au plus une fois par seconde)."""
    global _last_state
    while True:
        await asyncio.sleep(1)
        if not _online or _ws is None:
            continue
        state = await asyncio.get_running_loop().run_in_executor(None, _snapshot)
        text = json.dumps(state, sort_keys=True)
        if text != _last_state:
            _last_state = text
            await _send(state)


# ---------------------------------------------------------------------------
# Envoi d'un fichier au téléphone : connexion directe WebRTC
# ---------------------------------------------------------------------------

async def _ice_servers() -> list:
    """Serveurs pour établir la connexion directe (STUN, et TURN si le relais en a un)."""
    if _ws is None:
        return DEFAULT_ICE
    r = secrets.token_hex(6)
    fut = asyncio.get_running_loop().create_future()
    _ice_waiting[r] = fut
    await _send_raw({"t": "ice", "r": r})
    try:
        return await asyncio.wait_for(fut, timeout=5)
    except asyncio.TimeoutError:
        return DEFAULT_ICE
    finally:
        _ice_waiting.pop(r, None)


async def _send_file(phone: str, item_id: str, tid: str) -> None:
    async def fail(text: str) -> None:
        await _send({"t": "erreur", "tid": tid, "texte": text}, phone)

    try:
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
    except ImportError:
        return await fail("Le transfert vers le téléphone n'est pas encore installé sur ce PC : relance MediaVior.")
    try:
        media = web._media_file(web._item_dir(item_id))
    except HTTPException:
        media = None
    if not media:
        return await fail("Fichier introuvable sur le PC.")

    ice = await _ice_servers()
    servers = []
    for s in ice:
        urls = [u for u in ([s["urls"]] if isinstance(s.get("urls"), str) else s.get("urls") or [])
                if u.split(":", 1)[0] in ("stun", "turn", "turns")]
        if urls:
            servers.append(RTCIceServer(urls=urls, username=s.get("username"), credential=s.get("credential")))
    pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
    opened = asyncio.Event()
    drained = asyncio.Event()
    channel = pc.createDataChannel("fichier", ordered=True)
    channel.bufferedAmountLowThreshold = 1 << 20
    channel.on("open", opened.set)
    channel.on("bufferedamountlow", drained.set)
    answer = asyncio.get_running_loop().create_future()
    _answers[tid] = answer
    try:
        await pc.setLocalDescription(await pc.createOffer())
        await _send({"t": "offre", "tid": tid, "sdp": pc.localDescription.sdp, "ice": ice}, phone)
        sdp = await asyncio.wait_for(answer, timeout=30)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))
        await asyncio.wait_for(opened.wait(), timeout=25)

        size = media.stat().st_size
        kind = mimetypes.guess_type(media.name)[0] or "application/octet-stream"
        channel.send(json.dumps({"t": "debut", "nom": media.name, "taille": size, "type": kind}))
        with media.open("rb") as f:
            while chunk := f.read(CHUNK):
                if channel.readyState != "open":
                    raise ConnectionError("canal fermé")
                if channel.bufferedAmount > 4 << 20:
                    drained.clear()
                    await asyncio.wait_for(drained.wait(), timeout=60)
                channel.send(chunk)
        channel.send(json.dumps({"t": "fin"}))
        for _ in range(600):  # laisse partir la fin du fichier avant de fermer
            if channel.bufferedAmount == 0 or channel.readyState != "open":
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(2)
    except asyncio.TimeoutError:
        await fail("Connexion directe impossible sur ce réseau : le fichier reste sur ton PC.")
    except Exception:
        await fail("Le transfert s'est coupé. Réessaie.")
    finally:
        _answers.pop(tid, None)
        await pc.close()


# ---------------------------------------------------------------------------
# API pour la fenêtre « Téléphone » de l'appli PC
# ---------------------------------------------------------------------------

def _public_status() -> dict:
    return {
        "dispo": _available() is None,
        "raison": _available(),
        "relais": RELAIS,
        "connecte": _status["connecte"],
        "erreur": _status["erreur"],
        "jumeles": _cfg.get("tels", 0),
        "en_ligne": len(_online),
        "nouveau": _status["nouveau"],
    }


@router.get("/api/local/telephone")
async def phone_status():
    return _public_status()


@router.post("/api/local/telephone/qr")
async def phone_qr():
    """Nouveau QR code de jumelage (valable 10 minutes, une seule fois)."""
    global _invite_until
    reason = _available()
    if reason:
        raise HTTPException(status_code=503, detail=reason)
    import segno
    if not _cfg:
        _new_identity()
    invite = _b64(secrets.token_bytes(32))
    _cfg["invite_h"] = hashlib.sha256(invite.encode()).hexdigest()
    _save()
    _invite_until = time.time() + INVITE_TTL
    _wake.set()
    await _send_raw({"t": "invitation", "h": _cfg["invite_h"]})
    link = f"{RELAIS}/#j={_cfg['p']}.{invite}.{_cfg['c']}"
    qr = segno.make(link, error="m")
    return {**_public_status(), "lien": link, "qr": qr.svg_data_uri(scale=5, border=3),
            "expire": _invite_until}


@router.post("/api/local/telephone/oublier")
async def phone_forget():
    """Oublie tous les téléphones et change de clé : les anciens QR codes ne marchent plus."""
    global _invite_until
    await _send_raw({"t": "oublier"})
    _invite_until = 0
    if _ws is not None:
        await _ws.close()
    _new_identity()
    return _public_status()


def setup(main_module) -> list:
    """Appelé par app/main.py au démarrage de la version PC. Renvoie les tâches lancées."""
    global web
    web = main_module
    _cfg.update(_load())
    if _available():
        return []
    _wake.set()
    return [asyncio.create_task(_loop()), asyncio.create_task(_pusher())]
