#!/usr/bin/env sh
set -eu

install -Dm755 herdres.py "$HOME/.local/bin/herdres"
install -Dm644 .env.example "$HOME/.config/herdres/herdres.env"
mkdir -p "$HOME/.config/systemd/user"
cp systemd/user/herdres.service systemd/user/herdres.timer "$HOME/.config/systemd/user/"

printf '%s\n' "Installed herdres."
printf '%s\n' "Edit $HOME/.config/herdres/herdres.env, then run:"
printf '%s\n' "  systemctl --user daemon-reload"
printf '%s\n' "  systemctl --user enable --now herdres.timer"

