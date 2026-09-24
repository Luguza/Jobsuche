"""Änderungsprotokoll: neue/verschwundene Stellen und Firmen je Lauf (data/history.json)."""

from __future__ import annotations

MAX_ITEMS = 300


def diff_run(prev_jobs: dict, jobs: list[dict], prev_companies: dict, companies: list[dict],
             timestamp: str) -> dict:
    job_ids = {j["refnr"] for j in jobs}
    company_ids = {c["key"] for c in companies}
    entry = {"timestamp": timestamp, "jobs": len(jobs), "companies": len(companies)}
    if not prev_jobs and not prev_companies:
        entry["initial"] = True
        return entry

    def job_brief(j: dict) -> dict:
        return {"refnr": j["refnr"], "title": j["title"], "company": j["company"]}

    def company_brief(c: dict) -> dict:
        return {"key": c["key"], "name": c["name"], "score": c.get("score")}

    entry["new_jobs"] = [job_brief(j) for j in jobs if j["refnr"] not in prev_jobs][:MAX_ITEMS]
    entry["removed_jobs"] = [job_brief(j) for r, j in sorted(prev_jobs.items()) if r not in job_ids][:MAX_ITEMS]
    entry["new_companies"] = [company_brief(c) for c in companies if c["key"] not in prev_companies][:MAX_ITEMS]
    entry["removed_companies"] = [
        company_brief(c) for k, c in sorted(prev_companies.items()) if k not in company_ids][:MAX_ITEMS]
    return entry
