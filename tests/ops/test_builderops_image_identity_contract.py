from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_builderops_identity_is_fixed_before_package_install() -> None:
    """Package-created groups must not change the host-secret reader identity."""

    dockerfile = (ROOT / "Dockerfile.builderops").read_text(encoding="utf-8")
    group_creation = "addgroup --system --gid 101 builderops"
    user_creation = "adduser --system --uid 100 --ingroup builderops"
    package_install = "RUN apt-get update"

    assert group_creation in dockerfile
    assert user_creation in dockerfile
    assert dockerfile.index(group_creation) < dockerfile.index(package_install)
    assert dockerfile.index(user_creation) < dockerfile.index(package_install)
    assert "addgroup --system builderops" not in dockerfile
