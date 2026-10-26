"""
api/models/base.py
------------------
Declarative base for all SQLAlchemy ORM models.
Import Base here and use it in every model class.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
