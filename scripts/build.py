#!/usr/bin/env python3
"""
Genera el perfil de GitHub estilo terminal:
  - assets/terminal.svg  -> ventana de terminal animada (neofetch + estado de repos)
  - README.md            -> reescribe la tabla entre <!--REPOS:START--> y <!--REPOS:END-->

Solo usa la librería estándar. Pensado para correr en GitHub Actions cada pocas horas.

Uso:
  GH_USER=tuusuario GITHUB_TOKEN=xxx python scripts/build.py
  python scripts/build.py --mock            # datos falsos, para probar sin red
  python scripts/build.py --mock --static   # sin animación (para previsualizar en PNG)
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────── CONFIGURA AQUÍ ───────────────────────────────
CONFIG = {
    "host": "madrid",                 # sale como  usuario@host
    "info": [                         # líneas fijas del "neofetch" (clave, valor)
        ("OS", "Ingeniería Informática @ UFV"),
        ("Uptime", "3.er año · delegado de curso"),
        ("Host", "Madrid, ES"),
        ("Kernel", "Python · TypeScript · Rust"),
        ("Shell", "zsh + Claude Code"),
        ("Hobbies", "batería · guitarra · espresso"),
        ("Hackathons", "BIP Erasmus+ (ganador) · IA for Good"),
    ],
    "repo_limit": 8,                  # cuántos repos enseñar
    "exclude": [],                    # repos a ocultar, p.ej. ["dotfiles"]
    "include_forks": False,
    # Umbrales de estado (días desde el último push)
    "active_days": 7,
    "recent_days": 30,
    "plan": "construyendo cosas con agentes de IA",   # línea final tipo ~/.plan
}

# Logo ASCII original (izquierda). Mantén ~18 columnas para que no se pise.
LOGO = r"""
 ███╗   ███╗
 ████╗ ████║
 ██╔████╔██║
 ██║╚██╔╝██║
 ██║ ╚═╝ ██║
 ╚═╝     ╚═╝
   ▄▄▄▄▄▄▄
  ▐ >_    ▌
  ▐       ▌
   ▀▀▀▀▀▀▀
""".strip("\n").splitlines()

# Paleta (tokyonight-ish)
C = {
    "bg": "#1a1b26", "bar": "#16161e", "fg": "#c0caf5", "dim": "#565f89",
    "blue": "#7aa2f7", "cyan": "#7dcfff", "green": "#9ece6a", "yellow": "#e0af68",
    "red": "#f7768e", "magenta": "#bb9af7", "orange": "#ff9e64",
}
# ──────────────────────────────────────────────────────────────────────────────


def api(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "profile-builder"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def graphql_contribs(user: str) -> int | None:
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        return None
    q = {"query": "query($u:String!){user(login:$u){contributionsCollection{"
                  "contributionCalendar{totalContributions}}}}", "variables": {"u": user}}
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(q).encode(),
                                 headers={"Authorization": f"Bearer {tok}",
                                          "User-Agent": "profile-builder"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        return d["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    except Exception:
        return None


def fetch(user: str):
    u = api(f"https://api.github.com/users/{user}")
    repos = api(f"https://api.github.com/users/{user}/repos?per_page=100&sort=pushed&type=owner")
    return u, repos, graphql_contribs(user)


def mock(user: str):
    now = datetime.now(timezone.utc)
    def ago(d): return (now.timestamp() - d * 86400)
    def iso(ts): return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
    data = [("paeg-wallet", "Rust", 0.2, 12, "Private omnichain agent wallet"),
            ("posiq", "TypeScript", 1.5, 7, "Hackathon UFV × reload."),
            ("club-tenis-mesa", "TypeScript", 4, 2, "Web del club"),
            ("agente-emails", "Python", 12, 5, "Clasificador de emails con Claude"),
            ("discord-bot", "Python", 25, 3, "Bot de puntos para la comunidad"),
            ("tareas-casa", "TypeScript", 45, 0, "Reparto rotativo de tareas"),
            ("ssoo-practicas", "C", 160, 1, "Prácticas de Sistemas Operativos"),
            ("old-stuff", "Java", 400, 0, None)]
    repos = [{"name": n, "language": l, "pushed_at": iso(ago(d)), "stargazers_count": s,
              "description": desc, "fork": False, "archived": n == "old-stuff",
              "html_url": f"https://github.com/{user}/{n}", "size": 500} for n, l, d, s, desc in data]
    u = {"login": user, "public_repos": len(repos), "followers": 42, "created_at": "2022-09-01T00:00:00Z"}
    return u, repos, 731


def days_since(iso: str) -> float:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def rel(d: float) -> str:
    if d < 1 / 24: return "hace un momento"
    if d < 1: return f"hace {int(d * 24)} h"
    if d < 30: return f"hace {int(d)} d"
    if d < 365:
        m = int(d / 30)
        return f"hace {m} mes" if m == 1 else f"hace {m} meses"
    a = int(d / 365)
    return f"hace {a} año" if a == 1 else f"hace {a} años"


def status(repo) -> tuple[str, str, str]:
    """-> (etiqueta, color, emoji)"""
    if repo.get("archived"):
        return "archived", C["red"], "🔴"
    d = days_since(repo["pushed_at"])
    if d <= CONFIG["active_days"]:
        return "active", C["green"], "🟢"
    if d <= CONFIG["recent_days"]:
        return "recent", C["yellow"], "🟡"
    return "idle", C["dim"], "⚪"


def pick_repos(user, repos):
    out = [r for r in repos
           if r["name"] not in CONFIG["exclude"]
           and r["name"].lower() != user.lower()
           and (CONFIG["include_forks"] or not r.get("fork"))]
    out.sort(key=lambda r: r["pushed_at"], reverse=True)
    return out[: CONFIG["repo_limit"]]


def top_langs(repos, n=4):
    w: dict[str, float] = {}
    for r in repos:
        if r.get("language") and not r.get("fork"):
            w[r["language"]] = w.get(r["language"], 0) + max(r.get("size", 1), 1) ** 0.5
    tot = sum(w.values()) or 1
    return [(k, v / tot) for k, v in sorted(w.items(), key=lambda kv: -kv[1])[:n]]


# ───────────────────────────────── SVG ─────────────────────────────────
FS = 14          # font-size
LH = 20          # line height
CW = 8.43        # ancho aprox. de un carácter monoespaciado a 14px
PAD = 22


def esc(s: str) -> str:
    return html.escape(s, quote=False)


class Term:
    def __init__(self, static: bool):
        self.static = static
        self.lines: list[str] = []
        self.t = 0.4            # reloj de la animación (segundos)

    def _appear(self, delay: float) -> str:
        if self.static:
            return ""
        return (f'<set attributeName="opacity" to="1" begin="{delay:.2f}s" fill="freeze"/>')

    def row(self, y: int, spans: list[tuple[str, str]], x0: float = PAD, step: float = 0.07):
        """Una línea de salida que aparece de golpe."""
        self.t += step
        op = "1" if self.static else "0"
        parts = "".join(f'<tspan fill="{c}">{esc(t)}</tspan>' for t, c in spans)
        self.lines.append(f'<text x="{x0}" y="{y}" opacity="{op}" xml:space="preserve">'
                          f'{parts}{self._appear(self.t)}</text>')

    def command(self, y: int, prompt: list[tuple[str, str]], cmd: str, pause: float = 0.5):
        """Prompt + comando que se 'teclea' con un clipPath animado."""
        self.t += pause
        plen = sum(len(t) for t, _ in prompt)
        x_cmd = PAD + plen * CW
        dur = max(0.25, len(cmd) * 0.055)
        cid = f"c{len(self.lines)}"
        op = "1" if self.static else "0"
        p = "".join(f'<tspan fill="{c}">{esc(t)}</tspan>' for t, c in prompt)
        self.lines.append(f'<text x="{PAD}" y="{y}" opacity="{op}" xml:space="preserve">{p}'
                          f'{self._appear(self.t)}</text>')
        if self.static:
            self.lines.append(f'<text x="{x_cmd}" y="{y}" fill="{C["fg"]}" xml:space="preserve">{esc(cmd)}</text>')
        else:
            w = len(cmd) * CW + 4
            self.lines.append(
                f'<clipPath id="{cid}"><rect x="{x_cmd}" y="{y - FS}" height="{LH}" width="0">'
                f'<animate attributeName="width" from="0" to="{w:.1f}" begin="{self.t:.2f}s" '
                f'dur="{dur:.2f}s" fill="freeze" calcMode="discrete" '
                f'values="{";".join(f"{i * CW:.1f}" for i in range(len(cmd) + 1))}"/></rect></clipPath>'
                f'<text x="{x_cmd}" y="{y}" fill="{C["fg"]}" clip-path="url(#{cid})" '
                f'xml:space="preserve">{esc(cmd)}</text>')
        self.t += dur + 0.25


def build_svg(user, u, repos, contribs, static=False) -> str:
    shown = pick_repos(user, repos)
    langs = top_langs(repos)
    stars = sum(r.get("stargazers_count", 0) for r in repos if not r.get("fork"))
    host = CONFIG["host"]
    prompt = [(f"{user}@{host}", C["green"]), (":", C["fg"]), ("~", C["blue"]), ("$ ", C["fg"])]

    T = Term(static)
    y = 58
    T.command(y, prompt, "neofetch", pause=0.2)
    y += LH + 6

    # ── neofetch: logo a la izquierda, info a la derecha
    info_x = PAD + 17 * CW
    header = f"{user}@{host}"
    info: list[list[tuple[str, str]]] = [
        [(header, C["blue"])],
        [("─" * len(header), C["dim"])],
    ]
    for k, v in CONFIG["info"]:
        info.append([(f"{k}: ", C["cyan"]), (v, C["fg"])])
    since = u.get("created_at", "")[:4]
    stats = f'{u.get("public_repos", 0)} repos · ★ {stars} · {u.get("followers", 0)} followers'
    info.append([("GitHub: ", C["cyan"]), (stats, C["fg"])])
    if contribs is not None:
        info.append([("Commits: ", C["cyan"]), (f"{contribs} contribuciones este año", C["fg"])])
    if since:
        info.append([("Desde: ", C["cyan"]), (since, C["fg"])])
    if langs:
        info.append([("Langs: ", C["cyan"]),
                     ("  ".join(f"{k} {p:.0%}" for k, p in langs), C["fg"])])

    rows = max(len(LOGO), len(info))
    logo_cols = [C["magenta"], C["magenta"], C["blue"], C["blue"], C["cyan"], C["cyan"],
                 C["green"], C["green"], C["green"], C["green"]]
    for i in range(rows):
        if i < len(LOGO):
            T.row(y, [(LOGO[i], logo_cols[i % len(logo_cols)])], step=0.0)
        if i < len(info):
            T.row(y, info[i], x0=info_x, step=0.06)
        y += LH
    # paleta de colores tipo neofetch
    y += 4
    T.t += 0.05
    blocks = [C[k] for k in ("red", "orange", "yellow", "green", "cyan", "blue", "magenta", "fg")]
    op = "1" if static else "0"
    rects = "".join(f'<rect x="{info_x + i * 26:.1f}" y="{y - 13}" width="24" height="14" rx="2" fill="{c}"/>'
                    for i, c in enumerate(blocks))
    T.lines.append(f'<g opacity="{op}">{rects}{T._appear(T.t)}</g>')
    y += LH + 14

    # ── estado de repos
    T.command(y, prompt, "repo-status --live", pause=0.4)
    y += LH + 4
    namew = max([len(r["name"]) for r in shown] + [10])
    langw = max([len(r.get("language") or "—") for r in shown] + [9]) + 2
    for r in shown:
        label, col, _ = status(r)
        d = days_since(r["pushed_at"])
        lang = r.get("language") or "—"
        T.row(y, [("● ", col), (r["name"].ljust(namew + 2), C["fg"]),
                  (f"{label:<9}", col), (f"{lang:<{langw}}", C["magenta"]),
                  (rel(d), C["dim"])], step=0.08)
        y += LH
    y += 4
    T.row(y, [("● active ", C["green"]), (f"<{CONFIG['active_days']}d   ", C["dim"]),
              ("● recent ", C["yellow"]), (f"<{CONFIG['recent_days']}d   ", C["dim"]),
              ("● idle   ", C["dim"]), ("● archived", C["red"])], step=0.1)
    y += LH + 14

    # ── ~/.plan
    T.command(y, prompt, "cat ~/.plan", pause=0.4)
    y += LH
    T.row(y, [(CONFIG["plan"], C["yellow"])], step=0.15)
    y += LH + 10

    # ── prompt final con cursor parpadeante
    T.t += 0.3
    T.row(y, prompt, step=0)
    cx = PAD + sum(len(t) for t, _ in prompt) * CW
    blink = "" if static else ('<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" '
                               f'dur="1s" begin="{T.t:.2f}s" repeatCount="indefinite"/>')
    T.lines.append(f'<rect x="{cx:.1f}" y="{y - FS + 2}" width="{CW:.1f}" height="{FS + 2}" '
                   f'fill="{C["fg"]}" opacity="{"1" if static else "0"}">{T._appear(T.t)}{blink}</rect>')
    y += 18

    W = 860
    H = y + 6
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Terminal de {esc(user)}">
<title>{esc(user)} — perfil (actualizado {ts})</title>
<style>text{{font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,Consolas,"Liberation Mono",monospace;font-size:{FS}px}}</style>
<rect width="{W}" height="{H}" rx="12" fill="{C["bg"]}"/>
<rect width="{W}" height="34" rx="12" fill="{C["bar"]}"/><rect y="22" width="{W}" height="12" fill="{C["bar"]}"/>
<circle cx="22" cy="17" r="6" fill="#ff5f57"/><circle cx="42" cy="17" r="6" fill="#febc2e"/><circle cx="62" cy="17" r="6" fill="#28c840"/>
<text x="{W / 2}" y="22" fill="{C["dim"]}" text-anchor="middle" style="font-size:12px">{esc(user)}@{esc(host)}: ~ — zsh — {ts}</text>
{chr(10).join(T.lines)}
</svg>'''


# ──────────────────────────────── README ────────────────────────────────
def build_table(user, repos) -> str:
    rows = ["| | Repo | Estado | Lenguaje | Último push | ★ |",
            "|:-:|:--|:--|:--|:--|--:|"]
    for r in pick_repos(user, repos):
        label, _, emoji = status(r)
        desc = f"<br><sub>{esc(r['description'])}</sub>" if r.get("description") else ""
        rows.append(f"| {emoji} | [**{r['name']}**]({r['html_url']}){desc} | `{label}` | "
                    f"{r.get('language') or '—'} | {rel(days_since(r['pushed_at']))} | "
                    f"{r.get('stargazers_count', 0)} |")
    return "\n".join(rows)


def patch_readme(table: str):
    p = ROOT / "README.md"
    txt = p.read_text(encoding="utf-8")
    new = re.sub(r"(<!--REPOS:START-->).*?(<!--REPOS:END-->)",
                 lambda m: f"{m.group(1)}\n{table}\n{m.group(2)}", txt, flags=re.S)
    if new != txt:
        p.write_text(new, encoding="utf-8")


def main():
    args = set(sys.argv[1:])
    user = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "tu-usuario"
    u, repos, contribs = mock(user) if "--mock" in args else fetch(user)
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "terminal.svg").write_text(
        build_svg(user, u, repos, contribs, static="--static" in args), encoding="utf-8")
    patch_readme(build_table(user, repos))
    print(f"OK · {user} · {len(repos)} repos")


if __name__ == "__main__":
    main()
