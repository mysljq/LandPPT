from click.testing import CliRunner


def test_cli_migrate_runs_database_migrations(monkeypatch):
    from landppt import cli as cli_module

    calls = []

    async def fake_init_db(*, bootstrap_admin=True):
        calls.append(("init_db", bootstrap_admin))

    class FakeMigrationManager:
        async def migrate_up(self):
            calls.append(("migrate_up",))
            return True

    async def fake_close_db():
        calls.append(("close_db",))

    monkeypatch.setattr(cli_module, "init_db", fake_init_db)
    monkeypatch.setattr(cli_module, "migration_manager", FakeMigrationManager())
    monkeypatch.setattr(cli_module, "close_db", fake_close_db)

    result = CliRunner().invoke(cli_module.cli, ["migrate"])

    assert result.exit_code == 0
    assert calls == [("init_db", False), ("migrate_up",), ("close_db",)]
    assert "Database migration completed" in result.output


def test_cli_migrate_and_bootstrap_runs_steps_in_order(monkeypatch):
    from landppt import cli as cli_module

    calls = []

    async def fake_init_db(*, bootstrap_admin=True):
        calls.append(("init_db", bootstrap_admin))

    class FakeMigrationManager:
        async def migrate_up(self):
            calls.append(("migrate_up",))
            return True

    async def fake_templates():
        calls.append(("templates",))
        return [1, 2]

    def fake_admin():
        calls.append(("admin",))

    async def fake_close_db():
        calls.append(("close_db",))

    monkeypatch.setattr(cli_module, "init_db", fake_init_db)
    monkeypatch.setattr(cli_module, "migration_manager", FakeMigrationManager())
    monkeypatch.setattr(cli_module, "ensure_default_templates_exist", fake_templates)
    monkeypatch.setattr(cli_module, "_bootstrap_admin", fake_admin)
    monkeypatch.setattr(cli_module, "close_db", fake_close_db)

    result = CliRunner().invoke(cli_module.cli, ["migrate-and-bootstrap"])

    assert result.exit_code == 0
    assert calls == [
        ("init_db", False),
        ("migrate_up",),
        ("close_db",),
        ("templates",),
        ("close_db",),
        ("admin",),
    ]
    assert "Migration and bootstrap completed: 2 templates available" in result.output


def test_cli_migrate_fails_when_migration_fails(monkeypatch):
    from landppt import cli as cli_module

    async def fake_init_db(*, bootstrap_admin=True):
        return None

    class FakeMigrationManager:
        async def migrate_up(self):
            return False

    async def fake_close_db():
        return None

    monkeypatch.setattr(cli_module, "init_db", fake_init_db)
    monkeypatch.setattr(cli_module, "migration_manager", FakeMigrationManager())
    monkeypatch.setattr(cli_module, "close_db", fake_close_db)

    result = CliRunner().invoke(cli_module.cli, ["migrate"])

    assert result.exit_code != 0
    assert "Database migration failed" in result.output
