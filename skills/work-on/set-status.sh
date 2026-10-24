#!/usr/bin/env bash
# Set the Status of a GitHub issue on every GitHub project it belongs to.
#
#   ${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh <issue number> "<Status>" [owner/repo]
#
# The repo defaults to the one the current folder's git remote points at.
# Status is an option of the project's Status field, for example Backlog,
# In Progress, In Review, Done or Canceled. Prints one line per project.
# Needs gh signed in with the project scope.
set -euo pipefail

num="${1:?issue number}"
want="${2:?status name}"
repo="${3:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
owner="${repo%%/*}"
name="${repo#*/}"

items=$(gh api graphql -f owner="$owner" -f name="$name" -F num="$num" -f query='
query($owner:String!,$name:String!,$num:Int!){repository(owner:$owner,name:$name){issue(number:$num){
  projectItems(first:20){nodes{id project{id title
    field(name:"Status"){... on ProjectV2SingleSelectField{id options{id name}}}}}}}}}' \
  --jq '.data.repository.issue.projectItems.nodes')

if [ "$(jq 'length' <<<"$items")" = "0" ]; then
  echo "#$num is in no GitHub project; nothing to set."
  exit 0
fi

jq -c '.[]' <<<"$items" | while read -r item; do
  title=$(jq -r '.project.title' <<<"$item")
  option=$(jq -r --arg w "$want" '.project.field.options[] | select(.name == $w) | .id' <<<"$item")
  if [ -z "$option" ]; then
    echo "$title: has no Status called \"$want\"; options are $(jq -r '[.project.field.options[].name] | join(", ")' <<<"$item")."
    continue
  fi
  gh api graphql -f p="$(jq -r '.project.id' <<<"$item")" -f i="$(jq -r '.id' <<<"$item")" \
    -f f="$(jq -r '.project.field.id' <<<"$item")" -f o="$option" -f query='
    mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,
      itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}' >/dev/null
  echo "$title: #$num is now $want."
done
