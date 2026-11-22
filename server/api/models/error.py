"""System exceptions recorded independently of processing jobs."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class Error(Base):
    __tablename__ = "errors"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    location: Mapped[str] = mapped_column(Text)
    error_message: Mapped[str] = mapped_column(Text)
