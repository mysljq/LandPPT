#!/bin/sh

set -eu

TARGET_UID="${LANDPPT_UID:-10001}"
TARGET_GID="${LANDPPT_GID:-10001}"
MOUNT_ROOT="/mnt/landppt"
MARKER_NAME=".landppt-permissions-v1"

log() {
    printf '[permissions-init] %s\n' "$1"
}

warn() {
    printf '[permissions-init] WARNING: %s\n' "$1" >&2
}

fail() {
    printf '[permissions-init] ERROR: %s\n' "$1" >&2
    exit 1
}

validate_access() {
    target_path="$1"
    target_kind="$2"

    if ! /opt/venv/bin/python - "$TARGET_UID" "$TARGET_GID" "$target_path" "$target_kind" <<'PY'
import os
import sys
import tempfile

uid = int(sys.argv[1])
gid = int(sys.argv[2])
path = sys.argv[3]
kind = sys.argv[4]

os.setgroups([])
os.setgid(gid)
os.setuid(uid)

if kind == "file":
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    os.close(descriptor)
else:
    descriptor, probe = tempfile.mkstemp(prefix=".landppt-write-test-", dir=path)
    os.close(descriptor)
    os.unlink(probe)
PY
    then
        fail "UID ${TARGET_UID} cannot write ${target_path}"
    fi
}

marker_state() {
    marker_path="$1"

    /opt/venv/bin/python - "$TARGET_UID" "$TARGET_GID" "$marker_path" <<'PY'
import os
import stat
import sys

uid = int(sys.argv[1])
gid = int(sys.argv[2])
path = sys.argv[3]

try:
    descriptor = os.open(
        path,
        os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
except FileNotFoundError:
    print("missing")
    raise SystemExit(0)
except OSError as error:
    raise SystemExit(f"Could not inspect migration marker {path}: {error}")

try:
    marker_stat = os.fstat(descriptor)
finally:
    os.close(descriptor)

if not stat.S_ISREG(marker_stat.st_mode):
    raise SystemExit(f"Migration marker is not a regular file: {path}")
if marker_stat.st_uid != uid or marker_stat.st_gid != gid:
    raise SystemExit(
        f"Migration marker has unexpected owner: {path} "
        f"({marker_stat.st_uid}:{marker_stat.st_gid})"
    )
if stat.S_IMODE(marker_stat.st_mode) != 0o600:
    raise SystemExit(
        f"Migration marker has unexpected mode: {path} "
        f"({stat.S_IMODE(marker_stat.st_mode):#o})"
    )

print("valid")
PY
}

create_marker() {
    marker_path="$1"

    /opt/venv/bin/python - "$TARGET_UID" "$TARGET_GID" "$marker_path" <<'PY'
import os
import stat
import sys

uid = int(sys.argv[1])
gid = int(sys.argv[2])
path = sys.argv[3]
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW

os.setgroups([])
os.setgid(gid)
os.setuid(uid)
os.umask(0o077)

try:
    descriptor = os.open(path, flags, 0o600)
except OSError as error:
    raise SystemExit(f"Could not create migration marker {path}: {error}")

try:
    marker_stat = os.fstat(descriptor)
    if not stat.S_ISREG(marker_stat.st_mode):
        raise RuntimeError("created marker is not a regular file")
    if marker_stat.st_uid != uid or marker_stat.st_gid != gid:
        raise RuntimeError("created marker has unexpected owner")
    if stat.S_IMODE(marker_stat.st_mode) != 0o600:
        raise RuntimeError("created marker has unexpected mode")
except Exception as error:
    raise SystemExit(f"Could not secure migration marker {path}: {error}")
finally:
    os.close(descriptor)
PY
}

migrate_volume() {
    volume_path="$1"
    marker_path="${volume_path}/${MARKER_NAME}"

    [ -d "$volume_path" ] || fail "Volume path is missing: ${volume_path}"

    if ! state=$(marker_state "$marker_path"); then
        fail "Migration marker validation failed: ${marker_path}"
    fi

    case "$state" in
        missing)
            log "Migrating ${volume_path} to ${TARGET_UID}:${TARGET_GID}"
            chown -R "${TARGET_UID}:${TARGET_GID}" "$volume_path"
            chmod -R u+rwX "$volume_path"
            validate_access "$volume_path" directory
            if ! create_marker "$marker_path"; then
                fail "Migration marker creation failed: ${marker_path}"
            fi
            ;;
        valid)
            log "Migration marker found for ${volume_path}; validating"
            validate_access "$volume_path" directory
            ;;
        *)
            fail "Unexpected migration marker state for ${marker_path}: ${state}"
            ;;
    esac
}

configure_env_file() {
    env_path="${MOUNT_ROOT}/env/.env"

    [ -e "$env_path" ] || fail "Mounted .env is missing: ${env_path}"
    [ -f "$env_path" ] || fail "Mounted .env is not a regular file: ${env_path}"

    if ! chgrp "$TARGET_GID" "$env_path" 2>/dev/null; then
        warn "Could not change .env group; checking effective access"
    fi
    if ! chmod g+rw,o-rwx "$env_path" 2>/dev/null; then
        warn "Could not change .env mode; checking effective access"
    fi

    validate_access "$env_path" file
}

main() {
    [ "$(id -u)" -eq 0 ] || fail "Permission migration must run as root"

    configure_env_file
    for volume_name in data uploads reports cache lib; do
        migrate_volume "${MOUNT_ROOT}/${volume_name}"
    done

    log "Permission migration complete"
}

main "$@"
