from pathlib import Path


def test_startup_dotenv_does_not_override_orchestrator_environment():
    config_text = Path("src/landppt/core/config.py").read_text(encoding="utf-8")

    assert "load_dotenv(env_path, override=False)" in config_text
    assert "load_dotenv(env_path, override=True)" not in config_text
