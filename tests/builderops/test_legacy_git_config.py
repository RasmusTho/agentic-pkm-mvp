from pathlib import Path

import pytest

from app.builderops.legacy_git_config import ConfigError, check


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch):
    root = tmp_path / 'agentic-pkm-mvp'
    other = tmp_path / 'candidate'
    common = root / '.git'
    linked = common / 'worktrees' / 'candidate'
    linked.mkdir(parents=True)
    other.mkdir()
    (other / '.git').write_text(f'gitdir: {linked}\n')
    (linked / 'commondir').write_text('../..\n')
    monkeypatch.setattr('app.builderops.legacy_git_config.QUALIFIED_COMMON', common)
    monkeypatch.setattr('app.builderops.legacy_git_config._qualified_home', lambda: tmp_path)
    (common / 'config').write_text('[core]\n repositoryformatversion = 0\n[remote "origin"]\n url = https://example.invalid/repo\n')
    return root, other, common, linked


def test_safe_linked_checkout(checkout):
    root, other, _, _ = checkout
    check(cwd=root, worktree=other)


@pytest.mark.parametrize('directive', [
    '[include]\n path = /ignored/secret\n',
    '[includeIf "gitdir:foo"]\n path = /ignored/secret\n',
    '[filter "bad"]\n process = touch /tmp/never\n',
    '[url "https://other.invalid/"]\n insteadOf = https://github.com/\n',
    '[http "https://github.com/"]\n extraHeader = Authorization: redacted\n',
    '[credential]\n helper = evil\n',
    '[core]\n hooksPath = /tmp/evil\n',
])
def test_rejects_dangerous_configuration(checkout, directive, capsys):
    root, other, common, _ = checkout
    (common / 'config').write_text(directive)
    with pytest.raises(ConfigError):
        check(cwd=root, worktree=other)
    assert '/ignored/secret' not in str(capsys.readouterr())


def test_refuses_linked_configuration_and_symlink(checkout, tmp_path):
    root, other, common, linked = checkout
    (linked / 'config.worktree').write_text('[core]\n bare = false\n')
    with pytest.raises(ConfigError):
        check(cwd=root, worktree=other)
    (linked / 'config.worktree').unlink()
    (common / 'config').unlink()
    (common / 'config').symlink_to(tmp_path / 'secret')
    with pytest.raises(ConfigError):
        check(cwd=root, worktree=other)


def test_detects_drift_on_later_check(checkout):
    root, other, common, _ = checkout
    check(cwd=root, worktree=other)
    (common / 'config').write_text('[include]\n path = /ignored/secret\n')
    with pytest.raises(ConfigError):
        check(cwd=root, worktree=other)


def test_global_include_refused_and_safe_helper_not_run(tmp_path):
    from app.builderops.legacy_git_config import _screen

    marker = tmp_path / 'executed'
    with pytest.raises(ConfigError):
        _screen(b'[include]\n path = /ignored/secret\n', global_config=True)
    _screen(b'[credential]\n helper = osxkeychain\n', global_config=True)
    with pytest.raises(ConfigError):
        _screen(f'[credential]\n helper = !touch {marker}\n'.encode(), global_config=True)
    assert not marker.exists()


def test_bounded_read_handles_short_reads(tmp_path, monkeypatch):
    from app.builderops import legacy_git_config

    path = tmp_path / 'config'
    content = b'[include]\n path = /ignored/secret\n'
    path.write_bytes(content)
    original_read = legacy_git_config.os.read
    monkeypatch.setattr(legacy_git_config.os, 'read', lambda fd, size: original_read(fd, min(size, 3)))
    assert legacy_git_config._read(path) == content
    with pytest.raises(ConfigError):
        legacy_git_config._screen(legacy_git_config._read(path))


def test_qualified_gh_helpers_only(tmp_path, monkeypatch):
    from app.builderops import legacy_git_config

    gh = tmp_path / 'gh'
    gh.write_text('not executed')
    monkeypatch.setattr(legacy_git_config.shutil, 'which', lambda name: str(gh))
    for host in ('github.com', 'gist.github.com'):
        config = f'[credential "https://{host}"]\n helper =\n helper = !{gh} auth git-credential\n'
        legacy_git_config._screen(config.encode(), global_config=True)
    for host, command in (
        ('example.com', f'!{gh} auth git-credential'),
        ('github.com', f'"!{gh} auth git-credential;evil"'),
        ('github.com', '!/other/gh auth git-credential'),
    ):
        config = f'[credential "https://{host}"]\n helper = {command}\n'
        with pytest.raises(ConfigError):
            legacy_git_config._screen(config.encode(), global_config=True)


def test_worktree_config_extension_only_with_both_files_absent(checkout):
    root, other, common, linked = checkout
    (common / 'config').write_text('[extensions]\n worktreeConfig = true\n')
    check(cwd=root, worktree=other)
    for directory in (common, linked):
        config = directory / 'config.worktree'
        config.write_text('[core]\n bare = false\n')
        with pytest.raises(ConfigError):
            check(cwd=root, worktree=other)
        config.unlink()


def test_invalid_workspace_stops_actual_pickup_before_config_git_or_claim(tmp_path, monkeypatch):
    from app.builderops import legacy_git_config, legacy_owner_recovery

    def forbidden(*args, **kwargs):
        pytest.fail('invalid workspace reached a forbidden operation')

    monkeypatch.setattr(legacy_git_config, 'check_host_config', forbidden)
    monkeypatch.setattr(legacy_git_config, 'check', forbidden)
    monkeypatch.setattr(legacy_owner_recovery.subprocess, 'run', forbidden)
    monkeypatch.setattr(legacy_owner_recovery, '_execute_operator_pickup', forbidden)
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    with pytest.raises(legacy_owner_recovery.RecoveryEvidenceError, match='workspace boundary'):
        legacy_owner_recovery.execute_operator_pickup(
            run_state_root=tmp_path / 'state', cwd=checkout, issue=6601, pr=1,
            worktree=checkout, agent='agent', session='session', comment_id=1,
            workspace_root=checkout,
        )


def test_wrong_effective_git_refused_before_config_access(monkeypatch):
    from app.builderops import legacy_git_config

    monkeypatch.setattr(legacy_git_config.shutil, 'which', lambda name: '/other/git')
    monkeypatch.setattr(legacy_git_config, '_read', lambda *args, **kwargs: pytest.fail('read config'))
    with pytest.raises(ConfigError, match='executable'):
        legacy_git_config.check_host_config()


def test_candidate_outside_common_refused_before_commondir_read(checkout, tmp_path, monkeypatch):
    from app.builderops import legacy_git_config

    root, other, _, _ = checkout
    outside = tmp_path / 'outside'
    outside.mkdir()
    (other / '.git').write_text(f'gitdir: {outside}\n')
    original_read = legacy_git_config._read

    def guarded_read(path, **kwargs):
        if path == outside / 'commondir':
            pytest.fail('opened untrusted candidate commondir')
        return original_read(path, **kwargs)

    monkeypatch.setattr(legacy_git_config, '_read', guarded_read)
    with pytest.raises(ConfigError):
        check(cwd=root, worktree=other)


def test_source_outside_common_refused_before_commondir_read(checkout, tmp_path, monkeypatch):
    from app.builderops import legacy_git_config

    root, other, _, _ = checkout
    source = tmp_path / 'source'
    source.mkdir()
    outside = tmp_path / 'outside-source'
    outside.mkdir()
    (source / '.git').write_text(f'gitdir: {outside}\n')
    original_read = legacy_git_config._read

    def guarded_read(path, **kwargs):
        if path == outside / 'commondir':
            pytest.fail('opened untrusted source commondir')
        return original_read(path, **kwargs)

    monkeypatch.setattr(legacy_git_config, '_read', guarded_read)
    with pytest.raises(ConfigError):
        check(cwd=source, worktree=other)


def test_candidate_entrypoint_refuses_include_before_source_git(tmp_path, monkeypatch):
    import subprocess
    from app.builderops import legacy_git_config, legacy_owner_recovery

    source = tmp_path / 'agentic-pkm-mvp'
    subprocess.run(['git', 'init', '-b', 'main', str(source)], check=True, capture_output=True)
    (source / '.gitignore').write_text('ignored-poison\n', encoding='utf-8')
    marker = source / 'ignored-poison'
    marker.write_text('[invalid\n', encoding='utf-8')
    config = source / '.git/config'
    with config.open('a', encoding='utf-8') as stream:
        stream.write(f'\n[include]\n path = {marker}\n')
    monkeypatch.setattr(legacy_git_config, 'QUALIFIED_COMMON', (source / '.git').resolve())
    monkeypatch.setattr(legacy_git_config, '_qualified_home', lambda: tmp_path)
    monkeypatch.setattr(legacy_git_config, 'check_host_config', lambda: None)
    monkeypatch.setattr(legacy_owner_recovery, '_git_read',
                        lambda *_args, **_kwargs: pytest.fail('source Git ran before config refusal'))
    with pytest.raises(legacy_owner_recovery.RecoveryEvidenceError, match='Git configuration'):
        legacy_owner_recovery.read_clean_candidate(cwd=source, worktree=source)


def test_direct_candidate_read_refuses_inherited_config_before_git(checkout, monkeypatch):
    from app.builderops import legacy_owner_recovery

    root, other, _, _ = checkout
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'include.path')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', '/ignored/secret')
    monkeypatch.setattr(legacy_owner_recovery.subprocess, 'run',
                        lambda *args, **kwargs: pytest.fail('Git ran before refusal'))
    with pytest.raises(legacy_owner_recovery.RecoveryEvidenceError, match='configuration'):
        legacy_owner_recovery.read_clean_candidate(cwd=root, worktree=other)


def test_host_home_override_is_refused(tmp_path, monkeypatch):
    from app.builderops.legacy_git_config import _qualified_home
    monkeypatch.setenv('HOME', str(tmp_path))
    with pytest.raises(ConfigError, match='host home'):
        _qualified_home()
