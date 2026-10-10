"""Exercise the actual main entry path with pending APScheduler jobs."""

from workers import scheduler


def test_main_reaches_initial_check_and_scheduler_start(monkeypatch):
    real = scheduler.create_scheduler()
    calls = []
    monkeypatch.setattr(scheduler, "create_scheduler", lambda: real)
    monkeypatch.setattr(scheduler.signal, "signal", lambda *args: None)
    monkeypatch.setattr(scheduler, "email_job", lambda: calls.append("email"))
    monkeypatch.setattr(real, "start", lambda: calls.append("start"))
    scheduler.main()
    assert calls == ["email", "start"]
    assert {job.id for job in real.get_jobs()} == {"email_monitor", "weekly_scrape"}
