"""Background jobs (Phase 5.3, D-033).

Operator-triggered corpus re-rag runs as an RQ background job on the existing
Redis. This package owns the queue wiring (`queue.py`) and the job functions
(`smoke.py` for now; the real re-rag job lands in commit 3). The dockerised
``rq worker rerag`` process imports and runs these functions.
"""
