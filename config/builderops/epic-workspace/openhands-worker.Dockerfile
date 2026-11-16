# Bounded #6618 successor to the locally qualified OpenHands 1.62 / Python 3.12 image.
# Build only on the trusted host with --network=none --pull=false; no upstream rebuild.
FROM epic-worker@sha256:3c3c2472b35ea3ccb0df57df7cc9d2303f582dcb2987b259124c9df946d56644

# The parent already owns /home/worker and /workspace as 1000:1000, but lacks NSS
# records. Do not create/copy a home or change inherited tools and entrypoint.
USER 0:0
RUN test -x /usr/sbin/nologin \
 && groupadd --gid 1000 worker \
 && useradd --uid 1000 --gid 1000 --no-user-group --no-create-home \
      --no-log-init --home-dir /home/worker --shell /usr/sbin/nologin \
      --password '!' worker

USER 1000:1000
# Fail the build under the actual runtime identity; never print environment values.
RUN python -I -c 'import grp, os, pwd, re; \
    assert os.getuid() == os.getgid() == 1000; \
    account = pwd.getpwuid(os.getuid()); group = grp.getgrgid(os.getgid()); \
    assert account.pw_name == group.gr_name == "worker"; \
    assert account.pw_gid == 1000 and account.pw_dir == os.environ.get("HOME") == "/home/worker"; \
    assert account.pw_shell == "/usr/sbin/nologin" and os.path.isdir(account.pw_dir); \
    assert not any(re.search(r"TOKEN|SECRET|PASSWORD|CREDENTIAL|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|AUTH", name, re.I) for name in os.environ); \
    print("worker NSS identity verified: uid=1000 gid=1000 home=/home/worker")'
