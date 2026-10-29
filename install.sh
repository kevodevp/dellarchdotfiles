#!/usr/bin/env bash
# Install these dotfiles into $HOME, backing up anything that gets replaced.
set -euo pipefail

src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
backup="$HOME/.dotfiles-backup-$(date +%Y%m%d-%H%M%S)"

echo "Backing up existing files to: $backup"
mkdir -p "$backup/.config" "$backup/.local"
for item in "$src"/.config/*; do
    name=$(basename "$item")
    if [ -e "$HOME/.config/$name" ]; then
        cp -a "$HOME/.config/$name" "$backup/.config/"
    fi
done
if [ -d "$HOME/.local/bin" ]; then
    cp -a "$HOME/.local/bin" "$backup/.local/"
fi
if [ -f "$HOME/.bashrc" ]; then
    cp -a "$HOME/.bashrc" "$backup/"
fi

echo "Installing configs..."
mkdir -p "$HOME/.config" "$HOME/.local/bin"
cp -a "$src/.config/." "$HOME/.config/"
cp -a "$src/.local/." "$HOME/.local/"
cp -a "$src/.bashrc" "$HOME/.bashrc"

if command -v systemctl >/dev/null 2>&1; then
    echo "Enabling user services..."
    systemctl --user enable waybar.service hyprpolkitagent.service 2>/dev/null || true
    pgrep -x waybar >/dev/null || systemctl --user start waybar.service 2>/dev/null || true
    pgrep -x hyprpolkitagent >/dev/null || systemctl --user start hyprpolkitagent.service 2>/dev/null || true
fi

echo
echo "Done. Next steps:"
echo "  1. Install the system network files (see system/README.md)."
echo "  2. Update the wallpaper path in ~/.config/hypr/hyprpaper.conf."
echo "  3. Adjust /home/brunomars paths in ~/.config/waybar/config.jsonc if needed."
echo "  4. Log out and back in (or restart Hyprland)."
