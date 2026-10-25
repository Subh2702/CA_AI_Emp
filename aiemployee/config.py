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
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
UI_PORT = int(os.environ.get("UI_PORT", "8080"))
APPROVAL_THRESHOLD = 5000.00
PO_TOLERANCE = 0.02
SCENARIOS_DIR = os.path.join(COMPANY_DIR, "scenarios")
