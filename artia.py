#!/usr/bin/env python3
"""
Cliente mínimo (só stdlib) pra API GraphQL do Artia (https://api.artia.com/graphql).
Usado pela skill /artia-apontar. Não guarda senha em disco — lê ARTIA_EMAIL /
ARTIA_PASSWORD do ambiente a cada login. Só o token JWT é cacheado (curta duração,
arquivo 0600) pra não logar de novo a cada chamada dentro da mesma sessão.

Subcomandos:
  login                                   autentica, cacheia token
  whoami                                  confirma token, mostra usuário(s) da organização
  projects  --account ID                  lista projetos do grupo de trabalho
  folders   --account ID [--page N]       lista pastas/projetos (paginado, 25/página)
  activities --folder ID [--account ID] [--mine] [--email E]
                                           lista atividades de uma pasta
  time-entries --account ID --activity ID [--folder ID] [--date YYYY-MM-DD]
                                           lista apontamentos (filtra data no cliente)
  create-entry --account ID --activity ID --date D --start HH:MM --duration H
               [--status ID] [--by EMAIL] [--kind normal|extra] [--obs TEXT]
               [--custom-field HASH=VALOR ...] [--yes]
                                           cria apontamento — sem --yes só mostra o payload (dry-run)
  raw --query 'graphql...'                escape hatch pra qualquer query/mutation da coleção

Todas as respostas saem em JSON no stdout (fácil de parsear depois).
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.artia.com/graphql"
TOKEN_CACHE = os.path.expanduser("~/.cache/artia/token.json")
DEFAULT_ORG = os.environ.get("ARTIA_ORG_ID", "1")


def esc(s):
    """Escapa string pra literal GraphQL inline (a coleção oficial usa valores
    inline, sem variables, então seguimos o mesmo padrão)."""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def gql(query, token=None, org_id=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["OrganizationId"] = str(org_id or DEFAULT_ORG)
    data = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code}: {e.read().decode(errors='replace')}\n")
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.stderr.write(f"Falha de rede: {e}\n")
        sys.exit(1)
    if body.get("errors"):
        sys.stderr.write("Erro GraphQL: " + json.dumps(body["errors"], ensure_ascii=False) + "\n")
        sys.exit(1)
    return body["data"]


def jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None


def load_cached_token():
    if not os.path.exists(TOKEN_CACHE):
        return None
    try:
        d = json.load(open(TOKEN_CACHE))
        if d.get("exp", 0) > time.time() + 60:
            return d["token"]
    except Exception:
        pass
    return None


def save_token(token):
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    with open(TOKEN_CACHE, "w") as f:
        json.dump({"token": token, "exp": jwt_exp(token) or (time.time() + 3000)}, f)
    os.chmod(TOKEN_CACHE, 0o600)


def do_login(email=None, password=None):
    email = email or os.environ.get("ARTIA_EMAIL")
    password = password or os.environ.get("ARTIA_PASSWORD")
    if not email or not password:
        sys.exit(
            "Faltam credenciais: exporte ARTIA_EMAIL e ARTIA_PASSWORD no ambiente "
            "(ou passe --email/--password)."
        )
    q = f'mutation{{ authenticationByEmail(email:"{esc(email)}", password:"{esc(password)}") {{ token }} }}'
    data = gql(q)
    token = data["authenticationByEmail"]["token"]
    save_token(token)
    return token


def get_token(args):
    token = load_cached_token()
    if token:
        return token
    token = do_login(getattr(args, "email", None), getattr(args, "password", None))
    return token


# ---- subcomandos ----

def cmd_login(args):
    token = do_login(args.email, args.password)
    exp = jwt_exp(token)
    print(json.dumps({"status": "OK", "cached_at": TOKEN_CACHE, "exp": exp}, ensure_ascii=False))


def cmd_whoami(args):
    token = get_token(args)
    q = "query{ listingOrganizationUsers{ id, userId, name, email, role, suspended } }"
    data = gql(q, token, args.org)
    users = data["listingOrganizationUsers"]
    if args.email:
        users = [u for u in users if u.get("email", "").lower() == args.email.lower()]
    print(json.dumps(users, ensure_ascii=False, indent=2))


def cmd_projects(args):
    token = get_token(args)
    q = f"query{{ listingProjects(accountId: {int(args.account)}) {{ id, accountId, status, name, costCenterId }} }}"
    data = gql(q, token, args.org)
    print(json.dumps(data["listingProjects"], ensure_ascii=False, indent=2))


def cmd_folders(args):
    token = get_token(args)
    page = f", page: {int(args.page)}" if args.page else ""
    q = f"""query{{ listingFolders(accountId: {int(args.account)}{page}) {{
        id, name, status, accountId, folderTypeName, estimatedStart, estimatedEnd
    }} }}"""
    data = gql(q, token, args.org)
    print(json.dumps(data["listingFolders"], ensure_ascii=False, indent=2))


def cmd_activities(args):
    token = get_token(args)
    acc = f"accountId: {int(args.account)}, " if args.account else ""
    q = f"""query{{ listingActivities({acc}folderId: {int(args.folder)}) {{
        id, uid, title, status, folderTypeName,
        estimatedStart, estimatedEnd, actualStart, actualEnd,
        responsible {{ id, name, email }}
    }} }}"""
    data = gql(q, token, args.org)
    acts = data["listingActivities"]
    if args.mine:
        email = (args.email or os.environ.get("ARTIA_EMAIL") or "").lower()
        acts = [a for a in acts if (a.get("responsible") or {}).get("email", "").lower() == email]
    print(json.dumps(acts, ensure_ascii=False, indent=2))


def cmd_time_entries(args):
    token = get_token(args)
    folder = f"folderId: {int(args.folder)}, " if args.folder else ""
    q = f"""query{{ listingTimeEntries(accountId: {int(args.account)}, {folder}activityId: {int(args.activity)}) {{
        id, accountId, folderId, activityId, dateAt, startTime, endTime, duration,
        observation, timeEntryStatusId, status, kindOfHours
    }} }}"""
    data = gql(q, token, args.org)
    entries = data["listingTimeEntries"]
    if args.date:
        entries = [e for e in entries if (e.get("dateAt") or "")[:10] == args.date]
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def cmd_create_entry(args):
    fields = [
        f"accountId: {int(args.account)}",
        f"activityId: {int(args.activity)}",
        f'dateAt: "{esc(args.date)}"',
        f'startTime: "{esc(args.start)}"',
        f"duration: {float(args.duration)}",
        f"timeEntryStatusId: {int(args.status)}",
        f'kindOfHours: "{esc(args.kind)}"',
    ]
    if args.by:
        fields.append(f'createdBy: "{esc(args.by)}"')
    if args.obs:
        fields.append(f'observation: "{esc(args.obs)}"')
    if args.custom_field:
        cfs = []
        for cf in args.custom_field:
            hash_field, _, value = cf.partition("=")
            cfs.append(f'{{ hashField: "{esc(hash_field)}", value: "{esc(value)}" }}')
        fields.append("customField: [" + ", ".join(cfs) + "]")

    q = f"""mutation{{ createTimeEntry({", ".join(fields)}) {{
        id, accountId, folderId, activityId, dateAt, startTime, endTime, duration,
        observation, timeEntryStatusId, kindOfHours
    }} }}"""

    if not args.yes:
        print(json.dumps({"dry_run": True, "would_send_query": q}, ensure_ascii=False, indent=2))
        print("\n-- nada foi criado. Rode de novo com --yes para confirmar. --", file=sys.stderr)
        return

    token = get_token(args)
    data = gql(q, token, args.org)
    print(json.dumps(data["createTimeEntry"], ensure_ascii=False, indent=2))


def cmd_raw(args):
    token = None if args.noauth else get_token(args)
    data = gql(args.query, token, args.org)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(description="Cliente CLI pra API GraphQL do Artia")
    p.add_argument("--org", default=DEFAULT_ORG, help="OrganizationId (header). Default: %(default)s")
    p.add_argument("--email", help="Override de ARTIA_EMAIL")
    p.add_argument("--password", help="Override de ARTIA_PASSWORD")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login").set_defaults(func=cmd_login)

    w = sub.add_parser("whoami")
    w.set_defaults(func=cmd_whoami)

    pr = sub.add_parser("projects")
    pr.add_argument("--account", required=True)
    pr.set_defaults(func=cmd_projects)

    f = sub.add_parser("folders")
    f.add_argument("--account", required=True)
    f.add_argument("--page", type=int)
    f.set_defaults(func=cmd_folders)

    a = sub.add_parser("activities")
    a.add_argument("--folder", required=True)
    a.add_argument("--account")
    a.add_argument("--mine", action="store_true")
    a.set_defaults(func=cmd_activities)

    t = sub.add_parser("time-entries")
    t.add_argument("--account", required=True)
    t.add_argument("--folder")
    t.add_argument("--activity", required=True)
    t.add_argument("--date", help="YYYY-MM-DD, filtra no cliente")
    t.set_defaults(func=cmd_time_entries)

    c = sub.add_parser("create-entry")
    c.add_argument("--account", required=True)
    c.add_argument("--activity", required=True)
    c.add_argument("--date", required=True, help="YYYY-MM-DD")
    c.add_argument("--start", required=True, help="HH:MM")
    c.add_argument("--duration", required=True, help="horas, ex: 1.5")
    c.add_argument("--status", required=True, help="timeEntryStatusId")
    c.add_argument("--by", help="email ou id de quem registrou (createdBy)")
    c.add_argument("--kind", default="normal", choices=["normal", "extra"])
    c.add_argument("--obs", default="", help="observação do apontamento")
    c.add_argument("--custom-field", action="append", help="HASH=VALOR, repetível")
    c.add_argument("--yes", action="store_true", help="sem isso, só mostra o payload (dry-run)")
    c.set_defaults(func=cmd_create_entry)

    r = sub.add_parser("raw")
    r.add_argument("--query", required=True, help="query/mutation GraphQL completa")
    r.add_argument("--noauth", action="store_true")
    r.set_defaults(func=cmd_raw)

    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
