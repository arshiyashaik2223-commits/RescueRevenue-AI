"""
app/models/user.py

Domain model for the `Users` collection (dashboard login accounts —
NOT the business's end-customers, which live embedded inside
Transactions/FailedPayments per the approved schema doc).

This is the DB-facing representation used by `app/db/repositories/
users_repo.py` to read/write MongoDB documents, and consumed by
`app/core/security.py` when building JWTs and resolving the current
user. It intentionally includes sensitive fields (e.g. `password_hash`)
that must NEVER be reused as an API response model — see
`app/schemas/auth_schemas.py` (upcoming) for the public-facing shapes
that exclude such fields.

Reference: RevenueRescue-AI-Database-Schema.md, Section 1 ("Users").
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Optional

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field


def _validate_object_id(value: Any) -> ObjectId:
    """
    Coerces incoming values (str or ObjectId) into a valid bson ObjectId,
    raising a clear error otherwise. Used as a BeforeValidator so Pydantic
    v2 can accept both real ObjectIds (from Motor) and their string form
    (from JSON/API input) transparently.
    """
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ValueError(f"Invalid ObjectId: {value!r}")


# Reusable annotated type: validates as ObjectId, serializes as str.
PyObjectId = Annotated[ObjectId, BeforeValidator(_validate_object_id)]


class UserRole(str, Enum):
    """
    Role-based access control tiers, per the approved API spec:
      - admin:   full read/write access, can manage team + settings
      - analyst: can create/trigger recovery actions, cannot manage team
      - viewer:  read-only dashboard access
    """

    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class UserModel(BaseModel):
    """
    Full representation of a `Users` document as stored in MongoDB.

    Field-by-field mapping to the approved schema doc:
      _id             -> id (aliased, ObjectId)
      business_id     -> business_id (ObjectId, FK -> businesses._id)
      name            -> name
      email           -> email (unique login identifier)
      password_hash   -> password_hash (bcrypt/argon2 hash, never plaintext)
      role            -> role (admin | analyst | viewer)
      is_active       -> is_active (soft-disable flag)
      last_login_at   -> last_login_at
      created_at      -> created_at
      updated_at      -> updated_at
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str},
    )

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    business_id: PyObjectId
    name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password_hash: str
    role: UserRole
    is_active: bool = True
    last_login_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo(self) -> dict:
        """
        Serializes the model into a plain dict suitable for insertion into
        MongoDB via Motor, excluding `id` when it's None (let MongoDB
        generate the ObjectId on insert) and using the Mongo field name
        `_id` when it is set (e.g. for updates).
        """
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, document: dict) -> "UserModel":
        """Builds a UserModel from a raw MongoDB document."""
        return cls.model_validate(document)


class UserCreate(BaseModel):
    """
    Minimal shape needed internally to construct a new UserModel before
    persistence (e.g. from the register/invite flow in services/).
    Distinct from `UserModel` because it never carries an `id`,
    `created_at`, or `updated_at` — those are assigned at creation time.
    """

    business_id: PyObjectId
    name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password_hash: str
    role: UserRole = UserRole.VIEWER
    is_active: bool = True

    model_config = ConfigDict(arbitrary_types_allowed=True)
