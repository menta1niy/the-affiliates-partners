"""Generate local-only test Telegram HTML for a Vite server and isolated test API.

Do not use against a real bot or production API. Generated HTML is gitignored.
"""
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_signed_auth import signed_data


ROOT = Path(__file__).resolve().parents[1]
for role, uid in (("owner", 758398804), ("partner", 12345)):
    token = signed_data(uid, token="test-bot-token")
    js_data = json.dumps(token)
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>The Affiliates · Local {html.escape(role)} Test</title></head>
<body><div id="root"></div>
<script>
window.Telegram = {{WebApp: {{
    initData: {js_data},
    initDataUnsafe: {{user: {{id:{uid},first_name:"Test",username:"testaccount"}}}},
    platform:"android", isFullscreen:false,
    ready(){{}},expand(){{}},setHeaderColor(){{}},requestFullscreen(){{}},
    onEvent(){{}},offEvent(){{}},
    HapticFeedback:{{impactOccurred(){{}}}}
}}}};
</script>
<script type="module" src="/src/main.tsx"></script>
</body></html>"""
    (ROOT / f".e2e-{role}.html").write_text(page, encoding="utf-8")
print("Generated local-only owner and partner browser fixtures.")
