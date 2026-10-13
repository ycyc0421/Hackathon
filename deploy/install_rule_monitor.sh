#!/usr/bin/env bash
set -euo pipefail
repository=$(cd "$(dirname "$0")/.." && pwd)
target="$HOME/app/rule-monitor"
units="$HOME/.config/systemd/user"
mkdir -p "$target/backend/tools" "$target/backend/app/rules" "$units" "$HOME/app/shared/rule-sources"
cp "$repository/backend/tools/crawl_rule_sources.py" "$target/backend/tools/"
cp "$repository/backend/app/rules/source_catalog.json" "$target/backend/app/rules/"
cp "$repository/deploy/rule-monitor-requirements.txt" "$target/"
if [[ ! -x "$target/.venv/bin/python" ]]; then
  python3 -m venv --without-pip "$target/.venv"
fi
"$HOME/app/venv/bin/python" -m pip --python "$target/.venv/bin/python" install -r "$target/rule-monitor-requirements.txt"
for name in hackathon-rule-monitor.service hackathon-rule-monitor.timer; do
  if [[ -f "$units/$name" ]] && ! cmp -s "$repository/deploy/$name" "$units/$name"; then
    printf 'Existing monitor unit differs: %s. Review before replacing it.\n' "$units/$name" >&2
    exit 1
  fi
  cp "$repository/deploy/$name" "$units/$name"
done
systemd-analyze --user verify "$units/hackathon-rule-monitor.service" "$units/hackathon-rule-monitor.timer"
systemctl --user daemon-reload
systemctl --user enable --now hackathon-rule-monitor.timer
if ! systemctl --user start hackathon-rule-monitor.service; then
  printf 'Some sources failed. Last good versions are retained; the hourly timer will retry.\n' >&2
fi
systemctl --user list-timers hackathon-rule-monitor.timer --no-pager
