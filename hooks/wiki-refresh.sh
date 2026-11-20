#!/usr/bin/env bash
# wiki-refresh.sh: SessionStart hook that pulls (fast-forward only) the local clone of a repo's ADR wiki in the background, or clones it when missing; prints nothing and always exits 0.

set -uo pipefail

cat >/dev/null 2>&1 || true

here="$(cd "$(dirname "$0")" && pwd)"
# The facts of the repository the session is about (project_fact.py repo_root); none when that is unclear.
fact() { python3 "$here/project_fact.py" "$@" 2>/dev/null; }

adr_dir="$(fact ADR_DIR)"
case "$adr_dir" in
  "~/"*) adr_dir="$HOME/${adr_dir#\~/}" ;;
  /*) ;;
  *) exit 0 ;;
esac
clone="$(dirname "${adr_dir%/}")"
remote="$(fact ADR_REMOTE)"

# WIKI_GIT_TOKEN is a GitHub token: it goes only to github.com over https, with the remote the repo names.
header=""
case "$remote" in
  https://github.com/*)
    [ -n "${WIKI_GIT_TOKEN:-}" ] && header="Authorization: Basic $(printf 'x-access-token:%s' "$WIKI_GIT_TOKEN" | base64 | tr -d '\n')" ;;
esac
keep_header() {
  [ -n "$header" ] || return 0
  git -C "$clone" config http.extraHeader "$header" && chmod 600 "$clone/.git/config"
}

if [ -d "$clone/.git" ]; then
  # Only the clone of the named remote is pulled or given the token; another repository at that path is left alone.
  origin="$(git -C "$clone" config --get remote.origin.url 2>/dev/null)"
  [ -n "$remote" ] && [ "$origin" = "$remote" ] || exit 0
  (keep_header; git -C "$clone" pull -q --ff-only >/dev/null 2>&1 &)
elif [ ! -e "$clone" ] && [ -n "$remote" ]; then
  (git ${header:+-c "http.extraHeader=$header"} clone -q "$remote" "$clone" >/dev/null 2>&1 \
     && keep_header &)
fi
exit 0
