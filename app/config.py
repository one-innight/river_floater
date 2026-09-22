import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
STATIC_DIR = BASE_DIR / "static"
MOBILE_DIR = BASE_DIR / "mobile"
UPLOAD_DIR = STATIC_DIR / "uploads"
DATABASE_PATH = Path(os.getenv("RIVER_DATABASE", BASE_DIR / "river_litter_mvp.db"))
MODEL_PATH = Path(os.getenv("RIVER_MODEL", BASE_DIR / "weights" / "river_floater.pt"))
CONFIDENCE_THRESHOLD = float(os.getenv("RIVER_CONFIDENCE", "0.3"))
IMAGE_SIZE = int(os.getenv("RIVER_IMAGE_SIZE", "640"))
CAMERA_SOURCE = os.getenv("RIVER_CAMERA_SOURCE", "0")
CAMERA_LOCATION = os.getenv("RIVER_CAMERA_LOCATION", "河段 A")
CAMERA_INTERVAL_SECONDS = max(2.0, float(os.getenv("RIVER_CAMERA_INTERVAL", "8")))
CAMERA_AUTOSTART = os.getenv("RIVER_CAMERA_AUTOSTART", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# 登录账户用于保护巡护记录、现场图片和管理接口。部署时请通过 .env.server
# 覆盖默认密码，并为会话密钥填写随机且足够长的字符串。
AUTH_ENABLED = os.getenv("RIVER_AUTH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
ADMIN_USERNAME = os.getenv("RIVER_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("RIVER_ADMIN_PASSWORD", "admin123456")
SESSION_SECRET = os.getenv("RIVER_SESSION_SECRET", "change-this-session-secret-before-production")
SESSION_HTTPS_ONLY = os.getenv("RIVER_SESSION_HTTPS_ONLY", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
