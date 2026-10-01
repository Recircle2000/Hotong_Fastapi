from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaxiLocation(Base):
    __tablename__ = "taxi_locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False, unique=True)
    category = Column(String(20), nullable=False, default="other", server_default="other")
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    departure_parties = relationship(
        "TaxiParty",
        foreign_keys="TaxiParty.departure_location_id",
        back_populates="departure_location",
    )
    destination_parties = relationship(
        "TaxiParty",
        foreign_keys="TaxiParty.destination_location_id",
        back_populates="destination_location",
    )

    __table_args__ = (
        CheckConstraint(
            "category in ('campus', 'station', 'terminal', 'other')",
            name="ck_taxi_locations_category",
        ),
    )


class TaxiParty(Base):
    __tablename__ = "taxi_parties"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    client_request_id = Column(Uuid(as_uuid=True), nullable=False)
    meeting_code = Column(String(4), nullable=True)
    owner_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    departure_location_id = Column(
        Integer,
        ForeignKey("taxi_locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    destination_location_id = Column(
        Integer,
        ForeignKey("taxi_locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    departure_summary = Column(String(80), nullable=False)
    destination_summary = Column(String(80), nullable=True)
    member_note = Column(String(500), nullable=True)
    departure_at = Column(DateTime(timezone=True), nullable=False, index=True)
    max_members = Column(Integer, nullable=False)
    recruitment_open = Column(Boolean, nullable=False, default=True, server_default="true")
    status = Column(String(20), nullable=False, default="active", server_default="active")
    cancellation_reason = Column(String(200), nullable=True)
    cancelled_by_admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    departure_location = relationship(
        "TaxiLocation",
        foreign_keys=[departure_location_id],
        back_populates="departure_parties",
    )
    destination_location = relationship(
        "TaxiLocation",
        foreign_keys=[destination_location_id],
        back_populates="destination_parties",
    )
    members = relationship(
        "TaxiPartyMember",
        back_populates="party",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "TaxiMessage",
        back_populates="party",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "client_request_id", name="uq_taxi_party_owner_request"),
        UniqueConstraint("meeting_code", name="uq_taxi_parties_meeting_code"),
        CheckConstraint(
            "meeting_code is null or meeting_code ~ '^[2-9A-HJ-NP-Z]{4}$'",
            name="ck_taxi_parties_meeting_code",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "departure_location_id <> destination_location_id",
            name="ck_taxi_parties_different_locations",
        ),
        CheckConstraint("max_members between 2 and 4", name="ck_taxi_parties_capacity"),
        CheckConstraint("status in ('active', 'cancelled')", name="ck_taxi_parties_status"),
        Index(
            "ix_taxi_parties_list",
            "departure_at",
            "departure_location_id",
            "destination_location_id",
        ),
    )


class TaxiPartyMember(Base):
    __tablename__ = "taxi_party_members"

    id = Column(Integer, primary_key=True)
    party_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("taxi_parties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    anonymous_number = Column(Integer, nullable=True)
    joined_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    left_at = Column(DateTime(timezone=True), nullable=True)
    last_read_message_id = Column(Integer, nullable=True)

    party = relationship("TaxiParty", back_populates="members")

    __table_args__ = (
        UniqueConstraint("party_id", "user_id", name="uq_taxi_party_member_user"),
        UniqueConstraint("party_id", "anonymous_number", name="uq_taxi_party_member_number"),
        CheckConstraint(
            "anonymous_number is null or anonymous_number > 0",
            name="ck_taxi_party_member_number_positive",
        ),
        Index("ix_taxi_members_user_active", "user_id", "left_at"),
    )


class TaxiMessage(Base):
    __tablename__ = "taxi_messages"

    id = Column(Integer, primary_key=True)
    party_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("taxi_parties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    message_type = Column(String(20), nullable=False, default="chat", server_default="chat")
    content = Column(Text, nullable=False)
    client_message_id = Column(Uuid(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    party = relationship("TaxiParty", back_populates="messages")

    __table_args__ = (
        UniqueConstraint(
            "sender_id",
            "client_message_id",
            name="uq_taxi_message_sender_client_id",
        ),
        CheckConstraint(
            "message_type in ('chat', 'system')",
            name="ck_taxi_messages_type",
        ),
        Index("ix_taxi_messages_party_cursor", "party_id", "id"),
    )
