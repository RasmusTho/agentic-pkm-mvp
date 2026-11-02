"""Exercise the real public-certificate CLI with synthetic identities only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scripts import check_model_access_certificates as subject


@pytest.fixture
def public_chain(tmp_path):
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic CA')])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    def leaf(name, purpose, before=-1, after=120, ip='100.64.0.10'):
        key = ec.generate_private_key(ec.SECP256R1())
        builder = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
                   .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now + timedelta(days=before)).not_valid_after(now + timedelta(days=after))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False))
        if ip:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]),
                                            critical=False)
        return builder.sign(ca_key, hashes.SHA256())
    paths = {}
    for name, cert in {
        'ca': ca,
        'server': leaf('server', ExtendedKeyUsageOID.SERVER_AUTH),
        'client': leaf('client', ExtendedKeyUsageOID.CLIENT_AUTH, ip=None),
        'expired': leaf('expired', ExtendedKeyUsageOID.SERVER_AUTH, before=-10, after=-1),
        'future': leaf('future', ExtendedKeyUsageOID.SERVER_AUTH, before=1, after=120),
        'near': leaf('near', ExtendedKeyUsageOID.SERVER_AUTH, after=1),
        'wrong_purpose': leaf('wrong', ExtendedKeyUsageOID.CLIENT_AUTH),
    }.items():
        path = tmp_path / (name + '.crt')
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        paths[name] = path
    return paths


def cli(paths, *, channel='dev', server='server', client='client', ca='ca', server_ip='100.64.0.10'):
    command = [sys.executable, str(Path(subject.__file__)), '--channel', channel,
               '--server', str(paths[server]), '--client', str(paths[client]), '--ca', str(paths[ca]),
               '--server-ip', server_ip, '--min-days', '30']
    return subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)


def test_cli_checks_valid_public_chain_and_refuses_prod(public_chain, tmp_path, monkeypatch):
    for channel in ('dev', 'test'):
        result = cli(public_chain, channel=channel)
        payload = json.loads(result.stdout)
        assert result.returncode == 0 and payload['status'] == 'valid_public_files'
        assert payload['channel'] == channel and set(payload['certificates']) == {'server', 'client', 'ca'}
        assert str(tmp_path) not in result.stdout and not result.stderr
    result = subprocess.run(
        [sys.executable, str(Path(subject.__file__)), '--channel', 'prod', '--server', str(tmp_path / 'missing'),
         '--client', str(tmp_path / 'missing'), '--ca', str(tmp_path / 'missing'), '--server-ip', '100.64.0.10'],
        capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode != 0 and json.loads(result.stdout) == {'status': 'unqualified'}
    assert str(tmp_path) not in result.stdout + result.stderr
    monkeypatch.setattr(subject, 'PublicFile', lambda *_args: pytest.fail('PROD opened a file'))
    with pytest.raises(subject.Refused):
        subject.check_certificates(channel='prod', server='x', client='x', ca='x',
                                   server_ip='100.64.0.10', min_days=30)


@pytest.mark.parametrize('server,server_ip', [
    ('expired', '100.64.0.10'), ('future', '100.64.0.10'), ('near', '100.64.0.10'),
    ('wrong_purpose', '100.64.0.10'), ('server', '100.64.0.11'),
])
def test_cli_refuses_invalid_and_expiring_public_identity(public_chain, tmp_path, server, server_ip):
    result = cli(public_chain, server=server, server_ip=server_ip)
    assert result.returncode != 0 and json.loads(result.stdout) == {'status': 'unqualified'}
    assert str(tmp_path) not in result.stdout + result.stderr
    # A syntactically valid, but different, synthetic trust anchor is refused.
    wrong = cli(public_chain, ca='client')
    assert wrong.returncode != 0 and json.loads(wrong.stdout) == {'status': 'unqualified'}
    wrong_client = cli(public_chain, client='server')
    assert wrong_client.returncode != 0 and json.loads(wrong_client.stdout) == {'status': 'unqualified'}
    malformed = tmp_path / 'malformed.crt'
    malformed.write_text('not a public certificate')
    public_chain['invalid'] = malformed
    assert cli(public_chain, server='invalid').returncode != 0
    public_chain['invalid'] = tmp_path / 'missing.crt'
    assert cli(public_chain, server='invalid').returncode != 0


def test_cli_rejects_unsafe_or_changed_public_inputs(public_chain, tmp_path, monkeypatch):
    original = public_chain['server']
    symlink = tmp_path / 'link.crt'
    symlink.symlink_to(original)
    public_chain['link'] = symlink
    for path in (symlink, tmp_path, tmp_path / 'missing.crt'):
        public_chain['candidate'] = path
        result = cli(public_chain, server='candidate')
        assert result.returncode != 0 and json.loads(result.stdout) == {'status': 'unqualified'}
        assert str(tmp_path) not in result.stdout + result.stderr
    mixed = tmp_path / 'mixed.crt'
    mixed.write_bytes(original.read_bytes() + b'-----BEGIN PRIVATE KEY-----\nPRIVATE-SYNTHETIC\n')
    public_chain['candidate'] = mixed
    result = cli(public_chain, server='candidate')
    assert result.returncode != 0 and 'PRIVATE-SYNTHETIC' not in result.stdout + result.stderr
    mixed.write_bytes(b'-----BEGIN CERTIFICATE-----\n-----BEGIN PRIVATE KEY-----\nPRIVATE-SYNTHETIC\n')
    real_read = subject.os.read
    consumed = bytearray()
    def record_read(fd, count):
        result = real_read(fd, count)
        consumed.extend(result)
        return result
    monkeypatch.setattr(subject.os, 'read', record_read)
    with pytest.raises(subject.Refused):
        subject.check_certificates(channel='dev', server=str(mixed), client=str(public_chain['client']),
                                   ca=str(public_chain['ca']), server_ip='100.64.0.10', min_days=30)
    assert b'PRIVATE-SYNTHETIC' not in consumed
    monkeypatch.undo()
    growing = tmp_path / 'growing.crt'
    growing.write_bytes(original.read_bytes())
    original_size = growing.stat().st_size
    reads = 0
    def growing_read(fd, count):
        nonlocal reads
        if os.fstat(fd).st_ino == growing.stat().st_ino:
            reads += 1
            if os.lseek(fd, 0, os.SEEK_CUR) >= original_size - 1:
                with growing.open('ab') as output:
                    output.write(b' ')
        return real_read(fd, count)
    monkeypatch.setattr(subject.os, 'read', growing_read)
    with pytest.raises(subject.Refused):
        subject.check_certificates(channel='dev', server=str(growing), client=str(public_chain['client']),
                                   ca=str(public_chain['ca']), server_ip='100.64.0.10', min_days=30)
    assert reads <= original_size + 1
    monkeypatch.undo()
    mixed.write_bytes(b'A' * 4097)
    assert cli(public_chain, server='candidate').returncode != 0
    monkeypatch.setattr(subject, '_OPENSSL', str(tmp_path / 'absent'))
    with pytest.raises(subject.Refused):
        subject.check_certificates(channel='dev', server=str(original), client=str(public_chain['client']),
                                   ca=str(public_chain['ca']), server_ip='100.64.0.10', min_days=30)
    monkeypatch.undo()
    original_verify = subject._verify_chain
    replaced = False
    def change_after_check(ca, leaf, purpose):
        nonlocal replaced
        original_verify(ca, leaf, purpose)
        if not replaced:
            replacement = tmp_path / 'replacement.crt'
            replacement.write_bytes(original.read_bytes())
            replacement.replace(original)
            replaced = True
    monkeypatch.setattr(subject, '_verify_chain', change_after_check)
    with pytest.raises(subject.Refused):
        subject.check_certificates(channel='dev', server=str(original), client=str(public_chain['client']),
                                   ca=str(public_chain['ca']), server_ip='100.64.0.10', min_days=30)
