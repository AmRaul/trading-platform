"""Тесты алертера без сети: python -m pytest services/alerter"""
import asyncio

import alerter as al

BOT_OK = {"bot_id": 2, "symbol": "SOLUSDT", "status": "ok", "issues": []}
BOT_STALE = {"bot_id": 4, "symbol": "LINKUSDT", "status": "problem",
             "issues": ["последний тик цены 7 мин назад — поток цен встал"]}


def test_collect_backend_down():
    assert al.collect_problems(None, None, None) == {"backend:down": "бэкенд не отвечает"}


def test_collect_health_503_names_failed_checks():
    p = al.collect_problems(503, {"checks": {"db": True, "redis": False, "scheduler": True, "prices": False}}, None)
    assert list(p.values()) == ["не работает: Redis (цены), поток цен"]


def test_collect_bot_issues_only_problems():
    p = al.collect_problems(200, {}, {"bots": [BOT_OK, BOT_STALE]})
    assert list(p.values()) == ["бот 4 LINKUSDT: последний тик цены 7 мин назад — поток цен встал"]


def test_same_problem_with_other_numbers_is_same_key():
    a = al.problem_key("bot:4", "последний тик цены 7 мин назад")
    b = al.problem_key("bot:4", "последний тик цены 12 мин назад")
    assert a == b


def test_alert_once_then_resolved():
    s = al.AlertState()
    p = al.collect_problems(200, {}, {"bots": [BOT_STALE]})
    msgs = s.update(p, now=0)
    assert len(msgs) == 1 and msgs[0].startswith("🔴")
    assert s.update(al.collect_problems(200, {}, {"bots": [{**BOT_STALE, "issues": [
        "последний тик цены 12 мин назад — поток цен встал"]}]}), now=300) == []  # не спамим
    msgs = s.update({}, now=600)
    assert len(msgs) == 1 and msgs[0].startswith("✅") and "LINKUSDT" in msgs[0]


def test_reminder_after_remind_period():
    s = al.AlertState(remind_sec=3600)
    p = {"health:x": "не работает: база данных"}
    s.update(p, now=0)
    assert s.update(p, now=1800) == []
    msgs = s.update(p, now=3700)
    assert len(msgs) == 1 and msgs[0].startswith("⏰") and "уже 1 ч" in msgs[0]
    assert s.update(p, now=4000) == []


def test_backend_down_needs_confirmation():
    s = al.AlertState(down_after=2)
    down = al.collect_problems(None, None, None)
    assert s.update(down, now=0) == []          # один провал — рестарт при деплое
    assert s.update({}, now=300) == []          # поднялся — тишина
    assert s.update(down, now=600) == []
    msgs = s.update(down, now=900)
    assert len(msgs) == 1 and "2 проверки подряд" in msgs[0]
    msgs = s.update({}, now=1200)
    assert msgs and msgs[0].startswith("✅")


class FakeKandle:
    def __init__(self, status, body, bots):
        self.status, self.body, self.bots, self.bots_calls = status, body, bots, 0

    async def health(self):
        return self.status, self.body

    async def bots_health(self):
        self.bots_calls += 1
        return self.bots


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)


def test_check_once_sends_to_telegram():
    tg, s = FakeTG(), al.AlertState()
    asyncio.run(al.check_once(FakeKandle(200, {}, {"bots": [BOT_STALE]}), s, tg, now=0))
    assert len(tg.sent) == 1 and "LINKUSDT" in tg.sent[0]


def test_check_once_skips_bots_when_backend_down():
    k = FakeKandle(None, None, None)
    asyncio.run(al.check_once(k, al.AlertState(), FakeTG(), now=0))
    assert k.bots_calls == 0


def test_telegram_dry_run_without_token(caplog):
    caplog.set_level("INFO")
    asyncio.run(al.Telegram("", "").send("проверка"))
    assert "dry-run" in caplog.text


def test_backend_down_does_not_resolve_bot_problems():
    s = al.AlertState(down_after=1)
    s.update(al.collect_problems(200, {}, {"bots": [BOT_STALE]}), now=0)
    msgs = s.update(al.collect_problems(None, None, None), now=300)
    assert len(msgs) == 1 and msgs[0].startswith("🔴") and "бэкенд" in msgs[0]  # без ложного «✅»
    msgs = s.update(al.collect_problems(200, {}, {"bots": [BOT_STALE]}), now=600)
    assert len(msgs) == 1 and msgs[0].startswith("✅") and "бэкенд" in msgs[0] and "LINK" not in msgs[0]


def test_httpx_request_logs_silenced():
    import logging
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING  # в URL Telegram — токен
