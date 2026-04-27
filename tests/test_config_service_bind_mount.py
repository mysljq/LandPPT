import errno
import os
import stat
from pathlib import Path

from dotenv import main as dotenv_main
from landppt.services.config_service import ConfigService


def test_update_config_preserves_env_inode_ownership_and_mode(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# preserved comment\nOPENAI_MODEL=old-model\nUNCHANGED=value",
        encoding="utf-8",
    )
    env_path.chmod(0o640)
    monkeypatch.setenv("OPENAI_MODEL", "process-old-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://process-old.test/v1")

    service = ConfigService(env_file=str(env_path))
    monkeypatch.setattr(service, "_reload_ai_config", lambda: None)
    move_file = dotenv_main.shutil.move

    def reject_bind_mount_replacement(source, destination, *args, **kwargs):
        if Path(destination).resolve() == env_path.resolve():
            raise OSError(errno.EBUSY, "bind-mounted file cannot be replaced")
        return move_file(source, destination, *args, **kwargs)

    monkeypatch.setattr(dotenv_main.shutil, "move", reject_bind_mount_replacement)
    before = env_path.stat()

    # Keep the original inode open, as a bind mount does at the VFS boundary.
    with env_path.open("rb") as mounted_file:
        mounted = os.fstat(mounted_file.fileno())
        assert service.update_config(
            {
                "openai_model": "new-model",
                "openai_base_url": "https://example.test/v1",
            }
        ) is True
        after = env_path.stat()

        assert (after.st_dev, after.st_ino) == (mounted.st_dev, mounted.st_ino)

    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert env_path.read_text(encoding="utf-8") == (
        "# preserved comment\n"
        "OPENAI_MODEL=new-model\n"
        "UNCHANGED=value\n"
        "OPENAI_BASE_URL=https://example.test/v1\n"
    )
    assert os.environ["OPENAI_MODEL"] == "new-model"
    assert os.environ["OPENAI_BASE_URL"] == "https://example.test/v1"
