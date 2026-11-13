#!/usr/bin/env python3
"""
Genera el perfil de GitHub como panel de estado:
  - assets/terminal.svg  -> ventana de terminal animada con el estado de cada repo
  - README.md            -> reescribe el bloque entre <!--REPOS:START--> y <!--REPOS:END-->

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
    "host": "github",                 # sale como  usuario@host
    "repo_limit": 12,                 # cuántos repos enseñar
    "exclude": [],                    # repos a ocultar, p.ej. ["dotfiles"]
    "include_forks": False,
    # Umbrales de estado (días desde el último push)
    "active_days": 7,
    "recent_days": 30,
}

# Paleta (tokyonight-ish)
C = {
    "bg": "#1a1b26", "bar": "#16161e", "fg": "#c0caf5", "dim": "#565f89", "line": "#292e42",
    "blue": "#7aa2f7", "cyan": "#7dcfff", "green": "#9ece6a", "yellow": "#e0af68",
    "red": "#f7768e", "magenta": "#bb9af7", "orange": "#ff9e64",
}

# Estados: clave -> (etiqueta, plural para el resumen, color, emoji, pulso en segundos o None)
STATES = {
    "active":   ("activo",    "Activos",    C["green"],  "🟢", 1.4),
    "recent":   ("reciente",  "Recientes",  C["yellow"], "🟡", 2.6),
    "idle":     ("en pausa",  "En pausa",   C["dim"],    "⚪", None),
    "archived": ("archivado", "Archivados", C["red"],    "🔴", None),
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
    data = [("api-gateway", "Rust", 0.2, 12, "Gateway de ejemplo"),
            ("web-app", "TypeScript", 1.5, 7, "Aplicación web de ejemplo"),
            ("landing", "TypeScript", 4, 2, None),
            ("data-pipeline", "Python", 12, 5, "Pipeline de datos de ejemplo"),
            ("bot", "Python", 25, 3, None),
            ("notebooks", "Jupyter Notebook", 45, 0, None),
            ("practicas-c", "C", 160, 1, None),
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


def status(repo) -> str:
    if repo.get("archived"):
        return "archived"
    d = days_since(repo["pushed_at"])
    if d <= CONFIG["active_days"]:
        return "active"
    if d <= CONFIG["recent_days"]:
        return "recent"
    return "idle"


def eligible(user, repos):
    out = [r for r in repos
           if r["name"] not in CONFIG["exclude"]
           and r["name"].lower() != user.lower()
           and (CONFIG["include_forks"] or not r.get("fork"))]
    out.sort(key=lambda r: r["pushed_at"], reverse=True)
    return out


def pick_repos(user, repos):
    return eligible(user, repos)[: CONFIG["repo_limit"]]


def counts(user, repos) -> dict[str, int]:
    c = {k: 0 for k in STATES}
    for r in eligible(user, repos):
        c[status(r)] += 1
    return c


def top_langs(repos, n=4):
    w: dict[str, float] = {}
    for r in repos:
        if r.get("language") and not r.get("fork"):
            w[r["language"]] = w.get(r["language"], 0) + max(r.get("size", 1), 1) ** 0.5
    tot = sum(w.values()) or 1
    return [(k, v / tot) for k, v in sorted(w.items(), key=lambda kv: -kv[1])[:n]]


# ───────────────────────────────── SVG ─────────────────────────────────
FS = 14          # font-size
LH = 22          # line height
CW = 8.43        # ancho aprox. de un carácter monoespaciado a 14px
PAD = 22
W = 860


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def text(x: float, y: float, spans: list[tuple[str, str]], anchor: str = "start",
         size: int | None = None, bold: bool = False) -> str:
    parts = "".join(f'<tspan fill="{c}">{esc(t)}</tspan>' for t, c in spans)
    attrs = "" if anchor == "start" else f' text-anchor="{anchor}"'
    style = []
    if size:
        style.append(f"font-size:{size}px")
    if bold:
        style.append("font-weight:700")
    if style:
        attrs += f' style="{";".join(style)}"'
    return f'<text x="{x:.1f}" y="{y}" xml:space="preserve"{attrs}>{parts}</text>'


def dot(cx: float, cy: float, key: str, static: bool) -> str:
    _, _, col, _, pulse = STATES[key]
    core = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{col}"/>'
    if not pulse or static:
        return core
    halo = (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{col}" opacity="0.5">'
            f'<animate attributeName="r" values="4.5;11" dur="{pulse}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0.5;0" dur="{pulse}s" repeatCount="indefinite"/>'
            f'</circle>')
    return halo + core


def hline(y: float) -> str:
    return f'<rect x="{PAD}" y="{y:.1f}" width="{W - 2 * PAD}" height="1" fill="{C["line"]}"/>'


class Term:
    def __init__(self, static: bool):
        self.static = static
        self.out: list[str] = []
        self.t = 0.4            # reloj de la animación (segundos)

    def add(self, inner: str, step: float = 0.07):
        """Un bloque que aparece de golpe en el instante actual."""
        self.t += step
        if self.static:
            self.out.append(f"<g>{inner}</g>")
        else:
            self.out.append(f'<g opacity="0">{inner}'
                            f'<set attributeName="opacity" to="1" begin="{self.t:.2f}s" fill="freeze"/></g>')

    def command(self, y: int, prompt: list[tuple[str, str]], cmd: str, pause: float = 0.5):
        """Prompt + comando que se 'teclea' con un clipPath animado."""
        self.add(text(PAD, y, prompt), step=pause)
        x_cmd = PAD + sum(len(t) for t, _ in prompt) * CW
        if self.static:
            self.out.append(text(x_cmd, y, [(cmd, C["fg"])]))
            return
        dur = max(0.25, len(cmd) * 0.055)
        cid = f"c{len(self.out)}"
        w = len(cmd) * CW + 4
        self.out.append(
            f'<clipPath id="{cid}"><rect x="{x_cmd:.1f}" y="{y - FS}" height="{LH}" width="0">'
            f'<animate attributeName="width" from="0" to="{w:.1f}" begin="{self.t:.2f}s" '
            f'dur="{dur:.2f}s" fill="freeze" calcMode="discrete" '
            f'values="{";".join(f"{i * CW:.1f}" for i in range(len(cmd) + 1))}"/></rect></clipPath>'
            f'<g clip-path="url(#{cid})">{text(x_cmd, y, [(cmd, C["fg"])])}</g>')
        self.t += dur + 0.25


def build_svg(user, u, repos, contribs, static=False) -> str:
    shown = pick_repos(user, repos)
    cnt = counts(user, repos)
    langs = top_langs(repos)
    stars = sum(r.get("stargazers_count", 0) for r in repos if not r.get("fork"))
    host = CONFIG["host"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = [(f"{user}@{host}", C["green"]), (":", C["fg"]), ("~", C["blue"]), ("$ ", C["fg"])]

    T = Term(static)
    y = 60
    T.command(y, prompt, "status --repos", pause=0.2)
    y += LH + 12

    # ── cabecera del panel
    T.add(text(PAD, y, [("PANEL DE ESTADO", C["blue"])], bold=True)
          + text(W - PAD, y, [("actualizado ", C["dim"]), (ts, C["fg"])], anchor="end", size=12)
          + hline(y + 10), step=0.1)
    y += LH + 14

    # ── contadores por estado
    x = PAD + 6
    parts = []
    for key, (_, plural, col, _, _) in STATES.items():
        parts.append(dot(x, y - 5, key, static))
        label = f"{plural} "
        num = str(cnt[key])
        parts.append(text(x + 12, y, [(label, C["fg"]), (num, col)]))
        x += 12 + (len(label) + len(num)) * CW + 34
    T.add("".join(parts), step=0.15)
    y += LH + 14

    # ── tabla de repos
    namew = max([len(r["name"]) for r in shown] + [10]) + 2
    statew = max(len(s[0]) for s in STATES.values()) + 2
    langw = max([len(r.get("language") or "—") for r in shown] + [9]) + 2
    pushw = 15
    x_name = PAD + 20
    head = (f'{"REPO".ljust(namew)}{"ESTADO".ljust(statew)}{"LENGUAJE".ljust(langw)}'
            f'{"ÚLTIMO PUSH".ljust(pushw)}')
    T.add(text(x_name, y, [(head, C["dim"])], size=12)
          + text(W - PAD, y, [("★", C["dim"])], anchor="end", size=12), step=0.1)
    y += 8
    T.add(hline(y), step=0.0)
    y += LH

    for r in shown:
        key = status(r)
        label, _, col, _, _ = STATES[key]
        lang = r.get("language") or "—"
        row = text(x_name, y, [(r["name"].ljust(namew), C["fg"]),
                               (label.ljust(statew), col),
                               (lang.ljust(langw), C["magenta"]),
                               (rel(days_since(r["pushed_at"])).ljust(pushw), C["dim"])])
        row += text(W - PAD, y, [(str(r.get("stargazers_count", 0)), C["yellow"])], anchor="end")
        T.add(dot(PAD + 6, y - 5, key, static) + row, step=0.08)
        y += LH
    hidden = len(eligible(user, repos)) - len(shown)
    if hidden > 0:
        T.add(text(x_name, y, [(f"… y {hidden} más", C["dim"])], size=12), step=0.05)
        y += LH
    y += 2
    T.add(hline(y - 12), step=0.0)
    y += 12

    # ── resumen
    stats = [("repos ", C["dim"]), (str(u.get("public_repos", 0)), C["fg"]),
             ("   ★ ", C["dim"]), (str(stars), C["fg"])]
    if contribs is not None:
        stats += [("   contribuciones este año ", C["dim"]), (str(contribs), C["fg"])]
    T.add(text(PAD, y, stats), step=0.1)
    y += LH
    if langs:
        lspans = [("lenguajes ", C["dim"])]
        for k, p in langs:
            lspans += [(k, C["cyan"]), (f" {p:.0%}   ", C["fg"])]
        T.add(text(PAD, y, lspans), step=0.1)
        y += LH
    legend = (f'activo <{CONFIG["active_days"]}d · reciente <{CONFIG["recent_days"]}d · '
              f'en pausa >{CONFIG["recent_days"]}d · archivado')
    T.add(text(PAD, y, [(legend, C["dim"])], size=12), step=0.1)
    y += LH + 12

    # ── prompt final con cursor parpadeante
    T.add(text(PAD, y, prompt), step=0.3)
    cx = PAD + sum(len(t) for t, _ in prompt) * CW
    blink = "" if static else ('<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" '
                               f'dur="1s" begin="{T.t:.2f}s" repeatCount="indefinite"/>')
    T.add(f'<rect x="{cx:.1f}" y="{y - FS + 2}" width="{CW:.1f}" height="{FS + 2}" '
          f'fill="{C["fg"]}">{blink}</rect>', step=0.0)
    y += 18

    H = y + 6
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Panel de estado de los repos de {esc(user)}">
<title>{esc(user)} — estado de repos (actualizado {ts})</title>
<style>text{{font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,Consolas,"Liberation Mono",monospace;font-size:{FS}px}}</style>
<rect width="{W}" height="{H}" rx="12" fill="{C["bg"]}"/>
<rect width="{W}" height="34" rx="12" fill="{C["bar"]}"/><rect y="22" width="{W}" height="12" fill="{C["bar"]}"/>
<circle cx="22" cy="17" r="6" fill="#ff5f57"/><circle cx="42" cy="17" r="6" fill="#febc2e"/><circle cx="62" cy="17" r="6" fill="#28c840"/>
<text x="{W / 2}" y="22" fill="{C["dim"]}" text-anchor="middle" style="font-size:12px">{esc(user)}@{esc(host)}: ~ — status</text>
{chr(10).join(T.out)}
</svg>'''


# ──────────────────────────────── README ────────────────────────────────
def build_table(user, repos) -> str:
    cnt = counts(user, repos)
    summary = " · ".join(f"{emoji} **{cnt[k]}** {plural.lower()}"
                         for k, (_, plural, _, emoji, _) in STATES.items())
    rows = [summary, "",
            "| | Repo | Estado | Lenguaje | Último push | ★ |",
            "|:-:|:--|:--|:--|:--|--:|"]
    for r in pick_repos(user, repos):
        key = status(r)
        label, _, _, emoji, _ = STATES[key]
        rows.append(f"| {emoji} | [**{r['name']}**]({r['html_url']}) | `{label}` | "
                    f"{r.get('language') or '—'} | {rel(days_since(r['pushed_at']))} | "
                    f"{r.get('stargazers_count', 0)} |")
    rows += ["", f"<sub>🟢 push en los últimos {CONFIG['active_days']} días · "
                 f"🟡 en los últimos {CONFIG['recent_days']} · ⚪ más antiguo · 🔴 archivado</sub>"]
    return "\n".join(rows)


def patch_readme(table: str):
    p = ROOT / "README.md"
    txt = p.read_text(encoding="utf-8")
    new = re.sub(r"(<!--REPOS:START-->).*?(<!--REPOS:END-->)",
                 lambda m: f"{m.group(1)}\n{table}\n{m.group(2)}", txt, flags=re.S)
    if new != txt:
        p.write_text(new, encoding="utf-8", newline="\n")


def main():
    args = set(sys.argv[1:])
    user = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "tu-usuario"
    u, repos, contribs = mock(user) if "--mock" in args else fetch(user)
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "terminal.svg").write_text(
        build_svg(user, u, repos, contribs, static="--static" in args), encoding="utf-8", newline="\n")
    patch_readme(build_table(user, repos))
    print(f"OK · {user} · {len(repos)} repos")


if __name__ == "__main__":
    main()
