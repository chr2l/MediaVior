// Relais MediaVior : relie le PC et le téléphone, comme WhatsApp Web.
//
// - Le PC ouvre une connexion (WebSocket) vers le relais et la garde ouverte.
// - Le téléphone s'y connecte aussi, après avoir scanné le QR code affiché par le PC.
// - Le relais ne fait que passer des petits messages chiffrés de l'un à l'autre : il ne peut
//   pas les lire (la clé est dans le QR code, jamais envoyée au relais), et les fichiers ne
//   passent jamais par lui (ils vont directement du PC au téléphone, en WebRTC).
//
// Une « paire » = un PC et ses téléphones = un Durable Object, qui garde seulement des
// empreintes (SHA-256) des codes d'accès. Les connexions en veille ne coûtent rien
// (« hibernation »). Le reste des fichiers (page du téléphone) est servi depuis public/.

import { DurableObject } from "cloudflare:workers";

const ID = /^[A-Za-z0-9_-]{22}$/; // identifiant de paire : 16 octets en base64url
const SECRET = /^[A-Za-z0-9_-]{43}$/; // code d'accès : 32 octets en base64url
const MAX_MESSAGE = 64 * 1024; // un message relayé fait quelques centaines d'octets
const MAX_PHONES = 8;
const INVITE_TTL = 10 * 60 * 1000; // un QR code sert une fois, pendant 10 minutes
const RATE = { pc: 600, tel: 120 }; // messages par minute et par connexion
const STUN = [{ urls: ["stun:stun.cloudflare.com:3478"] }];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const m = url.pathname.match(/^\/ws\/(pc|tel)\/([^/]+)$/);
    if (!m) return env.ASSETS.fetch(request);

    if (!ID.test(m[2])) return new Response("Paire inconnue", { status: 400 });
    // Sans WebSocket : seulement pour qu'un téléphone vérifie que son jumelage existe encore
    const probe = request.headers.get("Upgrade") !== "websocket";
    if (probe && m[1] !== "tel") return new Response("WebSocket attendu", { status: 426 });
    // Limite par adresse : empêche de créer des milliers de paires ou de tester des codes
    const ip = request.headers.get("CF-Connecting-IP") || "?";
    if (env.LIMITE_CONNEXIONS) {
      const { success } = await env.LIMITE_CONNEXIONS.limit({ key: ip });
      if (!success) return new Response("Trop de connexions, réessaie dans une minute", { status: 429 });
    }
    return env.PAIRE.get(env.PAIRE.idFromName(m[2])).fetch(request);
  },
};

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomToken(n = 32) {
  return b64url(crypto.getRandomValues(new Uint8Array(n)));
}

async function sha256(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Comparaison à temps constant (les deux sont des empreintes hexadécimales de même longueur)
function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export class Paire extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    // Le « ping » de maintien de connexion est répondu sans réveiller l'objet (gratuit)
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request) {
    const url = new URL(request.url);
    const role = url.pathname.split("/")[2];
    const key = url.searchParams.get("k") || "";
    const invite = url.searchParams.get("invite") || "";
    const store = this.ctx.storage;

    if (role === "pc") {
      if (!SECRET.test(key)) return new Response("Code invalide", { status: 403 });
      const h = await sha256(key);
      const known = await store.get("pc");
      if (!known) await store.put("pc", h); // première connexion : ce PC devient le propriétaire
      else if (!same(known, h)) return new Response("Code invalide", { status: 403 });
      // Un seul PC à la fois : l'ancienne connexion (coupée, relancée…) est remplacée
      for (const old of this.ctx.getWebSockets("pc")) old.close(4000, "remplacé");
      const [ws, response] = this.accept(["pc"], { r: "pc" });
      const phones = (await store.get("tels")) || {};
      this.send(ws, { t: "etat", tels: this.onlinePhones(), jumeles: Object.keys(phones).length });
      this.broadcastPhones({ t: "pc", en_ligne: true });
      return response;
    }

    // Téléphone : soit un code d'accès reçu au jumelage, soit l'invitation du QR code
    const phones = (await store.get("tels")) || {};
    let id = null;
    let token = null;
    if (SECRET.test(key)) {
      const h = await sha256(key);
      id = Object.keys(phones).find((p) => same(phones[p].h, h)) || null;
    } else if (SECRET.test(invite) && request.headers.get("Upgrade") === "websocket") {
      const inv = await store.get("invitation");
      if (inv && inv.exp > Date.now() && same(inv.h, await sha256(invite))) {
        if (Object.keys(phones).length >= MAX_PHONES) {
          return new Response("Trop de téléphones jumelés", { status: 409 });
        }
        await store.delete("invitation");
        id = randomToken(6);
        token = randomToken();
        phones[id] = { h: await sha256(token), depuis: Date.now() };
        await store.put("tels", phones);
      }
    }
    if (!id) return new Response("Jumelage inconnu ou expiré", { status: 403 });
    if (request.headers.get("Upgrade") !== "websocket") return new Response(null, { status: 204 });

    const [ws, response] = this.accept(["tel", "tel:" + id], { r: "tel", id });
    this.send(ws, { t: "bienvenue", id, ...(token ? { k: token } : {}) });
    this.send(ws, { t: "pc", en_ligne: this.ctx.getWebSockets("pc").length > 0 });
    this.sendPc({ t: "tel", id, en_ligne: true, nouveau: Boolean(token) });
    return response;
  }

  accept(tags, attachment) {
    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server, tags);
    server.serializeAttachment({ ...attachment, w: Date.now(), n: 0 });
    return [server, new Response(null, { status: 101, webSocket: client })];
  }

  send(ws, msg) {
    try {
      ws.send(JSON.stringify(msg));
    } catch (e) {
      /* connexion déjà fermée */
    }
  }

  sendPc(msg) {
    for (const ws of this.ctx.getWebSockets("pc")) this.send(ws, msg);
  }

  broadcastPhones(msg, tag = "tel") {
    for (const ws of this.ctx.getWebSockets(tag)) this.send(ws, msg);
  }

  onlinePhones() {
    return this.ctx.getWebSockets("tel").map((ws) => ws.deserializeAttachment().id);
  }

  async iceServers() {
    // Relais TURN de Cloudflare (facultatif) : seulement s'il est configuré, pour les réseaux
    // où le transfert direct est bloqué. Sinon, STUN seul (gratuit et illimité).
    const { TURN_KEY_ID: id, TURN_KEY_API_TOKEN: token } = this.env;
    if (!id || !token) return STUN;
    try {
      const res = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${id}/credentials/generate-ice-servers`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ ttl: 3600 }),
      });
      if (!res.ok) return STUN;
      const servers = (await res.json()).iceServers || [];
      // Le port 53 est bloqué par les navigateurs : on l'enlève pour ne pas attendre pour rien
      return servers.map((s) => ({ ...s, urls: [].concat(s.urls).filter((u) => !/:53\b/.test(u)) }));
    } catch (e) {
      return STUN;
    }
  }

  async webSocketMessage(ws, raw) {
    const me = ws.deserializeAttachment();
    if (typeof raw !== "string" || raw.length > MAX_MESSAGE) return ws.close(1009, "message trop gros");
    const now = Date.now();
    if (now - me.w > 60000) {
      me.w = now;
      me.n = 0;
    }
    me.n += 1;
    ws.serializeAttachment(me);
    if (me.n > RATE[me.r]) return ws.close(1008, "trop de messages");

    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (e) {
      return;
    }
    if (!msg || typeof msg !== "object") return;

    if (msg.t === "m" && typeof msg.d === "string") {
      // Message chiffré à transmettre tel quel
      if (me.r === "tel") this.sendPc({ t: "m", de: me.id, d: msg.d });
      else this.broadcastPhones({ t: "m", de: "pc", d: msg.d }, msg.a ? "tel:" + msg.a : "tel");
    } else if (msg.t === "ice" && me.r === "pc") {
      this.send(ws, { t: "ice", serveurs: await this.iceServers(), r: msg.r });
    } else if (msg.t === "invitation" && me.r === "pc" && /^[0-9a-f]{64}$/.test(msg.h || "")) {
      await this.ctx.storage.put("invitation", { h: msg.h, exp: now + INVITE_TTL });
    } else if (msg.t === "oublier" && me.r === "pc") {
      // « Oublier les téléphones » : plus aucun téléphone ne peut se reconnecter
      await this.ctx.storage.delete(["tels", "invitation"]);
      for (const t of this.ctx.getWebSockets("tel")) t.close(4001, "oublié");
      this.send(ws, { t: "etat", tels: [], jumeles: 0 });
    } else if (msg.t === "retirer" && me.r === "pc" && typeof msg.id === "string") {
      const phones = (await this.ctx.storage.get("tels")) || {};
      delete phones[msg.id];
      await this.ctx.storage.put("tels", phones);
      for (const t of this.ctx.getWebSockets("tel:" + msg.id)) t.close(4001, "oublié");
    }
  }

  async webSocketClose(ws) {
    const me = ws.deserializeAttachment();
    if (me.r === "pc") {
      if (this.ctx.getWebSockets("pc").every((s) => s === ws)) this.broadcastPhones({ t: "pc", en_ligne: false });
    } else {
      this.sendPc({ t: "tel", id: me.id, en_ligne: false });
    }
  }

  async webSocketError(ws) {
    await this.webSocketClose(ws);
  }
}
