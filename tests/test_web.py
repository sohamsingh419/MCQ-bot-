import importlib


def test_health_endpoint_returns_ok_json(monkeypatch):
    web = importlib.import_module("bot.web")
    monkeypatch.setattr(web, "_ready", False)
    monkeypatch.setattr(web, "_stopping", False)
    response = web.app.test_client().get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["service"] == "gsi-study-mcq-bot"
    assert payload["status"] == "starting"


def test_health_endpoint_reports_ready_and_stopping(monkeypatch):
    web = importlib.import_module("bot.web")
    web.mark_ready()
    response = web.app.test_client().get("/")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"

    web.mark_stopping()
    response = web.app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "stopping"

    # Reset module state for any test process that reuses the imported module.
    monkeypatch.setattr(web, "_ready", False)
    monkeypatch.setattr(web, "_stopping", False)
