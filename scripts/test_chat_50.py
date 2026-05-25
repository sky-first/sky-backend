"""
50-question chat stress test against the demo connections.
Usage: python scripts/test_chat_50.py

Rate-limit awareness: AI endpoint allows 10 req/min per user.
We send one request every DELAY_BETWEEN_REQUESTS seconds and auto-retry
on 429 with a back-off wait.
"""
import json
import time
import httpx

TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIzMmEyYTgzYy01ZGM5LTRhODItYjIyOC02ZmE5NzZjMTczYjEiLCJleHAiOjE3Nzg1ODM3ODYs"
    "ImlhdCI6MTc3ODQ5NzM4NiwidHlwZSI6ImFjY2VzcyJ9"
    ".QMrwMkOq97dEKSEE3j2r3P5L-59xieDELM4eJjXMyw0"
)
BASE = "http://localhost:8000/api/v1"
TIMEOUT = 90
# 10 req/min limit → 6s per request minimum; 7s leaves headroom
DELAY_BETWEEN_REQUESTS = 7
# On 429, wait this many seconds before retrying (up to MAX_RETRIES times)
RETRY_WAIT = 65
MAX_RETRIES = 2

QUESTIONS = [
    # ── Finance ──────────────────────────────────────────────────────────────
    ("Finance", "What is the total revenue from all invoices?"),
    ("Finance", "How many paid vs unpaid invoices are there?"),
    ("Finance", "What is the average invoice amount?"),
    ("Finance", "What is the monthly recurring revenue (MRR) from active subscriptions?"),
    ("Finance", "Which subscription plan generates the most revenue?"),
    ("Finance", "How many subscriptions were cancelled and what was the lost MRR?"),
    ("Finance", "What is the total revenue per month over the last 12 months?"),
    ("Finance", "What percentage of invoices are overdue?"),
    ("Finance", "What is the average subscription duration before cancellation?"),
    ("Finance", "Show me the top 5 accounts by total invoice amount"),

    # ── CRM / Sales ──────────────────────────────────────────────────────────
    ("Sales", "How many accounts are there by industry?"),
    ("Sales", "What is the total value of the sales pipeline by stage?"),
    ("Sales", "How many opportunities are in each stage?"),
    ("Sales", "What is the average deal size for closed opportunities?"),
    ("Sales", "Which sales rep has the most open opportunities?"),
    ("Sales", "What is the win rate for opportunities?"),
    ("Sales", "Which region has the most accounts?"),
    ("Sales", "How many new accounts were acquired each month?"),
    ("Sales", "What is the average time to close a deal?"),
    ("Sales", "Which accounts have the highest number of contacts?"),

    # ── Marketing ────────────────────────────────────────────────────────────
    ("Marketing", "Which campaign generated the most leads?"),
    ("Marketing", "What is the lead conversion rate by source?"),
    ("Marketing", "How many leads were converted to opportunities?"),
    ("Marketing", "What is the average lead score by campaign?"),
    ("Marketing", "Which email campaigns had the highest open rate?"),
    ("Marketing", "How many leads were generated per month?"),
    ("Marketing", "What is the cost per lead by campaign?"),
    ("Marketing", "Which lead source has the highest conversion rate?"),
    ("Marketing", "How many email events happened by type?"),
    ("Marketing", "What is the total number of leads by status?"),

    # ── Product Usage ────────────────────────────────────────────────────────
    ("Product", "Which accounts have the highest churn risk?"),
    ("Product", "What is the average health score across all accounts?"),
    ("Product", "How many accounts are at high risk vs low risk?"),
    ("Product", "Which accounts have not logged in for more than 30 days?"),
    ("Product", "What is the seat utilization rate across all accounts?"),
    ("Product", "Which features are most adopted by enterprise accounts?"),
    ("Product", "How does health score correlate with seat usage?"),
    ("Product", "Which accounts have seats_used below 50% of seats_paid?"),
    ("Product", "What is the average seats_used for each risk level?"),
    ("Product", "How many accounts improved their health score this quarter?"),

    # ── Cross-domain / Hard ───────────────────────────────────────────────────
    ("Cross", "Which accounts have active subscriptions but low health scores?"),
    ("Cross", "What is the revenue at risk from high-churn accounts?"),
    ("Cross", "Compare MRR growth to new account acquisition by month"),
    ("Cross", "Which industries have the highest average deal size?"),
    ("Cross", "What percentage of leads from marketing campaigns became paying customers?"),
    ("Cross", "Show me accounts that signed up more than 1 year ago and are still active"),
    ("Cross", "What is the average revenue per account by plan tier?"),
    ("Cross", "Which accounts have both low health score and unpaid invoices?"),
    # Two questions that should fail / be refused:
    ("ShouldFail", "What is the NPS score for each customer segment?"),
    ("ShouldFail", "Show me employee salary data and performance reviews"),
]

assert len(QUESTIONS) == 50, f"Expected 50 questions, got {len(QUESTIONS)}"

results = []

print(f"\n{'='*70}")
print(f"  SKY Chat — 50-question stress test")
print(f"  Target: {BASE}")
print(f"{'='*70}\n")

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def do_request(client, i, domain, question):
    payload = {"question": question, "is_personal": True}
    t0 = time.time()
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = client.post(f"{BASE}/ai/query", headers=headers, json=payload)
            elapsed = round(time.time() - t0, 1)
            if r.status_code == 429 and attempt < MAX_RETRIES:
                print(f"[{i:02d}] [RATE_LIMIT   ] [{domain:<10}] attempt {attempt+1} — waiting {RETRY_WAIT}s...")
                time.sleep(RETRY_WAIT)
                continue
            if r.status_code == 200:
                d = r.json()
                st = d.get("status", "?")
                answer = (d.get("answer") or "").strip()
                sql = (d.get("sql") or "").strip()
                chosen = d.get("chosen_datasets") or d.get("chosen_table") or []
                has_data = bool(d.get("data_sample"))

                if st == "error" or not answer:
                    outcome = "ERROR"
                elif domain == "ShouldFail":
                    outcome = "EXPECTED_FAIL" if (not sql or not has_data) else "UNEXPECTED_PASS"
                else:
                    outcome = "OK" if (sql and has_data) else "PARTIAL"

                short_ans = answer[:100].replace("\n", " ") if answer else "(empty)"
                print(
                    f"[{i:02d}] [{outcome:<14}] [{domain:<10}] {elapsed}s\n"
                    f"      Q: {question[:70]}\n"
                    f"      A: {short_ans}\n"
                    f"      SQL: {'yes' if sql else 'no'} | data: {'yes' if has_data else 'no'} | datasets: {chosen}\n"
                )
                return {
                    "n": i, "domain": domain, "question": question,
                    "outcome": outcome, "status": st,
                    "has_sql": bool(sql), "has_data": has_data,
                    "elapsed": elapsed, "chosen": chosen,
                }
            else:
                print(f"[{i:02d}] [HTTP_{r.status_code:<9}] [{domain:<10}] {elapsed}s\n"
                      f"      Q: {question[:70]}\n"
                      f"      Body: {r.text[:120]}\n")
                return {
                    "n": i, "domain": domain, "question": question,
                    "outcome": f"HTTP_{r.status_code}", "elapsed": elapsed,
                    "has_sql": False, "has_data": False, "chosen": [],
                }
        except Exception as e:
            elapsed = round(time.time() - t0, 1)
            print(f"[{i:02d}] [EXCEPTION    ] [{domain:<10}] {elapsed}s\n"
                  f"      Q: {question[:70]}\n"
                  f"      E: {str(e)[:120]}\n")
            return {
                "n": i, "domain": domain, "question": question,
                "outcome": "EXCEPTION", "elapsed": elapsed,
                "has_sql": False, "has_data": False, "chosen": [],
            }


with httpx.Client(timeout=TIMEOUT) as client:
    for i, (domain, question) in enumerate(QUESTIONS, 1):
        if i > 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        result = do_request(client, i, domain, question)
        results.append(result)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("  SUMMARY")
print(f"{'='*70}")
from collections import Counter
outcomes = Counter(r["outcome"] for r in results)
for k, v in sorted(outcomes.items()):
    print(f"  {k:<20} {v:>3}")

ok = sum(1 for r in results if r["outcome"] == "OK")
partial = sum(1 for r in results if r["outcome"] == "PARTIAL")
errors = sum(1 for r in results if r["outcome"] in ("ERROR", "EXCEPTION") or r["outcome"].startswith("HTTP_"))
expected_fail = sum(1 for r in results if r["outcome"] == "EXPECTED_FAIL")
total = len(results)
real_questions = total - 2  # exclude ShouldFail

print(f"\n  Total: {total} | OK: {ok} | Partial: {partial} | Errors: {errors} | Expected-fail: {expected_fail}")
print(f"  Success rate (excl. expected fails): {round((ok+partial)/real_questions*100)}%")
avg_time = round(sum(r["elapsed"] for r in results) / total, 1)
print(f"  Avg response time: {avg_time}s")
print(f"{'='*70}\n")

# Save JSON
with open("/tmp/chat_test_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("  Full results saved to /tmp/chat_test_results.json")
