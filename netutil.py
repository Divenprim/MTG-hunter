"""Small standard-library-only LAN helpers used before app dependencies load."""
from __future__ import annotations

import ipaddress
import socket


def _usable(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        addr.version == 4
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_multicast
        and not addr.is_unspecified
    )


def lan_addresses() -> list[str]:
    """Return useful IPv4 addresses, with the default-route address first."""
    found: list[str] = []

    # UDP connect does not send application data; Windows merely chooses the
    # interface it would use. This is much more reliable than hostname lookup
    # on machines with VPN/WSL/VirtualBox adapters.
    for target in (("1.1.1.1", 80), ("8.8.8.8", 80)):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(target)
            ip = probe.getsockname()[0]
            if _usable(ip) and ip not in found:
                found.append(ip)
        except OSError:
            pass
        finally:
            probe.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _usable(ip) and ip not in found:
                found.append(ip)
    except OSError:
        pass

    # Prefer RFC1918 addresses over VPN/public adapter addresses after the
    # default-route address.
    if len(found) > 1:
        first, rest = found[0], found[1:]
        rest.sort(key=lambda ip: (not ipaddress.ip_address(ip).is_private, ip))
        found = [first] + rest
    return found


def primary_lan_address() -> str | None:
    found = lan_addresses()
    return found[0] if found else None
