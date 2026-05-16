from __future__ import annotations


def test_request_summary_enqueues_job(client_with_fakes) -> None:
    client, _, arq, _ = client_with_fakes
    r = client.post("/summaries/request", json={})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert len(arq.jobs) == 1
    assert arq.jobs[0]["name"] == "summary_job"


def test_request_summary_with_chat_id(client_with_fakes) -> None:
    client, _, arq, _ = client_with_fakes
    r = client.post("/summaries/request", json={"chat_id": 12345})
    assert r.status_code == 202
    assert arq.jobs[0]["kwargs"]["chat_id"] == 12345
