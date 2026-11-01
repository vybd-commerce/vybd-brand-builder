#!/usr/bin/env bash
# Complete the whole brief over plain HTTP (Milestone 3 check). Needs: curl, jq, a running server.
#   VYBD_API_URL=http://localhost:8000 scripts/curl_brief.sh
set -euo pipefail
API="${VYBD_API_URL:-http://localhost:8000}"
EMAIL="curl-$(date +%s)-$RANDOM@example.com"

post() { curl -sS -X POST "$API$1" -H 'Content-Type: application/json' ${TOKEN:+-H "Authorization: Bearer $TOKEN"} -d "$2"; }
get()  { curl -sS "$API$1" ${TOKEN:+-H "Authorization: Bearer $TOKEN"}; }
check() { jq -e '.ok' >/dev/null <<<"$1" || { echo "FAILED: $1" >&2; exit 1; }; }

r=$(post /v1/auth/signup "{\"email\":\"$EMAIL\"}"); check "$r"
TOKEN=$(jq -r .data.token <<<"$r")
r=$(post /v1/brands '{"name":"Chilli Co"}'); check "$r"
BRAND=$(jq -r .data.brand.id <<<"$r")
echo "user=$EMAIL brand=$BRAND"

answer_for() {
  case "$1" in
    one_liner) echo "Small-batch hot sauce made with Kerala chillies." ;;
    customer) echo "Indian-American home cooks in their 30s who cook dal weekly and shop at Patel Brothers." ;;
    problem) echo "Supermarket hot sauces taste sweet and vinegary and don't suit Indian food." ;;
    alternative) echo "They use Sriracha or bring chilli pickle back from India; neither is right." ;;
    positioning) echo "The only hot sauce built for Indian home cooking." ;;
    product_price) echo "One 5oz green chilli sauce at \$9." ;;
    channels) echo "Our own website and Indian grocery stores." ;;
    competitors) echo "Diaspora Co., Brooklyn Delhi." ;;
    goals) echo "Decide between grocery wholesale and online for the first six months." ;;
  esac
}

while :; do
  r=$(get "/v1/brands/$BRAND/challenges/next"); check "$r"
  CID=$(jq -r '.data.challenge.id // empty' <<<"$r")
  [ -z "$CID" ] && break
  r=$(post "/v1/brands/$BRAND/challenges/$CID/answer" "$(jq -n --arg t "$(answer_for "$CID")" '{text:$t}')"); check "$r"
  echo "answered $CID -> $(jq -c '.progress | {completed, required, est_minutes_left}' <<<"$r")"
done

r=$(post "/v1/brands/$BRAND/notes" '{"text":"We sell 40 bottles a month at a farmers market."}'); check "$r"
r=$(get "/v1/brands/$BRAND/brief"); check "$r"
echo "next_actions: $(jq -c '[.next_actions[].action]' <<<"$r")"
jq -r .data.markdown <<<"$r"
