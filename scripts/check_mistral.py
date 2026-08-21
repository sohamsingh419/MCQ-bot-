import os
import sys

import httpx

api_key = os.environ.get("MISTRAL_API_KEY")
model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
base_url = os.environ.get("MISTRAL_BASE_URL", "https://api.mistral.ai/v1").rstrip("/")
if not api_key:
    print("MISTRAL_API_KEY is not configured")
    raise SystemExit(2)

payload = {
    "model": model,
    "temperature": 0,
    "max_tokens": 8,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": "Return exactly {\"ok\":true}."},
    ],
}
response = httpx.post(
    f"{base_url}/chat/completions",
    headers={"Authorization": f"Bearer {api_key}"},
    json=payload,
    timeout=30,
)
print(f"HTTP {response.status_code}")
if response.is_success:
    data = response.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    print("usable_completion=" + str(bool(content)))
else:
    print("Mistral health check returned an error response")
    raise SystemExit(1)
