import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANY_DIR = os.path.join(ROOT, "company")
RUNS_DIR = os.path.join(ROOT, "runs")
ERP_URL = os.environ.get("ERP_URL", "http://127.0.0.1:8001")
ERP_USER = os.environ.get("ERP_USER", "ai.employee")
ERP_PASSWORD = os.environ.get("ERP_PASSWORD", "s3cret-ap-bot")
ERP_API_KEY = os.environ.get("ERP_API_KEY", "audit-key-123")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct")
HF_MODEL = os.environ.get("HF_MODEL", "Qwen/Qwen2.5-72B-Instruct")
HF_BASE_URL = os.environ.get("HF_BASE_URL", "https://router.huggingface.co/v1")
UI_HOST = os.environ.get("UI_HOST", "127.0.0.1")
UI_PORT = int(os.environ.get("PORT") or os.environ.get("UI_PORT", "8080"))  # Render injects PORT
UI_USER = os.environ.get("UI_USER", "admin")
UI_PASSWORD = os.environ.get("UI_PASSWORD", "")  # empty = no auth (local dev only)
DEFAULT_PROVIDER = os.environ.get("DEFAULT_PROVIDER", "ollama")
ALLOW_AUTO = os.environ.get("ALLOW_AUTO", "1") == "1"  # test-only auto-approve/deny; disable when public
APPROVAL_THRESHOLD = 5000.00
PO_TOLERANCE = 0.02
SCENARIOS_DIR = os.path.join(COMPANY_DIR, "scenarios")
