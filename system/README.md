# System configuration

These files live outside `$HOME` and need root to install.

```bash
sudo install -Dm644 network/20-ethernet.network /etc/systemd/network/
sudo install -Dm644 network/20-wlan.network     /etc/systemd/network/
sudo install -Dm644 iwd/main.conf               /etc/iwd/main.conf
sudo systemctl enable --now iwd systemd-networkd systemd-resolved
```

What this does:

- `iwd` handles Wi-Fi association only (`EnableNetworkConfiguration=false`);
  DHCP and addressing stay in `systemd-networkd`.
- Ethernet is preferred over Wi-Fi through route metrics 100 vs 600.
- `iwd` renames the wireless interface to `wlan0` (via its
  `80-iwd.link` file). The `.network` files match by type, not name.
- DNS presets chosen in the Waybar network menu are written as drop-ins at
  `/etc/systemd/network/<file>.d/99-waybar-dns.conf`, then `networkctl
  reload/reconfigure` and `resolvectl flush-caches` are run through polkit.

Check the result with:

```bash
networkctl status --no-pager
iwctl station wlan0 show
resolvectl status
```
