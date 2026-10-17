#!/bin/bash
# Nightly security check for dough-flow-db (run by LaunchAgent com.billyzou.dough-flow-security).
#
# Alerts when something private reaches the public GitHub repo, or when a service
# becomes reachable from the internet. LAN-only hardening (passwords, file
# permissions, outdated packages) is logged as "note" without alerting. Private inputs (denylist, accepted findings,
# logs) live outside the repo in ~/.dough-flow-security so they can't be committed.
#
# Usage: scripts/security_check.sh            # run all checks, notify on problems
#        scripts/security_check.sh --accept   # also accept current secret-scan findings as known
#
# Exit code: 0 = all clear, 1 = at least one FAIL or WARN (notes don't count).

set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$HOME/.dough-flow-security"
GITLEAKS_IMAGE="zricethezav/gitleaks:v8.24.3"
# Ports the stack is allowed to publish on all interfaces. A new one appearing is flagged.
EXPECTED_LAN_PORTS="5433 8080 8501"
# Ports that must never be reachable from the internet.
INTERNET_PORTS="5433 8080 8501"

mkdir -p "$STATE"
chmod 700 "$STATE"
touch "$STATE/denylist.txt" "$STATE/gitleaksignore"
cd "$REPO" || exit 1

problems=()
ok()   { echo "  ok    $1"; }
warn() { echo "  WARN  $1"; problems+=("$1"); }
fail() { echo "  FAIL  $1"; problems+=("$1"); }
note() { echo "  note  $1"; }
compose() { docker compose -f "$REPO/docker-compose.yml" "$@" 2> >(grep -v 'attribute `version` is obsolete' >&2); }

echo "=== dough-flow security check $(date '+%Y-%m-%d %H:%M:%S')"

# ─── 1. Secrets and private info in git history ──────────────────────────────
echo "[1] Secret scan of full git history (all branches)"
# Build a gitleaks config: default rules + your real .env secret values + denylist terms.
# Rule ids are hashes so the report never names the private term itself.
/usr/bin/python3 - "$REPO/.env" "$STATE/denylist.txt" > "$STATE/gitleaks.toml" <<'PY'
import hashlib, re, sys
env_path, deny_path = sys.argv[1], sys.argv[2]
terms = []
try:
    for line in open(env_path):
        k, _, v = line.strip().partition("=")
        v = v.strip().strip("'\"")
        if re.search(r"PASSWORD|SECRET|TOKEN|KEY|CLIENT_ID", k) and len(v) >= 8:
            terms.append(("env", re.escape(v)))
except FileNotFoundError:
    pass
for line in open(deny_path):
    line = line.strip()
    if line and not line.startswith("#"):
        terms.append(("private", line))  # denylist lines are regexes
print("[extend]\nuseDefault = true\n")
for kind, rx in terms:
    rid = f"{kind}-{hashlib.sha256(rx.encode()).hexdigest()[:8]}"
    print(f"[[rules]]\nid = \"{rid}\"\ndescription = \"{kind} value\"\nregex = '''(?i){rx}'''\n")
PY
chmod 600 "$STATE/gitleaks.toml"

run_gitleaks() {  # $1 = mode (git|stdin), rest = extra args
    local mode=$1; shift
    docker run --rm -i -v "$REPO:/repo:ro" -v "$STATE:/state" "$GITLEAKS_IMAGE" \
        "$mode" "$@" --config /state/gitleaks.toml --gitleaks-ignore-path /state/gitleaksignore \
        --redact --no-banner --log-level error --exit-code 3
}
run_gitleaks git /repo --report-path /state/gitleaks-history.json; rc=$?
if [ $rc -eq 0 ]; then
    ok "no new secrets or private terms in any commit"
elif [ $rc -eq 3 ]; then
    n=$(/usr/bin/python3 -c "import json;print(len(json.load(open('$STATE/gitleaks-history.json'))))")
    fail "$n new secret/private-info finding(s) in git history (see $STATE/gitleaks-history.json)"
    /usr/bin/python3 -c "
import json
for f in json.load(open('$STATE/gitleaks-history.json')):
    print(f\"        {f['RuleID']:<24} {f['Commit'][:7]} {f['File']}:{f['StartLine']}\")"
    if [ "${1:-}" = "--accept" ]; then
        /usr/bin/python3 -c "
import json
for f in json.load(open('$STATE/gitleaks-history.json')): print(f['Fingerprint'])" >> "$STATE/gitleaksignore"
        echo "        accepted into $STATE/gitleaksignore"
    fi
else
    fail "gitleaks history scan did not run (exit $rc)"
fi

# Uncommitted changes, so a leak is caught before it's committed.
git -C "$REPO" diff HEAD | run_gitleaks stdin > /dev/null; rc=$?
if [ $rc -eq 0 ]; then ok "no secrets in uncommitted changes"
elif [ $rc -eq 3 ]; then fail "secret or private term in uncommitted changes (git diff HEAD)"
else fail "gitleaks diff scan did not run (exit $rc)"; fi

# ─── 2. Files that must never be tracked ─────────────────────────────────────
echo "[2] Tracked-file policy"
bad=$(git ls-files | grep -E '(^|/)\.env$|\.(dump|pgdump|backup|sql\.gz|csv\.bak)$|^backups/|^data/|^analyses/|^CLAUDE\.md$|^scripts/(categorize_csv_backfill|delete_transactions|explore_plaid_response)\.py$')
[ -z "$bad" ] && ok "no .env, dumps, backups or local-only scripts tracked" || fail "private files tracked: $(echo $bad)"

for nb in $(git ls-files '*.ipynb'); do
    if /usr/bin/python3 -c "import json,sys;sys.exit(any(c.get('outputs') for c in json.load(open('$nb'))['cells']))"; then
        ok "$nb has no saved outputs"
    else
        fail "$nb has saved cell outputs (can contain tokens/balances); clear them"
    fi
done

# ─── 3. GitHub repo settings ─────────────────────────────────────────────────
echo "[3] GitHub repo settings"
slug=$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')
if gh_json=$(gh api "repos/$slug" 2>/dev/null); then
    for feat in secret_scanning secret_scanning_push_protection; do
        s=$(echo "$gh_json" | /usr/bin/python3 -c "import json,sys;print(json.load(sys.stdin)['security_and_analysis']['$feat']['status'])" 2>/dev/null)
        [ "$s" = "enabled" ] && ok "GitHub $feat enabled" || fail "GitHub $feat is ${s:-unknown} (free for public repos)"
    done
else
    warn "could not query GitHub (gh not logged in or offline)"
fi

# ─── 4. Local file permissions ───────────────────────────────────────────────
echo "[4] File permissions"
for f in "$REPO/.env" "$REPO"/backups/*; do
    [ -e "$f" ] || continue
    p=$(stat -f %Lp "$f")
    [ "${p:1}" = "00" ] && ok "${f#$REPO/} is $p" || note "${f#$REPO/} is $p, readable by other users (want 600: chmod 600 '$f')"
done

# ─── 5. Running stack ────────────────────────────────────────────────────────
echo "[5] Running stack"
if ! docker info > /dev/null 2>&1; then
    note "Docker isn't running; stack checks skipped"
else
    # Ports published on all interfaces (reachable by every device on the LAN)
    lan_ports=$(docker ps --format '{{.Ports}}' | grep -oE '0\.0\.0\.0:[0-9]+' | cut -d: -f2 | sort -un | tr '\n' ' ')
    unexpected=""
    for p in $lan_ports; do [[ " $EXPECTED_LAN_PORTS " == *" $p "* ]] || unexpected+="$p "; done
    [ -z "$unexpected" ] && ok "LAN-exposed ports are the expected ones ($lan_ports)" || note "new port(s) exposed to the LAN: $unexpected"

    # Postgres must require a password for network logins (trust on loopback inside the container is the image default)
    trust=$(compose exec -T postgres sh -c 'grep -E "^host" "$PGDATA/pg_hba.conf" | grep -w trust | grep -vE "127\.0\.0\.1/32|::1/128"' 2>/dev/null)
    [ -z "$trust" ] && ok "Postgres requires passwords for network logins" || note "Postgres pg_hba.conf has 'trust' for network logins"

    # Logins whose passwords are published in this public repo. Tested from another
    # container so it goes over the network like a LAN client would.
    if compose exec -T streamlit python -c "
import psycopg2; psycopg2.connect(host='postgres', user='airflow', password='airflow', dbname='airflow_meta', connect_timeout=5)" > /dev/null 2>&1; then
        note "Postgres role 'airflow' still uses the password 'airflow' from the public repo (port 5433 is open to the LAN)"
    else
        ok "Postgres role 'airflow' doesn't use the public default password"
    fi
    weak=$(compose exec -T airflow-webserver python -c "
import os
from sqlalchemy import create_engine, text
from werkzeug.security import check_password_hash
e = create_engine(os.environ['AIRFLOW__DATABASE__SQL_ALCHEMY_CONN'])
with e.connect() as c:
    rows = c.execute(text('select username, password from ab_user')).fetchall()
print(' '.join(u for u, p in rows if any(check_password_hash(p, g) for g in (u, 'admin', 'password', 'airflow'))))
" 2>/dev/null)
    if [ $? -ne 0 ]; then note "could not check Airflow UI passwords"
    elif [ -z "$weak" ]; then ok "no Airflow UI user has a default password"
    else note "Airflow UI user(s) with a default password: $weak (port 8080 is open to the LAN)"; fi
fi

# Internet exposure: the router (UniFi) loops traffic to our public IP back to us
# only when a port forward exists. The router answers some ports itself (8080 is
# UniFi's device inform port), so a port only counts if the response matches ours.
public_ip=$(curl -s --max-time 5 https://api.ipify.org)
if [ -n "$public_ip" ]; then
    open=""
    for p in $INTERNET_PORTS; do
        nc -z -G 3 "$public_ip" "$p" 2>/dev/null || continue
        if [ "$p" = 5433 ]; then open+="$p "; continue; fi  # router doesn't listen on 5433
        sig() { curl -s -m 5 -o /dev/null -w '%{http_code} %{redirect_url}' "http://$1:$p/" | sed "s#$1#HOST#"; }
        [ "$(sig "$public_ip")" = "$(sig localhost)" ] && open+="$p "
    done
    [ -z "$open" ] && ok "no service ports reachable from the internet" || fail "port(s) reachable from the internet: $open"
else
    warn "could not look up public IP; internet exposure not checked"
fi

# ─── 6. Known-vulnerable Python packages in the running containers ───────────
echo "[6] Dependency vulnerabilities"
if [ ! -x "$STATE/venv/bin/pip-audit" ]; then
    /usr/bin/python3 -m venv "$STATE/venv" && "$STATE/venv/bin/pip" install -q --upgrade pip pip-audit > /dev/null 2>&1
fi
for svc in airflow-scheduler streamlit; do
    if ! compose exec -T "$svc" python -m pip freeze 2>/dev/null | grep '==' > "$STATE/freeze-$svc.txt"; then
        note "could not list packages in $svc"; continue
    fi
    "$STATE/venv/bin/pip-audit" -r "$STATE/freeze-$svc.txt" --no-deps --disable-pip --progress-spinner off \
        --format json -o "$STATE/audit-$svc.json" > /dev/null 2>&1
    vulns=$(/usr/bin/python3 -c "
import json
d = json.load(open('$STATE/audit-$svc.json'))
bad = sorted(((len(x['vulns']), x['name'], x['version']) for x in d['dependencies'] if x.get('vulns')), reverse=True)
if bad: print(f\"{len(bad)} packages, {sum(c for c, _, _ in bad)} CVEs; worst: \" + ', '.join(f'{n} {v} ({c})' for c, n, v in bad[:3]))" 2>/dev/null) || { note "pip-audit failed for $svc"; continue; }
    [ -z "$vulns" ] && ok "$svc: no known-vulnerable packages" || note "$svc: $vulns (details: $STATE/audit-$svc.json)"
done

# ─── Summary ─────────────────────────────────────────────────────────────────
echo "=== ${#problems[@]} problem(s)"
if [ ${#problems[@]} -gt 0 ]; then
    osascript -e "display notification \"${#problems[@]} problem(s). Log: $STATE/check.log\" with title \"dough-flow security check\" sound name \"Basso\"" 2>/dev/null
    exit 1
fi
