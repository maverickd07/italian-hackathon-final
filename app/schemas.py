from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)


class Ref(Model):
    id: str


class AssociationType(Model):
    associationCategory: Literal["HUBSPOT_DEFINED"] = "HUBSPOT_DEFINED"
    associationTypeId: int = Field(gt=0)


class AssociationInput(Model):
    to: Ref
    types: list[AssociationType] = Field(min_length=1)


class Create(Model):
    properties: dict[str, Any]
    associations: list[AssociationInput] = Field(default_factory=list)


class Update(Model):
    properties: dict[str, Any]


class BatchCreate(Model):
    inputs: list[Create] = Field(max_length=100)


class BatchUpdateItem(Update):
    id: str
    idProperty: str | None = None


class BatchUpdate(Model):
    inputs: list[BatchUpdateItem] = Field(max_length=100)


class BatchRead(Model):
    inputs: list[Ref] = Field(max_length=100)
    properties: list[str] | None = None
    idProperty: str | None = None


class BatchArchive(Model):
    inputs: list[Ref] = Field(max_length=100)


Operator = Literal[
    "EQ",
    "NEQ",
    "LT",
    "LTE",
    "GT",
    "GTE",
    "BETWEEN",
    "IN",
    "NOT_IN",
    "HAS_PROPERTY",
    "NOT_HAS_PROPERTY",
    "CONTAINS_TOKEN",
    "NOT_CONTAINS_TOKEN",
]


class Filter(Model):
    propertyName: str = Field(min_length=1)
    operator: Operator
    value: str | None = None
    highValue: str | None = None
    values: list[str] | None = None

    @model_validator(mode="after")
    def operands(self):
        if self.operator in {"IN", "NOT_IN"}:
            if self.values is None:
                raise ValueError("values is required for IN and NOT_IN")
        elif self.operator not in {"HAS_PROPERTY", "NOT_HAS_PROPERTY"} and self.value is None:
            raise ValueError("value is required for this operator")
        if self.operator == "BETWEEN" and self.highValue is None:
            raise ValueError("highValue is required for BETWEEN")
        return self


class FilterGroup(Model):
    filters: list[Filter] = Field(default_factory=list, max_length=6)


class Sort(Model):
    propertyName: str = Field(min_length=1)
    direction: Literal["ASCENDING", "DESCENDING"] = "ASCENDING"


class Search(Model):
    filterGroups: list[FilterGroup] = Field(default_factory=list, max_length=5)
    filters: list[Filter] = Field(default_factory=list, max_length=6)
    sorts: list[Sort | str] = Field(default_factory=list, max_length=1)
    query: str | None = None
    properties: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=200)
    after: int = Field(default=0, ge=0, lt=10000)

    @model_validator(mode="after")
    def total_filters(self):
        if sum(len(g.filters) for g in self.filterGroups) + len(self.filters) > 18:
            raise ValueError("Maximum 18 filters")
        return self


class AssociationBatchItem(Model):
    from_: Ref = Field(alias="from")
    to: Ref
    type: str | None = None
    types: list[AssociationType] = Field(default_factory=list)


class AssociationBatch(Model):
    inputs: list[AssociationBatchItem] = Field(max_length=2000)


class AssociationBatchRead(Model):
    inputs: list[Ref] = Field(max_length=1000)


class UpsertItem(Update):
    id: str = Field(min_length=1)
    idProperty: str = Field(min_length=1)
    objectWriteTraceId: str | None = None


class BatchUpsert(Model):
    inputs: list[UpsertItem] = Field(max_length=100)
