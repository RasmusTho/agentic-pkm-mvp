"""Construct an in-memory certificate candidate, never operational authority.

The caller must separately establish signer custody, operation ownership and
publication authority. This module neither discovers credentials nor provides
any file, network, scheduling, deployment or recovery entry point.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
from typing import Literal

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, ed448, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

_MAX_CSR_BYTES = 65_536
_MAX_ISSUER_BYTES = 65_536
_MAX_SUBJECT_BYTES = 4_096
_MAX_NAMES = 32
_MAX_NAME_BYTES = 2_048
_MAX_LIFETIME = timedelta(days=366)
_CSR_BEGIN = b'-----BEGIN CERTIFICATE REQUEST-----'
_CSR_END = b'-----END CERTIFICATE REQUEST-----'


class CandidateRefused(ValueError):
    """A candidate could not be verified against the supplied policy."""


@dataclass(frozen=True, repr=False)
class CandidatePolicy:
    """Exact public identity chosen by a separately authorized caller."""

    issuer_sha256: bytes = field(repr=False)
    subject_key_sha256: bytes = field(repr=False)
    subject: x509.Name = field(repr=False)
    names: tuple[x509.GeneralName, ...] = field(repr=False)
    purpose: Literal['server', 'client']
    not_before: datetime
    not_after: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_key_bytes(key: object) -> bytes:
    if not isinstance(key, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey,
                            ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
        raise ValueError
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _validate_names(names: object) -> tuple[x509.GeneralName, ...]:
    if type(names) is not tuple or len(names) > _MAX_NAMES:
        raise ValueError
    for name in names:
        if type(name) not in (x509.DNSName, x509.IPAddress, x509.UniformResourceIdentifier):
            raise ValueError
        if isinstance(name, x509.IPAddress):
            if type(name.value) not in (ipaddress.IPv4Address, ipaddress.IPv6Address):
                raise ValueError
        elif not name.value or len(name.value.encode('utf-8')) > _MAX_NAME_BYTES:
            raise ValueError
    if len(set(names)) != len(names):
        raise ValueError
    return names


def _validate_csr_extensions(csr: x509.CertificateSigningRequest, policy: CandidatePolicy) -> None:
    actual_names: tuple[x509.GeneralName, ...] = ()
    expected_usage = (ExtendedKeyUsageOID.SERVER_AUTH if policy.purpose == 'server'
                      else ExtendedKeyUsageOID.CLIENT_AUTH)
    for extension in csr.extensions:
        value = extension.value
        if isinstance(value, x509.SubjectAlternativeName):
            actual_names = tuple(value)
        elif isinstance(value, x509.ExtendedKeyUsage):
            if tuple(value) != (expected_usage,):
                raise ValueError
        elif isinstance(value, x509.BasicConstraints):
            if value.ca or value.path_length is not None:
                raise ValueError
        else:
            # CSR-supplied restrictions are never silently copied or ignored.
            raise ValueError
    names = _validate_names(actual_names)
    if len(names) != len(policy.names) or set(names) != set(policy.names):
        raise ValueError


def _load_csr(raw: bytes) -> x509.CertificateSigningRequest:
    stripped = raw.strip()
    if not stripped.startswith(_CSR_BEGIN) or not stripped.endswith(_CSR_END):
        raise ValueError
    body = stripped[len(_CSR_BEGIN):-len(_CSR_END)]
    encoded = b''.join(body.split())
    decoded = base64.b64decode(encoded, validate=True)
    csr = x509.load_der_x509_csr(decoded)
    if csr.public_bytes(serialization.Encoding.DER) != decoded:
        raise ValueError
    return csr


def create_candidate(csr_pem: bytes, *, issuer: x509.Certificate, issuer_key: object,
                     policy: CandidatePolicy) -> bytes:
    """Return a verified PEM candidate; this is not an issuance authorization."""
    try:
        if type(csr_pem) is not bytes or not 0 < len(csr_pem) <= _MAX_CSR_BYTES:
            raise ValueError
        if not isinstance(issuer, x509.Certificate) or type(policy) is not CandidatePolicy:
            raise ValueError
        if not isinstance(issuer_key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey,
                                       ed25519.Ed25519PrivateKey, ed448.Ed448PrivateKey)):
            raise ValueError
        if (type(policy.issuer_sha256) is not bytes or len(policy.issuer_sha256) != 32
                or type(policy.subject_key_sha256) is not bytes or len(policy.subject_key_sha256) != 32
                or not isinstance(policy.subject, x509.Name) or len(policy.subject) == 0
                or len(policy.subject.public_bytes()) > _MAX_SUBJECT_BYTES
                or policy.purpose not in ('server', 'client')):
            raise ValueError
        _validate_names(policy.names)
        if len(issuer.public_bytes(serialization.Encoding.DER)) > _MAX_ISSUER_BYTES:
            raise ValueError
        if issuer.fingerprint(hashes.SHA256()) != policy.issuer_sha256:
            raise ValueError
        if _public_key_bytes(issuer.public_key()) != _public_key_bytes(issuer_key.public_key()):
            raise ValueError
        # Refuse CA restrictions we do not implement rather than issue a leaf
        # that violates name constraints or another unexamined issuer policy.
        supported_ca_extensions = (x509.BasicConstraints, x509.KeyUsage, x509.ExtendedKeyUsage,
                                   x509.SubjectKeyIdentifier, x509.AuthorityKeyIdentifier)
        if any(not isinstance(extension.value, supported_ca_extensions)
               for extension in issuer.extensions):
            raise ValueError
        if not issuer.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError
        try:
            usage = issuer.extensions.get_extension_for_class(x509.KeyUsage).value
        except x509.ExtensionNotFound:
            pass  # An absent KeyUsage imposes no key-usage restriction.
        else:
            if not usage.key_cert_sign:
                raise ValueError
        purpose = (ExtendedKeyUsageOID.SERVER_AUTH if policy.purpose == 'server'
                   else ExtendedKeyUsageOID.CLIENT_AUTH)
        try:
            issuer_usage = issuer.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        except x509.ExtensionNotFound:
            pass
        else:
            if purpose not in issuer_usage and ExtendedKeyUsageOID.ANY_EXTENDED_KEY_USAGE not in issuer_usage:
                raise ValueError
        now = _now()
        before, after = policy.not_before, policy.not_after
        if (not isinstance(before, datetime) or not isinstance(after, datetime)
                or before.utcoffset() is None or after.utcoffset() is None):
            raise ValueError
        # X.509 uses UTC whole seconds; check after conversion, since Python
        # accepts offsets with fractional seconds too.
        before = before.astimezone(timezone.utc)
        after = after.astimezone(timezone.utc)
        if before.microsecond != 0 or after.microsecond != 0:
            raise ValueError
        if (before > now or after <= now or after <= before
                or after - before > _MAX_LIFETIME
                or before < issuer.not_valid_before_utc or after > issuer.not_valid_after_utc
                or issuer.not_valid_before_utc > now or issuer.not_valid_after_utc <= now):
            raise ValueError
        csr = _load_csr(csr_pem)
        if (not csr.is_signature_valid or csr.subject != policy.subject
                or hashlib.sha256(_public_key_bytes(csr.public_key())).digest() != policy.subject_key_sha256):
            raise ValueError
        _validate_csr_extensions(csr, policy)
        builder = (x509.CertificateBuilder().subject_name(policy.subject).issuer_name(issuer.subject)
                   .public_key(csr.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(before).not_valid_after(after)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False))
        if policy.names:
            builder = builder.add_extension(x509.SubjectAlternativeName(policy.names), critical=False)
        algorithm = None if isinstance(issuer_key, (ed25519.Ed25519PrivateKey, ed448.Ed448PrivateKey)) else hashes.SHA256()
        certificate = builder.sign(issuer_key, algorithm)
        certificate.verify_directly_issued_by(issuer)
        if (certificate.subject != policy.subject
                or hashlib.sha256(_public_key_bytes(certificate.public_key())).digest() != policy.subject_key_sha256
                or certificate.not_valid_before_utc != before
                or certificate.not_valid_after_utc != after
                or certificate.not_valid_before_utc > _now()
                or certificate.not_valid_after_utc <= _now()
                or certificate.not_valid_after_utc <= certificate.not_valid_before_utc
                or tuple(certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) != (purpose,)):
            raise ValueError
        try:
            actual = tuple(certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
        except x509.ExtensionNotFound:
            actual = ()
        if len(actual) != len(policy.names) or set(actual) != set(policy.names):
            raise ValueError
        return certificate.public_bytes(serialization.Encoding.PEM)
    except Exception:
        raise CandidateRefused('candidate_unavailable') from None
