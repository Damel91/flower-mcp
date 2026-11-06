"""Owner-scoped certificate material for the dedicated HTTPS dashboard listener."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import sys

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.ledger_archive import ArchiveError, assert_private_archive_directory
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_file_ownership


_MAX_PEM_BYTES = 65536
_LEAF_LIFETIME = timedelta(days=90)
_RENEW_BEFORE = timedelta(days=14)
_PEM_KEY_HEADER = b"-----BEGIN PRIVATE KEY-----"
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_BROWSER_NUMERIC = re.compile(r"(?:[0-9]+|0x[0-9a-f]*)", re.ASCII)


class DashboardTLSError(ValueError):
    """Configuration or certificate material is unsuitable for HTTPS."""


@dataclass(frozen=True)
class DashboardTLSAddress:
    bind: str
    port: int
    name: str
    authority: str


@dataclass(frozen=True)
class DashboardTLS(DashboardTLSAddress):
    certfile: Path
    keyfile: Path
    ca_file: Path | None

    def context(self) -> ssl.SSLContext:
        return _server_context(self.certfile, self.keyfile)


def _server_context(certfile: Path, keyfile: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        # A fixed empty passphrase prevents OpenSSL from prompting on an
        # unexpectedly encrypted file.
        context.load_cert_chain(certfile, keyfile, password="")
    except (OSError, ValueError) as exc:
        raise DashboardTLSError("Cannot load the dashboard TLS certificate and key.") from exc
    return context


def _now() -> datetime:
    return datetime.now(UTC)


def _validate_port(port: int) -> None:
    if type(port) is not int or not 1 <= port <= 65535:
        raise DashboardTLSError("The dashboard TLS port must be between 1 and 65535.")


def _is_dns_name(name: str) -> bool:
    labels = name.split(".")
    return (len(name) <= 253 and all(_DNS_LABEL.fullmatch(label) for label in labels)
            and not _BROWSER_NUMERIC.fullmatch(labels[-1]))


def _address(bind: str, name: str, port: int) -> DashboardTLSAddress:
    try:
        if not isinstance(bind, str) or "%" in bind:
            raise ValueError
        bind_ip = ipaddress.ip_address(bind)
        if bind_ip.is_unspecified or bind_ip.is_multicast:
            raise ValueError
    except ValueError as exc:
        raise DashboardTLSError("The dashboard TLS bind must be a concrete unicast IP address.") from exc
    _validate_port(port)
    if not isinstance(name, str) or not name.isascii() or "%" in name:
        raise DashboardTLSError("The dashboard TLS name must be an ASCII DNS name or an IP address.")
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        name = name.lower()
        if not _is_dns_name(name):
            raise DashboardTLSError("The dashboard TLS name must be an ASCII DNS name or an IP address.") from None
        host = name
    else:
        if ip.is_unspecified or ip.is_multicast:
            raise DashboardTLSError("The dashboard TLS name must identify a unicast address.")
        name = str(ip)
        host = f"[{name}]" if ip.version == 6 else name
    authority = host if port == 443 else f"{host}:{port}"
    return DashboardTLSAddress(str(bind_ip), port, name, authority)


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def _matches_name(certificate: x509.Certificate, name: str) -> bool:
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    expected = _san(name)
    if isinstance(expected, x509.IPAddress):
        return expected in names
    labels = name.split(".")
    for candidate in names.get_values_for_type(x509.DNSName):
        candidate = candidate.lower()
        if candidate == name:
            return True
        pattern = candidate.split(".")
        if len(pattern) >= 3 and pattern[0] == "*" and pattern[1:] == labels[1:]:
            return True
    return False


def _read_public_pem(path: Path) -> bytes:
    """Read a user-owned certificate, which may have public read permission."""
    before = secure._metadata(path, directory=False)
    if os.name != "nt" and stat.S_IMODE(before.st_mode) & 0o022:
        raise DashboardTLSError("The supplied dashboard TLS certificate must not be writable by other users.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise DashboardTLSError("The supplied dashboard TLS certificate changed while opening it.")
        data = source.read(_MAX_PEM_BYTES + 1)
    if len(data) > _MAX_PEM_BYTES:
        raise DashboardTLSError("The supplied dashboard TLS certificate is too large.")
    return data


def _explicit(address: DashboardTLSAddress, cert: Path, key: Path) -> DashboardTLS:
    cert, key = Path(cert).expanduser().absolute(), Path(key).expanduser().absolute()
    try:
        certificate = x509.load_pem_x509_certificates(_read_public_pem(cert))[0]
        secure.read_owned(key, limit=_MAX_PEM_BYTES)
        now = _now()
        if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
            raise DashboardTLSError("The supplied dashboard TLS certificate is outside its validity dates.")
        if not _matches_name(certificate, address.name):
            raise DashboardTLSError("The supplied dashboard TLS certificate does not cover the configured name.")
        prepared = DashboardTLS(address.bind, address.port, address.name, address.authority, cert, key, None)
        prepared.context()
        return prepared
    except DashboardTLSError:
        raise
    except (OSError, ValueError, IndexError, x509.ExtensionNotFound, x509.DuplicateExtension) as exc:
        raise DashboardTLSError("Cannot read a suitable supplied dashboard TLS certificate and private key.") from exc


def validate_dashboard_tls(
    *, bind: str, name: str, port: int, cert: Path | None = None, key: Path | None = None
) -> DashboardTLSAddress:
    """Check listener identity and any explicit PEM pair without creating files."""
    address = _address(bind, name, port)
    if (cert is None) != (key is None):
        raise DashboardTLSError("Supply both the dashboard TLS certificate and key, or omit both.")
    if cert is not None and key is not None:
        return _explicit(address, cert, key)
    return address


def _private_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _key_matches(certificate: x509.Certificate, key: ec.EllipticCurvePrivateKey) -> bool:
    def public_bytes(public_key):
        return public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    return public_bytes(certificate.public_key()) == public_bytes(key.public_key())


def _identity(path: Path) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    contents = secure.read_owned(path, limit=_MAX_PEM_BYTES)
    certificate_pem, marker, key_pem = contents.partition(_PEM_KEY_HEADER)
    if not marker:
        raise DashboardTLSError("Persisted dashboard TLS material is malformed.")
    certificate = x509.load_pem_x509_certificate(certificate_pem)
    key = serialization.load_pem_private_key(marker + key_pem, password=None)
    if (not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1)
            or not _key_matches(certificate, key)
            or certificate.public_bytes(serialization.Encoding.PEM) != certificate_pem
            or _private_pem(key) != marker + key_pem):
        raise DashboardTLSError("Persisted dashboard TLS material is malformed.")
    return certificate, key


def _save_identity(path: Path, certificate: x509.Certificate, key: ec.EllipticCurvePrivateKey) -> None:
    payload = certificate.public_bytes(serialization.Encoding.PEM) + _private_pem(key)
    if len(payload) > _MAX_PEM_BYTES:
        raise DashboardTLSError("The generated dashboard TLS identity is too large.")
    secure.write_owned(path, payload)


def _common_name(value: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, value)])


def _certificate(
    subject: x509.Name, issuer: x509.Name, key: ec.EllipticCurvePrivateKey,
    now: datetime, end: datetime, *, is_ca: bool,
) -> x509.CertificateBuilder:
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=0 if is_ca else None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=not is_ca, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=is_ca, crl_sign=is_ca,
            encipher_only=None, decipher_only=None,
        ), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )


def _exists(path: Path) -> bool:
    return os.path.lexists(path)


def _authority(directory: Path, now: datetime) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey, Path]:
    identity, exported = directory / "ca-identity.pem", directory / "ca.pem"
    if _exists(identity):
        ca, key = _identity(identity)
        ca.verify_directly_issued_by(ca)
        constraints = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = ca.extensions.get_extension_for_class(x509.KeyUsage).value
        if not constraints.ca or constraints.path_length != 0 or not usage.key_cert_sign:
            raise DashboardTLSError("The persisted dashboard TLS CA is unsuitable.")
        if not ca.not_valid_before_utc <= now < ca.not_valid_after_utc - _RENEW_BEFORE:
            raise DashboardTLSError("The dashboard TLS CA is outside its usable lifetime. Supply a current PEM pair.")
    else:
        if _exists(exported) or _exists(directory / "server.pem") or _exists(directory / "lan.pem"):
            raise DashboardTLSError("The dashboard TLS CA identity is missing.")
        key = ec.generate_private_key(ec.SECP256R1())
        subject = _common_name("Flower Dashboard CA")
        ca = _certificate(subject, subject, key, now, now + timedelta(days=3650), is_ca=True).sign(
            key, hashes.SHA256()
        )
        _save_identity(identity, ca, key)
    ca_pem = ca.public_bytes(serialization.Encoding.PEM)
    if _exists(exported):
        if secure.read_owned(exported, limit=_MAX_PEM_BYTES) != ca_pem:
            raise DashboardTLSError("The exported dashboard TLS CA differs from the persisted identity.")
    else:
        secure.write_owned(exported, ca_pem)
    return ca, key, exported


def _leaf(
    path: Path, names: tuple[str, ...], ca: x509.Certificate, ca_key: ec.EllipticCurvePrivateKey,
    now: datetime, *, lan: bool,
) -> datetime:
    expected = [_san(name) for name in names]
    if _exists(path):
        leaf, _ = _identity(path)
        leaf.verify_directly_issued_by(ca)
        constraints = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        stored_names = list(leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
        if lan:
            ipv4 = [name for name in stored_names if isinstance(name, x509.IPAddress)
                    and isinstance(name.value, ipaddress.IPv4Address)]
            dns_count = sum(isinstance(name, x509.DNSName) for name in stored_names)
            valid_names = bool(ipv4) and len(ipv4) + dns_count == len(stored_names)
        else:
            valid_names = len(stored_names) == 1 and isinstance(stored_names[0], (x509.DNSName, x509.IPAddress))
        if (constraints.ca or usage != x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])
                or not valid_names
                or leaf.not_valid_before_utc < ca.not_valid_before_utc
                or leaf.not_valid_after_utc > ca.not_valid_after_utc
                or leaf.not_valid_before_utc > now):
            raise DashboardTLSError("The persisted dashboard TLS server certificate is unsuitable.")
        if stored_names == expected and leaf.not_valid_after_utc > now + _RENEW_BEFORE:
            return leaf.not_valid_after_utc
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        _certificate(_common_name("Flower Dashboard"), ca.subject, key, now,
                     min(now + _LEAF_LIFETIME, ca.not_valid_after_utc), is_ca=False)
        .add_extension(x509.SubjectAlternativeName(expected), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _save_identity(path, leaf, key)
    return leaf.not_valid_after_utc


@dataclass(frozen=True)
class _GeneratedTLS:
    names: tuple[str, ...]
    hostnames: tuple[str, ...]
    certfile: Path
    ca_file: Path
    expires_at: datetime
    context: ssl.SSLContext


def _generated_tls(
    config_path: Path, names: tuple[str, ...], now: datetime, *, lan: bool, hostnames: tuple[str, ...] = (),
) -> _GeneratedTLS:
    config_path = Path(config_path).expanduser().absolute()
    selector = hashlib.sha256(os.fsencode(config_path.name)).hexdigest()[:16]
    directory = config_path.parent / f".flower-dashboard-tls-{selector}"
    try:
        secure.check_data_file(config_path)
        secure.ensure_directory(directory)
        assert_private_archive_directory(directory)
        with acquire_file_ownership(directory / "material"):
            ca, ca_key, ca_file = _authority(directory, now)
            leaf = directory / ("lan.pem" if lan else "server.pem")
            expires_at = _leaf(leaf, names + hostnames, ca, ca_key, now, lan=lan)
            return _GeneratedTLS(names, hostnames, leaf, ca_file, expires_at, _server_context(leaf, leaf))
    except DashboardTLSError:
        raise
    except (OSError, ValueError, TypeError, ArchiveError, RuntimeOwnershipError,
            InvalidSignature, UnsupportedAlgorithm, x509.ExtensionNotFound, x509.DuplicateExtension) as exc:
        raise DashboardTLSError("Cannot prepare safe dashboard TLS material for this profile.") from exc


def prepare_dashboard_tls(
    config_path: Path, *, bind: str, name: str, port: int,
    cert: Path | None = None, key: Path | None = None,
) -> DashboardTLS:
    """Prepare local owner-private TLS files or select the explicit pair."""
    address = validate_dashboard_tls(bind=bind, name=name, port=port, cert=cert, key=key)
    if isinstance(address, DashboardTLS):
        return address
    material = _generated_tls(config_path, (address.name,), _now(), lan=False)
    return DashboardTLS(address.bind, address.port, address.name, address.authority,
                        material.certfile, material.certfile, material.ca_file)


def _lan_names() -> tuple[str, ...]:
    try:
        from psutil import net_if_addrs
    except ImportError as exc:
        raise DashboardTLSError("The LAN dashboard requires psutil for interface discovery.") from exc
    try:
        addresses = {
            ipaddress.IPv4Address(entry.address)
            for entries in net_if_addrs().values()
            for entry in entries
            if entry.family == socket.AF_INET
        }
    except (OSError, ValueError) as exc:
        raise DashboardTLSError("Cannot discover IPv4 addresses for the LAN dashboard.") from exc
    names = tuple(
        str(address) for address in sorted(addresses)
        if not (address.is_unspecified or address.is_multicast or address.is_reserved)
    )
    if not names:
        raise DashboardTLSError("No assigned IPv4 addresses are available for the LAN dashboard.")
    return names


def _lan_hostnames() -> tuple[str, ...]:
    # macOS's Bonjour name is separately configured from the machine hostname.
    # DNS is optional. Missing or invalid OS names leave the IPv4 URLs usable.
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["/usr/sbin/scutil", "--get", "LocalHostName"], capture_output=True,
                                    encoding="ascii", errors="replace", check=True, timeout=0.25)
            label = result.stdout.strip().lower()
            name = f"{label}.local" if _DNS_LABEL.fullmatch(label) else ""
        else:
            name = socket.gethostname().lower().removesuffix(".")
    except (OSError, subprocess.SubprocessError):
        return ()
    if (not _is_dns_name(name) or name.split(".", 1)[0] == "localhost" or name.endswith(".localhost")):
        return ()
    return (name,)


class DashboardLANTLS:
    """Select the current SAN set and leaf for new wildcard TLS connections."""

    bind = "0.0.0.0"

    def __init__(self, config_path: Path, port: int, material: _GeneratedTLS) -> None:
        self.port = port
        self.ca_file = material.ca_file
        self._config_path = config_path
        self._material = material
        self._listener_context = material.context
        self._listener_context.sni_callback = self._select_context

    @property
    def names(self) -> tuple[str, ...]:
        return self._material.names

    @property
    def hostnames(self) -> tuple[str, ...]:
        return self._material.hostnames

    def context(self) -> ssl.SSLContext:
        return self._listener_context

    def _select_context(
        self, connection: ssl.SSLObject | ssl.SSLSocket, _name: str | None, _context: ssl.SSLContext,
    ) -> None:
        # IP clients can omit SNI. The current leaf covers every assigned IP.
        connection.context = self._material.context

    def refresh(self) -> bool:
        """Publish a complete generation. On failure retain the last good one."""
        names = _lan_names()
        hostnames = _lan_hostnames()
        now = _now()
        if (names == self.names and hostnames == self.hostnames
                and self._material.expires_at > now + _RENEW_BEFORE):
            return False
        self._material = _generated_tls(self._config_path, names, now, lan=True, hostnames=hostnames)
        return True


def prepare_dashboard_lan_tls(config_path: Path, *, port: int) -> DashboardLANTLS:
    """Issue a profile-CA leaf for assigned IPv4 addresses and configured names."""
    _validate_port(port)
    path = config_path.expanduser().absolute()
    return DashboardLANTLS(path, port, _generated_tls(path, _lan_names(), _now(), lan=True, hostnames=_lan_hostnames()))
