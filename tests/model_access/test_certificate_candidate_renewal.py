"""Real cryptography with disposable identities; no operational signer is used."""
from __future__ import annotations

import base64
import builtins
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import os
import socket
import subprocess

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier

from app.model_access import certificate_renewal_candidate as subject


@pytest.fixture
def fixture():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    issuer_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    issuer_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic CA')])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic caller')])
    def issuer(*, is_ca=True, before=-1, after=365, signing=True, purpose=None, constrained=False):
        builder = (x509.CertificateBuilder().subject_name(issuer_name).issuer_name(issuer_name)
                   .public_key(issuer_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now + timedelta(days=before)).not_valid_after(now + timedelta(days=after))
                   .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
                   .add_extension(x509.KeyUsage(False, False, False, False, False, signing, signing, False, False),
                                  critical=True))
        if purpose is not None:
            builder = builder.add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
        if constrained:
            builder = builder.add_extension(x509.NameConstraints(
                permitted_subtrees=[x509.DNSName('allowed.example')], excluded_subtrees=None), critical=True)
        return builder.sign(issuer_key, hashes.SHA256())
    def csr(*, names=(), eku=None, key=leaf_key, extra=False):
        builder = x509.CertificateSigningRequestBuilder().subject_name(leaf_name)
        if names:
            builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
        if eku:
            builder = builder.add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
        if extra:
            builder = builder.add_extension(x509.UnrecognizedExtension(ObjectIdentifier('1.2.3.4'), b'private'),
                                            critical=False)
        return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    def policy(cert, *, names=(), purpose='server'):
        public = leaf_key.public_key().public_bytes(serialization.Encoding.DER,
                                                    serialization.PublicFormat.SubjectPublicKeyInfo)
        return subject.CandidatePolicy(issuer_sha256=cert.fingerprint(hashes.SHA256()),
                                       subject_key_sha256=hashlib.sha256(public).digest(),
                                       subject=leaf_name, names=tuple(names), purpose=purpose,
                                       not_before=now - timedelta(minutes=1),
                                       not_after=now + timedelta(days=30))
    return now, issuer_key, leaf_key, issuer, csr, policy


@pytest.mark.parametrize('purpose,names', [
    ('server', (x509.IPAddress(ipaddress.ip_address('192.0.2.5')), x509.DNSName('synthetic.example'))),
    ('client', (x509.UniformResourceIdentifier('urn:synthetic:client'),)),
    ('client', ()),
])
def test_synthetic_candidates_bind_requested_identity(fixture, purpose, names):
    _now, issuer_key, leaf_key, make_issuer, make_csr, make_policy = fixture
    issuer = make_issuer()
    usage = ExtendedKeyUsageOID.SERVER_AUTH if purpose == 'server' else ExtendedKeyUsageOID.CLIENT_AUTH
    csr_pem = make_csr(names=names, eku=usage)
    policy = make_policy(issuer, names=names, purpose=purpose)
    result = subject.create_candidate(csr_pem, issuer=issuer, issuer_key=issuer_key, policy=policy)
    cert = x509.load_pem_x509_certificate(result)
    cert.verify_directly_issued_by(issuer)
    assert cert.subject == policy.subject
    assert cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) == (
        leaf_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
    assert cert.not_valid_before_utc == policy.not_before
    assert cert.not_valid_after_utc == policy.not_after
    assert tuple(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) == (usage,)
    if names:
        assert set(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value) == set(names)
    else:
        with pytest.raises(x509.ExtensionNotFound):
            cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca


def test_invalid_candidate_inputs_refuse_without_disclosure(fixture):
    now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    names = (x509.IPAddress(ipaddress.ip_address('192.0.2.5')),)
    other = (x509.IPAddress(ipaddress.ip_address('192.0.2.6')),)
    issuer = make_issuer()
    policy = make_policy(issuer, names=names)
    valid = make_csr(names=names, eku=ExtendedKeyUsageOID.SERVER_AUTH)
    der = bytearray(x509.load_pem_x509_csr(valid).public_bytes(serialization.Encoding.DER))
    der[-1] ^= 1
    invalid_signature = (b'-----BEGIN CERTIFICATE REQUEST-----\n' + base64.encodebytes(bytes(der))
                         + b'-----END CERTIFICATE REQUEST-----\n')
    wrong_ca = make_issuer(is_ca=False)
    wrong_usage = make_issuer(signing=False)
    wrong_eku = make_issuer(purpose=ExtendedKeyUsageOID.CLIENT_AUTH)
    expired_ca = make_issuer(before=-365, after=-1)
    restricted_ca = make_issuer(constrained=True)
    attempts = [
        (b'PRIVATE-SYNTHETIC', issuer, issuer_key, policy),
        (valid + valid, issuer, issuer_key, policy),
        (b'A' * 65_537, issuer, issuer_key, policy),
        (invalid_signature, issuer, issuer_key, policy),
        (valid, issuer, ec.generate_private_key(ec.SECP256R1()), policy),
        (valid, issuer, issuer_key, replace(policy, issuer_sha256=b'\x00' * 32)),
        (valid, issuer, issuer_key, replace(policy, subject_key_sha256=b'\x01' * 32)),
        (valid, issuer, issuer_key, replace(policy, subject=x509.Name([]))),
        (valid, issuer, issuer_key, replace(policy, names=other)),
        (make_csr(names=(*names, *names)), issuer, issuer_key, policy),
        (make_csr(names=names, eku=ExtendedKeyUsageOID.CLIENT_AUTH), issuer, issuer_key, policy),
        (make_csr(names=names, extra=True), issuer, issuer_key, policy),
        (valid, wrong_ca, issuer_key, make_policy(wrong_ca, names=names)),
        (valid, wrong_usage, issuer_key, make_policy(wrong_usage, names=names)),
        (valid, wrong_eku, issuer_key, make_policy(wrong_eku, names=names)),
        (valid, expired_ca, issuer_key, make_policy(expired_ca, names=names)),
        (valid, restricted_ca, issuer_key, make_policy(restricted_ca, names=names)),
        (valid, issuer, issuer_key, replace(policy, not_after=now - timedelta(seconds=1))),
        (valid, issuer, issuer_key, replace(policy, not_after=now + timedelta(days=367))),
        (valid, issuer, issuer_key, replace(policy, not_after=now + timedelta(days=400))),
        (valid, issuer, issuer_key, replace(policy, not_before=now.replace(tzinfo=None))),
        (valid, issuer, issuer_key, replace(policy, purpose='other')),
    ]
    for csr_pem, candidate_issuer, key, candidate_policy in attempts:
        with pytest.raises(subject.CandidateRefused, match='^candidate_unavailable$') as error:
            subject.create_candidate(csr_pem, issuer=candidate_issuer, issuer_key=key, policy=candidate_policy)
        assert 'PRIVATE-SYNTHETIC' not in str(error.value)
        assert error.value.__cause__ is None


def test_candidate_builder_has_no_operational_side_effects(fixture, monkeypatch):
    _now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    names = (x509.IPAddress(ipaddress.ip_address('192.0.2.5')),)
    issuer = make_issuer()
    csr_pem = make_csr(names=names)
    policy = make_policy(issuer, names=names)
    def unexpected(*_args, **_kwargs):
        pytest.fail('unexpected filesystem or network effect')
    monkeypatch.setattr(builtins, 'open', unexpected)
    monkeypatch.setattr(os, 'open', unexpected)
    monkeypatch.setattr(socket, 'socket', unexpected)
    monkeypatch.setattr(socket, 'create_connection', unexpected)
    result = subject.create_candidate(csr_pem, issuer=issuer, issuer_key=issuer_key, policy=policy)
    assert result.startswith(b'-----BEGIN CERTIFICATE-----')
    assert 'not an issuance authorization' in subject.create_candidate.__doc__
    assert 'PRIVATE' not in repr(policy)


@pytest.mark.parametrize('purpose', ['server', 'client'])
def test_openssl_accepts_synthetic_candidate_for_intended_tls_purpose(fixture, tmp_path, purpose):
    _now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    issuer = make_issuer()
    names = (x509.DNSName('synthetic.example'),)
    policy = make_policy(issuer, names=names, purpose=purpose)
    candidate = subject.create_candidate(make_csr(names=names), issuer=issuer,
                                         issuer_key=issuer_key, policy=policy)
    ca_file = tmp_path / 'ca.pem'
    leaf_file = tmp_path / 'leaf.pem'
    ca_file.write_bytes(issuer.public_bytes(serialization.Encoding.PEM))
    leaf_file.write_bytes(candidate)
    result = subprocess.run(['openssl', 'verify', '-CAfile', str(ca_file), '-purpose',
                             'sslserver' if purpose == 'server' else 'sslclient', str(leaf_file)],
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


def test_candidate_refuses_expiry_within_current_x509_second(fixture, monkeypatch):
    now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    current = now.replace(microsecond=500_000)
    monkeypatch.setattr(subject, '_now', lambda: current)
    issuer = make_issuer()
    policy = make_policy(issuer)
    for before, after in (
        (now - timedelta(seconds=1), now.replace(microsecond=700_000)),
        (now.replace(microsecond=100_000), now.replace(microsecond=900_000)),
        (now.replace(microsecond=100_000), now + timedelta(days=1)),
    ):
        with pytest.raises(subject.CandidateRefused, match='^candidate_unavailable$'):
            subject.create_candidate(make_csr(), issuer=issuer, issuer_key=issuer_key,
                                     policy=replace(policy, not_before=before, not_after=after))


def test_candidate_refuses_if_expired_during_signing(fixture, monkeypatch):
    now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    observations = iter((now, now + timedelta(seconds=2), now + timedelta(seconds=2)))
    monkeypatch.setattr(subject, '_now', lambda: next(observations))
    issuer = make_issuer()
    policy = replace(make_policy(issuer), not_after=now + timedelta(seconds=1))
    with pytest.raises(subject.CandidateRefused, match='^candidate_unavailable$'):
        subject.create_candidate(make_csr(), issuer=issuer, issuer_key=issuer_key, policy=policy)


def test_subsecond_policy_start_cannot_be_issued_early(fixture, monkeypatch):
    now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    monkeypatch.setattr(subject, '_now', lambda: now + timedelta(seconds=1))
    issuer = make_issuer()
    policy = replace(make_policy(issuer), not_before=now.replace(microsecond=500_000))
    with pytest.raises(subject.CandidateRefused, match='^candidate_unavailable$'):
        subject.create_candidate(make_csr(), issuer=issuer, issuer_key=issuer_key, policy=policy)


def test_subsecond_timezone_offset_cannot_issue_before_policy(fixture, monkeypatch):
    now, issuer_key, _leaf_key, make_issuer, make_csr, make_policy = fixture
    monkeypatch.setattr(subject, '_now', lambda: now + timedelta(seconds=1))
    issuer = make_issuer()
    half_second = timezone(timedelta(microseconds=500_000))
    local_start = now.replace(tzinfo=half_second)
    policy = replace(make_policy(issuer), not_before=local_start)
    with pytest.raises(subject.CandidateRefused, match='^candidate_unavailable$'):
        subject.create_candidate(make_csr(), issuer=issuer, issuer_key=issuer_key, policy=policy)
