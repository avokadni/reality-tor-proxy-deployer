#!/usr/bin/env python3
"""Deploy a VLESS + TCP + REALITY -> Tor gateway to Ubuntu 22.04."""

from __future__ import annotations

import getpass
import ipaddress
import json
import re
import secrets
import shlex
import socket
import sys
import textwrap
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlencode

try:
    import paramiko
except ImportError:
    print(
        "Missing dependency: paramiko\n"
        "Install it with: python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)


XRAY_BIN = "/usr/local/bin/xray"
XRAY_CONFIG = "/usr/local/etc/xray/config.json"
TOR_CHECK_URL = "https://check.torproject.org/api/ip"
REALITY_TARGET = "www.cloudflare.com:443"
REALITY_SERVER_NAME = "www.cloudflare.com"
REALITY_FINGERPRINT = "chrome"
REALITY_SPIDER_X = "/"


class RemoteCommandError(RuntimeError):
    def __init__(self, command: str, code: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Command failed with exit code {code}: {command}")


@dataclass
class Options:
    host: str
    ssh_port: int
    username: str
    password: str
    vless_port: int
    remark: str


@dataclass
class RealitySettings:
    private_key: str
    client_password: str
    short_id: str


class RemoteHost:
    def __init__(self, options: Options) -> None:
        self.options = options
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self) -> None:
        connect_kwargs = {
            "hostname": self.options.host,
            "port": self.options.ssh_port,
            "username": self.options.username,
            "password": self.options.password,
            "timeout": 15,
            "banner_timeout": 15,
            "auth_timeout": 15,
            "look_for_keys": False,
            "allow_agent": False,
        }

        ip_literal = parse_ip_literal(self.options.host)
        if ip_literal is None:
            try:
                self.client.connect(**connect_kwargs)
            except LookupError as exc:
                if "idna" in str(exc).lower():
                    raise RuntimeError(
                        "Local Python is missing the 'idna' codec. "
                        "Enter a numeric IP address instead of a hostname, or reinstall Python."
                    ) from exc
                raise
            return

        sock = open_ip_socket(ip_literal, self.options.ssh_port, timeout=15)
        try:
            self.client.connect(sock=sock, **connect_kwargs)
        except Exception:
            sock.close()
            raise

    def close(self) -> None:
        self.client.close()

    def run(
        self,
        command: str,
        *,
        sudo: bool = False,
        check: bool = True,
        timeout: int | None = None,
    ) -> tuple[int, str, str]:
        wrapped = f"bash -lc {shlex.quote(command)}"
        if sudo and self.options.username != "root":
            wrapped = f"sudo -S -p '' {wrapped}"

        stdin, stdout, stderr = self.client.exec_command(
            wrapped,
            timeout=timeout,
            get_pty=True,
        )
        if sudo and self.options.username != "root":
            stdin.write(self.options.password + "\n")
            stdin.flush()

        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if check and code != 0:
            raise RemoteCommandError(command, code, out, err)
        return code, out, err

    def upload_text(self, remote_path: str, content: str, *, mode: int = 0o600) -> None:
        temp_path = f"/tmp/codex-{uuid.uuid4().hex}"
        sftp = self.client.open_sftp()
        try:
            with sftp.file(temp_path, "w") as handle:
                handle.write(content)
            sftp.chmod(temp_path, mode)
        finally:
            sftp.close()

        self.run(
            f"install -D -m {format(mode, '04o')} {shlex.quote(temp_path)} {shlex.quote(remote_path)}",
            sudo=True,
        )
        self.run(f"rm -f {shlex.quote(temp_path)}", sudo=True)


def prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("Value is required.")


def prompt_int(label: str, default: int) -> int:
    while True:
        value = input(f"{label} [{default}]: ").strip()
        if not value:
            return default
        if value.isdigit():
            return int(value)
        print("Enter a valid integer.")


def print_step(text: str) -> None:
    print(f"\n==> {text}")


def parse_ip_literal(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def open_ip_socket(
    ip_literal: ipaddress.IPv4Address | ipaddress.IPv6Address,
    port: int,
    *,
    timeout: int,
) -> socket.socket:
    family = socket.AF_INET6 if ip_literal.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    address: tuple[str, int] | tuple[str, int, int, int]
    if ip_literal.version == 6:
        address = (str(ip_literal), port, 0, 0)
    else:
        address = (str(ip_literal), port)
    sock.connect(address)
    return sock


def render_server_config(vless_port: int, client_id: str, reality: RealitySettings) -> str:
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "vless-in",
                "listen": "0.0.0.0",
                "port": vless_port,
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": client_id, "email": "codex-vless-tor@localhost"}],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "tcpSettings": {"header": {"type": "none"}},
                    "realitySettings": {
                        "show": False,
                        "target": REALITY_TARGET,
                        "xver": 0,
                        "serverNames": [REALITY_SERVER_NAME],
                        "privateKey": reality.private_key,
                        "shortIds": [reality.short_id],
                        "fingerprint": REALITY_FINGERPRINT,
                        "spiderX": REALITY_SPIDER_X,
                    },
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            }
        ],
        "outbounds": [
            {
                "tag": "tor-out",
                "protocol": "socks",
                "settings": {"servers": [{"address": "127.0.0.1", "port": 9050}]},
            },
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "block"},
                {"type": "field", "network": "udp", "outboundTag": "block"},
                {"type": "field", "network": "tcp", "outboundTag": "tor-out"},
            ],
        },
    }
    return json.dumps(config, indent=2) + "\n"


def render_test_client_config(
    socks_port: int,
    vless_port: int,
    client_id: str,
    reality: RealitySettings,
) -> str:
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": False},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": vless_port,
                            "users": [{"id": client_id, "encryption": "none"}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "tcpSettings": {"header": {"type": "none"}},
                    "realitySettings": {
                        "serverName": REALITY_SERVER_NAME,
                        "fingerprint": REALITY_FINGERPRINT,
                        "password": reality.client_password,
                        "shortId": reality.short_id,
                        "spiderX": REALITY_SPIDER_X,
                    },
                },
            }
        ],
    }
    return json.dumps(config, indent=2) + "\n"


def generate_reality_settings(remote: RemoteHost) -> RealitySettings:
    print_step("Generating REALITY keys")
    _, out, _ = remote.run(f"{XRAY_BIN} x25519", sudo=True)
    private_match = re.search(r"Private(?:\s+key|Key):\s*(\S+)", out, re.IGNORECASE)
    password_match = re.search(r"Password:\s*(\S+)", out, re.IGNORECASE)
    public_match = re.search(r"Public(?:\s+key|Key):\s*(\S+)", out, re.IGNORECASE)
    client_password = None
    if password_match:
        client_password = password_match.group(1)
    elif public_match:
        client_password = public_match.group(1)

    if not private_match or not client_password:
        raise RuntimeError(f"Unable to parse x25519 output:\n{out.strip()}")

    _, short_id, _ = remote.run("openssl rand -hex 8", sudo=True)
    short_id = short_id.strip()
    if not re.fullmatch(r"[0-9a-f]{16}", short_id):
        raise RuntimeError(f"Unable to generate a valid REALITY short ID: {short_id!r}")

    return RealitySettings(
        private_key=private_match.group(1),
        client_password=client_password,
        short_id=short_id,
    )


def detect_tor_unit(remote: RemoteHost) -> str:
    _, out, _ = remote.run(
        "if systemctl list-unit-files | grep -q '^tor@default\\.service'; then echo tor@default; else echo tor; fi",
        sudo=True,
    )
    return out.strip() or "tor"


def install_stack(
    remote: RemoteHost,
    options: Options,
    client_id: str,
) -> tuple[str, RealitySettings]:
    print_step("Checking remote OS")
    _, out, _ = remote.run("source /etc/os-release && printf '%s %s' \"$ID\" \"$VERSION_ID\"")
    if out.strip() != "ubuntu 22.04":
        raise RuntimeError(f"Expected Ubuntu 22.04, got: {out.strip() or 'unknown'}")

    print_step("Checking target port")
    _, out, _ = remote.run(f"ss -ltnH '( sport = :{options.vless_port} )' || true", sudo=True)
    if out.strip():
        raise RuntimeError(f"Remote port {options.vless_port} is already in use.")

    print_step("Installing Tor and base packages")
    remote.run(
        textwrap.dedent(
            """
            export DEBIAN_FRONTEND=noninteractive
            apt-get update
            apt-get install -y ca-certificates curl jq openssl tor unzip
            """
        ).strip(),
        sudo=True,
        timeout=1800,
    )

    print_step("Installing Xray from the official installer")
    remote.run(
        'bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install',
        sudo=True,
        timeout=1800,
    )

    reality = generate_reality_settings(remote)

    print_step("Uploading Xray server config")
    remote.upload_text(
        XRAY_CONFIG,
        render_server_config(options.vless_port, client_id, reality),
        mode=0o644,
    )

    tor_unit = detect_tor_unit(remote)

    print_step("Restarting services")
    remote.run(f"systemctl enable --now {shlex.quote(tor_unit)}", sudo=True, timeout=120)
    remote.run("systemctl enable --now xray", sudo=True, timeout=120)
    remote.run(f"systemctl restart {shlex.quote(tor_unit)}", sudo=True, timeout=120)
    remote.run("systemctl restart xray", sudo=True, timeout=120)

    print_step("Opening firewall port if UFW is active")
    remote.run(
        textwrap.dedent(
            f"""
            if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
              ufw allow {options.vless_port}/tcp
            fi
            """
        ).strip(),
        sudo=True,
        timeout=120,
    )

    print_step("Checking listeners and services")
    remote.run(f"systemctl is-active --quiet {shlex.quote(tor_unit)}", sudo=True)
    remote.run("systemctl is-active --quiet xray", sudo=True)
    remote.run("ss -ltnH '( sport = :9050 )' | grep -q .", sudo=True)
    remote.run(f"ss -ltnH '( sport = :{options.vless_port} )' | grep -q .", sudo=True)
    return tor_unit, reality


def check_direct_tor(remote: RemoteHost) -> dict:
    print_step("Checking direct Tor egress")
    shell_script = textwrap.dedent(
        f"""
        set -euo pipefail
        for _ in $(seq 1 30); do
          if out=$(curl -fsS --max-time 30 --socks5-hostname 127.0.0.1:9050 {shlex.quote(TOR_CHECK_URL)}); then
            if printf '%s' "$out" | jq -e '.IsTor == true' >/dev/null 2>&1; then
              printf '%s' "$out"
              exit 0
            fi
          fi
          sleep 3
        done
        echo "Tor did not become ready in time." >&2
        exit 1
        """
    ).strip()
    _, out, _ = remote.run(
        shell_script,
        sudo=True,
        timeout=240,
    )
    result = json.loads(out)
    if not result.get("IsTor"):
        raise RuntimeError(f"Tor check failed: {out.strip()}")
    return result


def check_vless_tor_path(
    remote: RemoteHost,
    options: Options,
    client_id: str,
    reality: RealitySettings,
) -> dict:
    print_step("Checking VLESS + REALITY -> Tor end-to-end path")
    remote_path = f"/tmp/xray-vless-tor-test-{uuid.uuid4().hex}.json"
    socks_port = secrets.randbelow(20000) + 20000
    remote.upload_text(
        remote_path,
        render_test_client_config(socks_port, options.vless_port, client_id, reality),
        mode=0o600,
    )

    test_script = textwrap.dedent(
        f"""
        set -euo pipefail
        TEST_CONFIG={shlex.quote(remote_path)}
        TEST_LOG=/tmp/xray-vless-tor-test.log
        {XRAY_BIN} run -config "$TEST_CONFIG" >"$TEST_LOG" 2>&1 &
        TEST_PID=$!
        cleanup() {{
          kill "$TEST_PID" >/dev/null 2>&1 || true
          wait "$TEST_PID" >/dev/null 2>&1 || true
          rm -f "$TEST_CONFIG"
        }}
        trap cleanup EXIT
        for _ in $(seq 1 20); do
          if ss -ltnH '( sport = :{socks_port} )' | grep -q .; then
            break
          fi
          sleep 1
        done
        ss -ltnH '( sport = :{socks_port} )' | grep -q .
        for _ in $(seq 1 20); do
          if out=$(curl -fsS --max-time 30 --socks5-hostname 127.0.0.1:{socks_port} {shlex.quote(TOR_CHECK_URL)}); then
            if printf '%s' "$out" | jq -e '.IsTor == true' >/dev/null 2>&1; then
              printf '%s' "$out"
              exit 0
            fi
          fi
          sleep 3
        done
        echo "VLESS + REALITY -> Tor path did not become ready in time." >&2
        exit 1
        """
    ).strip()

    _, out, _ = remote.run(test_script, sudo=True, timeout=240)
    result = json.loads(out)
    if not result.get("IsTor"):
        raise RuntimeError(f"VLESS + REALITY check failed: {out.strip()}")
    return result


def build_vless_link(options: Options, client_id: str, reality: RealitySettings) -> str:
    query = urlencode(
        {
            "encryption": "none",
            "security": "reality",
            "type": "tcp",
            "headerType": "none",
            "sni": REALITY_SERVER_NAME,
            "fp": REALITY_FINGERPRINT,
            "pbk": reality.client_password,
            "sid": reality.short_id,
            "spx": REALITY_SPIDER_X,
        },
        quote_via=quote,
    )
    return (
        f"vless://{client_id}@{options.host}:{options.vless_port}"
        f"?{query}"
        f"#{quote(options.remark, safe='-._~')}"
    )


def collect_options() -> Options:
    host = prompt_text("Server IP / hostname")
    ssh_port = prompt_int("SSH port", 22)
    username = prompt_text("SSH username", "root")
    password = getpass.getpass("SSH password: ")
    if not password:
        raise RuntimeError("SSH password is required.")
    vless_port = prompt_int("VLESS listen port", 443)
    remark = prompt_text("Connection remark", "vless-tor")
    return Options(host, ssh_port, username, password, vless_port, remark)


def main() -> int:
    try:
        options = collect_options()
        client_id = str(uuid.uuid4())
        remote = RemoteHost(options)

        print_step("Connecting to remote host")
        remote.connect()
        try:
            tor_unit, reality = install_stack(remote, options, client_id)
            tor_result = check_direct_tor(remote)
            vless_result = check_vless_tor_path(remote, options, client_id, reality)
        finally:
            remote.close()

        print_step("Deployment completed")
        print(f"Tor service: {tor_unit}")
        print(f"Xray config: {XRAY_CONFIG}")
        print(f"REALITY target: {REALITY_TARGET}")
        print(f"REALITY SNI: {REALITY_SERVER_NAME}")
        print(f"REALITY fingerprint: {REALITY_FINGERPRINT}")
        print(f"REALITY client password: {reality.client_password}")
        print(f"REALITY short ID: {reality.short_id}")
        print(f"VLESS link: {build_vless_link(options, client_id, reality)}")
        print(f"Direct Tor check: IsTor={tor_result.get('IsTor')} IP={tor_result.get('IP')}")
        print(f"VLESS + REALITY -> Tor check: IsTor={vless_result.get('IsTor')} IP={vless_result.get('IP')}")
        print("\nNote: this script deploys Xray directly, not Marzban.")
        print("The default REALITY mask is www.cloudflare.com:443. Change it later if needed.")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 130
    except RemoteCommandError as exc:
        print(f"\nRemote command failed: {exc.command}", file=sys.stderr)
        if exc.stdout.strip():
            print("\nSTDOUT:\n" + exc.stdout.strip(), file=sys.stderr)
        if exc.stderr.strip():
            print("\nSTDERR:\n" + exc.stderr.strip(), file=sys.stderr)
        return exc.code or 1
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
