"""At most `max_concurrent_runs` learns, repairs and spot checks use the model at once.

Ten portals added together went over the key's 1,000,000 tokens a minute and the learns that lost out died of
a 429 ("No recipe could be learned"). The others now wait for a free place. No model is called here.
"""
from __future__ import annotations

import threading
import time

import pytest

import app.agent as agent_module
from app.agent import Agents
from app.agent.settings import AgentSettings
from app.models import Portal, url_key


def portal(n: int) -> Portal:
    url = f"https://p{n}.example/"
    return Portal(id=f"p{n}", url=url, url_key=url_key(url))


def agents_with(monkeypatch, limit: int, work) -> Agents:
    monkeypatch.setattr(agent_module, "learn", work)
    monkeypatch.setattr(Agents, "_steps", lambda self, run_id: None)
    return Agents(model=None, fetch=None, database=None, settings=AgentSettings(max_concurrent_runs=limit))


def test_no_more_learns_than_the_limit_run_at_once(monkeypatch):
    lock, active, peak, done = threading.Lock(), [0], [0], []

    def slow_learn(p, **kwargs):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
            done.append(p.id)
        return p.id

    agents = agents_with(monkeypatch, 2, slow_learn)
    threads = [threading.Thread(target=agents.learn, args=(portal(n), f"r{n}")) for n in range(10)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]
    assert sorted(done) == sorted(f"p{n}" for n in range(10))      # every learn ran: none was dropped
    assert peak[0] == 2                                            # and never more than two at the same moment


def test_a_run_that_fails_gives_its_place_back(monkeypatch):
    def boom(p, **kwargs):
        raise RuntimeError("the model call failed")

    agents = agents_with(monkeypatch, 1, boom)
    for n in range(3):                                             # with one place, a leak would hang the second
        with pytest.raises(RuntimeError):
            agents.learn(portal(n), f"r{n}")


def test_the_limit_is_a_setting_that_must_be_positive():
    assert AgentSettings().max_concurrent_runs == 2
    assert AgentSettings.from_env({"AGENT_MAX_CONCURRENT_RUNS": "4"}).max_concurrent_runs == 4
    with pytest.raises(ValueError):
        AgentSettings(max_concurrent_runs=0)
