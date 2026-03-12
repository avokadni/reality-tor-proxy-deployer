# reality-tor-proxy-deployer

<p align="center">
  <a href="./README.md">Русский</a> · <strong>English</strong>
</p>

Python script for automated deployment of `VLESS + TCP + REALITY` with outbound traffic routed through `Tor SOCKS5` on a remote `Ubuntu 22.04` server.

The script connects to the server over SSH, installs `tor` and `xray`, generates `REALITY` keys, writes the config, restarts services, and verifies that:

1. `Tor` itself is working;
2. the full `VLESS + REALITY -> Tor` path comes up and returns `IsTor=true`.

## What gets deployed

- Incoming `VLESS + TCP + REALITY` on the selected port.
- Outbound traffic through local `Tor SOCKS5` on `127.0.0.1:9050`.
- `UDP` blocked.
- `geoip:private` blocked.

By default the script uses:

- `REALITY target`: `www.cloudflare.com:443`
- `REALITY SNI`: `www.cloudflare.com`
- `REALITY fingerprint`: `chrome`

Important: this is a workable default, but for real-world use you should replace the target/SNI with your own values.

## What the script does

- Connects to the server over SSH with a password.
- Installs `tor`, `curl`, `jq`, `openssl`, `unzip`.
- Installs `xray` using the official `XTLS/Xray-install`.
- Generates `x25519` keys and a `shortId` for `REALITY`.
- Writes the `xray` server config.
- Enables and restarts `tor` and `xray`.
- Opens the port in `ufw` if it is active.
- Verifies direct `Tor` egress.
- Verifies the e2e path using a temporary local `VLESS + REALITY` client.
- Prints a ready-to-import `vless://` link.

## Requirements

Local machine:

- Python 3
- SSH access to the server
- Ability to install dependencies from `requirements.txt`

Remote server:

- Ubuntu 22.04
- SSH password auth enabled
- `root` user or a user with `sudo`
- Internet access for `apt` and downloading `xray`

## Installation

```bash
git clone https://github.com/avokadni/reality-tor-proxy-deployer.git
cd reality-tor-proxy-deployer
python3 -m pip install -r requirements.txt
```

## Run

```bash
python3 deploy_vless_tor.py
```

The script will ask for:

- server IP / hostname
- SSH port
- SSH username
- SSH password
- `VLESS` port
- connection remark

## Output

After a successful run the script prints:

- `tor` service name
- `xray` config path
- `REALITY target`
- `REALITY SNI`
- `REALITY fingerprint`
- `REALITY client password`
- `REALITY short ID`
- ready-to-use `vless://` link
- `Tor` verification result
- `VLESS + REALITY -> Tor` verification result

## Architecture

```text
+------------+        +-------------+        +-------------+        +------+
| VLESS      |        | Xray Server |        | Tor SOCKS5  |        | Tor  |
| Client     +------->+ REALITY In  +------->+ 127.0.0.1   +------->+ Net  |
|            |        |             |        | :9050       |        |      |
+------------+        +-------------+        +-------------+        +------+
```

## Limitations

- The script configures `xray` directly, not `Marzban`.
- It assumes the `sudo` password is the same as the SSH password when not using `root`.
- It is better to run it with a numeric IP instead of a hostname if your local Python has `idna` codec issues.
- If the selected port is already in use, the script exits with an error.
- If the server cannot reach `GitHub`, the `Tor` network, or `check.torproject.org`, install or verification will fail.

## Troubleshooting

### `unknown encoding: idna`

Use a numeric server IP instead of a hostname, or reinstall your local Python.

### `Unable to parse x25519 output`

The script already supports both old and new `xray x25519` output formats. If the error still appears, share the full command output.

### `Remote port ... is already in use`

Pick another `VLESS` port.

### `Tor did not become ready in time`

Check:

- whether `tor` is running
- whether the server has internet access
- whether your provider or host blocks access to the Tor network

## Project files

- `deploy_vless_tor.py` - main deployment script
- `requirements.txt` - Python dependencies

## Useful links

- `Xray-install`: <https://github.com/XTLS/Xray-install>
- `Xray REALITY docs`: <https://xtls.github.io/en/config/transport.html>
- `Tor Project`: <https://www.torproject.org/>
