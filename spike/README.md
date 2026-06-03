# Spike — echo server

Throwaway FastAPI stub used in Phase 1.2 to verify the tModLoader mod can POST
JSON to a local server and receive a reply before any real backend exists.

## Run

```bash
uvicorn spike.echo_server:app --reload --port 8000
```

## Test

```bash
curl -s -X POST http://localhost:8000/echo \
  -H "Content-Type: application/json" \
  -d '{"message": "what armor should I craft?", "hp": 300}' | python3 -m json.tool
```

Expected response:

```json
{
    "reply": "Echo: what armor should I craft? (HP=300)"
}
```

## Result

Verified 2026-06-03: /bot from in-game tModLoader round-tripped to this server; reply rendered in chat with live HP. Phase 1.2 success criterion met.