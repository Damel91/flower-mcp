"""Dashboard certificate identity, ownership and HTTPS behavior."""

from datetime import timedelta
import os
from pathlib import Path
import ssl
import stat

from cryptography import x509
from cryptography.hazmat.primitives import serialization
import pytest

from flow_of_work_mcp import dashboard_tls as tls
from flow_of_work_mcp import managed_service_security as secure


@pytest.fixture
def profile(tmp_path):
    config = tmp_path.resolve() / "flower.yaml"
    config.write_text("fixture configuration", encoding="utf-8")
    return config


def _prepare(config, *, name="flower.example.test", **kwargs):
    return tls.prepare_dashboard_tls(config, bind="127.0.0.1", name=name, port=8443, **kwargs)


def _transfer(source, destination):
    payload = source.read()
    if payload:
        destination.write(payload)


def _handshake(material, name):
    client_context = ssl.create_default_context(cafile=material.ca_file)
    client_context.verify_flags |= ssl.VERIFY_X509_STRICT
    server_in, server_out, client_in, client_out = (ssl.MemoryBIO() for _ in range(4))
    server = material.context().wrap_bio(server_in, server_out, server_side=True)
    client = client_context.wrap_bio(client_in, client_out, server_hostname=name)
    waiting = {server, client}
    for _ in range(16):
        for peer in tuple(waiting):
            try:
                peer.do_handshake()
            except ssl.SSLWantReadError:
                continue
            waiting.remove(peer)
        _transfer(server_out, client_in)
        _transfer(client_out, server_in)
        if not waiting:
            return client.version()
    pytest.fail("The TLS handshake did not complete.")


def test_dns_and_ipv6_authorities_are_canonical_without_writing(profile):
    assert tls.validate_dashboard_tls(bind="127.0.0.1", name="Flower.Example.Test", port=443).authority == (
        "flower.example.test"
    )
    address = tls.validate_dashboard_tls(bind="2001:0db8::2", name="2001:0db8::3", port=8443)
    assert (address.bind, address.name, address.authority) == ("2001:db8::2", "2001:db8::3", "[2001:db8::3]:8443")
    assert set(profile.parent.iterdir()) == {profile}


@pytest.mark.parametrize("options", [
    {"bind": "0.0.0.0"}, {"bind": "::"}, {"bind": "224.0.0.1"}, {"bind": "fe80::1%en0"},
    {"bind": "localhost"}, {"name": "flower.test:8443"}, {"name": "https://flower.test"},
    {"name": "*.flower.test"}, {"name": "flower.test."}, {"name": "127.1"},
    {"name": "0x7f000001"}, {"name": "flower.test\n"}, {"port": 0}, {"port": True},
    {"cert": Path("only-cert.pem")},
])
def test_invalid_inputs_fail_before_generation(profile, options):
    defaults = {"bind": "127.0.0.1", "name": "flower.example.test", "port": 8443}
    with pytest.raises(tls.DashboardTLSError):
        tls.prepare_dashboard_tls(profile, **(defaults | options))
    assert set(profile.parent.iterdir()) == {profile}


@pytest.mark.parametrize("name", ["flower.example.test", "192.0.2.42", "2001:db8::42"])
def test_generated_material_completes_a_trusted_handshake(profile, name):
    material = _prepare(profile, name=name)
    assert material.context().minimum_version == ssl.TLSVersion.TLSv1_2
    assert _handshake(material, name) in {"TLSv1.2", "TLSv1.3"}
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(material, "other.example.test")
    ca = x509.load_pem_x509_certificate(material.ca_file.read_bytes())
    leaf = x509.load_pem_x509_certificate(material.certfile.read_bytes())
    leaf.verify_directly_issued_by(ca)
    assert b"PRIVATE KEY" not in material.ca_file.read_bytes()
    if os.name == "posix":
        for path in (material.ca_file, material.keyfile, material.keyfile.parent / "ca-identity.pem"):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(material.keyfile.parent.stat().st_mode) == 0o700


def test_leaf_reuses_material_then_renews_without_rotating_profile_ca(profile, monkeypatch):
    instant = tls._now()
    monkeypatch.setattr(tls, "_now", lambda: instant)
    initial = _prepare(profile)
    old_leaf, old_root = initial.certfile.read_bytes(), initial.ca_file.read_bytes()
    assert _prepare(profile).certfile.read_bytes() == old_leaf
    monkeypatch.setattr(tls, "_now", lambda: instant + timedelta(days=80))
    renewed = _prepare(profile)
    assert renewed.certfile.read_bytes() != old_leaf
    assert renewed.ca_file.read_bytes() == old_root
    before_rename = renewed.certfile.read_bytes()
    renamed = _prepare(profile, name="changed.example.test")
    assert renamed.certfile.read_bytes() != before_rename
    assert renamed.ca_file.read_bytes() == old_root


def test_profiles_in_same_directory_have_independent_cas(profile):
    other = profile.with_name("other.yaml")
    other.write_text("fixture configuration", encoding="utf-8")
    assert _prepare(other).ca_file.read_bytes() != _prepare(profile).ca_file.read_bytes()


def test_malformed_or_incomplete_identity_is_not_overwritten(profile):
    material = _prepare(profile)
    identity = material.ca_file.parent / "ca-identity.pem"
    secure.write_owned(identity, b"truncated private identity")
    old_root = material.ca_file.read_bytes()
    with pytest.raises(tls.DashboardTLSError):
        _prepare(profile)
    assert identity.read_bytes() == b"truncated private identity"
    identity.unlink()
    with pytest.raises(tls.DashboardTLSError, match="CA identity is missing"):
        _prepare(profile)
    assert material.ca_file.read_bytes() == old_root


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode and symlink checks")
def test_existing_insecure_mode_and_symlink_are_rejected(profile):
    material = _prepare(profile)
    material.keyfile.chmod(0o644)
    with pytest.raises(tls.DashboardTLSError):
        _prepare(profile)
    material.keyfile.chmod(0o600)
    elsewhere = material.keyfile.with_name("alias-target.pem")
    material.keyfile.rename(elsewhere)
    material.keyfile.symlink_to(elsewhere)
    with pytest.raises(tls.DashboardTLSError):
        _prepare(profile)
    assert material.keyfile.is_symlink()


def test_supplied_pem_requires_matching_name_and_usable_key(profile):
    automatic = _prepare(profile)
    identity = automatic.certfile.read_bytes()
    certificate = x509.load_pem_x509_certificate(identity).public_bytes(serialization.Encoding.PEM)
    key_data = identity[len(certificate):]
    cert, key = profile.parent / "supplied.crt", profile.parent / "supplied.key"
    secure.write_owned(cert, certificate, private_parent=False)
    secure.write_owned(key, key_data, private_parent=False)
    if os.name == "posix":
        cert.chmod(0o644)
    supplied = _prepare(profile, cert=cert, key=key)
    assert (supplied.certfile, supplied.keyfile, supplied.ca_file) == (cert, key, None)
    with pytest.raises(tls.DashboardTLSError, match="does not cover"):
        _prepare(profile, name="other.example.test", cert=cert, key=key)
    secure.write_owned(key, b"malformed key", private_parent=False)
    with pytest.raises(tls.DashboardTLSError):
        _prepare(profile, cert=cert, key=key)
