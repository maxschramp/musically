from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(default="")  # JSON-encoded
    description: Mapped[str] = mapped_column(default="")
    category: Mapped[str]  # "thresholds" | "scheduling" | "sources" | "library" | "notifications" | "api_keys" | "beets"
