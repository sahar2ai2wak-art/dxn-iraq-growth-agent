import json
from app import core


def test_four_answers_and_no_budget_does_not_alone_disqualify(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB', tmp_path / 'leads.db')
    lead = core.upsert('telegram', '42', name='Test')
    assert lead['status'] == 'جديد'
    for value in (1, 2, 1, 3):
        lead = core.answer('telegram', '42', value)
    assert lead['score'] == 5
    assert lead['status'] == 'مؤهل'
    assert json.loads(lead['answers']) == [1, 2, 1, 3]
    assert core.answer('telegram', '42', 3)['answers'] == lead['answers']


def test_duplicate_event(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'DB', tmp_path / 'events.db')
    assert core.dedupe('a') is True
    assert core.dedupe('a') is False
