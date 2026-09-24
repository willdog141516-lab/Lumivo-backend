from app.settings import Settings


def test_settings_use_fixture_defaults(monkeypatch):
    for name in (
        "LUMIVO_APP_NAME",
        "LUMIVO_ENVIRONMENT",
        "LUMIVO_PROVIDER_MODE",
        "LUMIVO_FRONTEND_ORIGIN",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_name == "Lumivo Backend"
    assert settings.environment == "development"
    assert settings.provider_mode == "fixture"
    assert settings.frontend_origin == "http://localhost:8989"


def test_settings_accept_environment_overrides(monkeypatch):
    monkeypatch.setenv("LUMIVO_APP_NAME", "Test Backend")
    monkeypatch.setenv("LUMIVO_ENVIRONMENT", "test")
    monkeypatch.setenv("LUMIVO_PROVIDER_MODE", "map-real")
    monkeypatch.setenv("LUMIVO_FRONTEND_ORIGIN", "http://localhost:3100")
    monkeypatch.setenv("LUMIVO_BAIDU_MAP_SK", "test-sk")
    monkeypatch.setenv("LUMIVO_BAIDU_VECTOR_TILE_AK", "vector-ak")

    settings = Settings()

    assert settings.app_name == "Test Backend"
    assert settings.environment == "test"
    assert settings.provider_mode == "map-real"
    assert settings.frontend_origin == "http://localhost:3100"
    assert settings.baidu_map_sk == "test-sk"
    assert settings.baidu_vector_tile_ak == "vector-ak"
