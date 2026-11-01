from fastapi import APIRouter, HTTPException, Request, Response

from app.db import now
from app.dependencies import DB, batch_result
from app.schemas import AssociationBatch, AssociationBatchRead, AssociationType
from app.store import (
    ASSOCIATION_TYPES,
    OBJECT_TYPES,
    association_name,
    association_results,
    association_rows,
    canonical,
    get_record,
    link,
    unlink,
)

router = APIRouter()


def resolve_types(item, source, target):
    if item.types:
        return [spec.associationTypeId for spec in item.types]
    if item.type:
        for type_id, definition in ASSOCIATION_TYPES.items():
            if definition[:2] == (source, target) and item.type in {
                str(type_id),
                association_name(type_id),
            }:
                return [type_id]
    raise HTTPException(400, "Specify a valid association type")


@router.post("/{from_type}/{to_type}/batch/create", status_code=201)
def batch_create(from_type: str, to_type: str, body: AssociationBatch, session: DB):
    started = now()
    source_type, target_type = canonical(from_type), canonical(to_type)
    results = []
    for item in body.inputs:
        source = get_record(session, source_type, item.from_.id)
        target = get_record(session, target_type, item.to.id)
        for type_id in resolve_types(item, source_type, target_type):
            link(session, source, target, type_id)
            results.append(
                {
                    "from": {"id": source.id},
                    "to": {"id": target.id},
                    "type": association_name(type_id),
                }
            )
    return batch_result(results, started)


@router.post("/{from_type}/{to_type}/batch/read")
def batch_read(
    from_type: str, to_type: str, body: AssociationBatchRead, request: Request, session: DB
):
    started = now()
    source_type, target_type = canonical(from_type), canonical(to_type)
    modern = "/2026-09/" in request.url.path or "/v4/" in request.url.path
    results = []
    for item in body.inputs:
        source = get_record(session, source_type, item.id)
        rows = association_rows(session, source, target_type)
        results.append({"from": {"id": source.id}, "to": association_results(rows, modern)})
    return batch_result(results, started)


@router.post("/{from_type}/{to_type}/batch/archive", status_code=204)
def batch_archive(from_type: str, to_type: str, body: AssociationBatch, session: DB):
    source_type, target_type = canonical(from_type), canonical(to_type)
    for item in body.inputs:
        source = get_record(session, source_type, item.from_.id)
        target = get_record(session, target_type, item.to.id)
        for type_id in resolve_types(item, source_type, target_type):
            unlink(session, source, target, type_id)
    return Response(status_code=204)


modern_objects = APIRouter()


@modern_objects.put("/{object_type}/{object_id}/associations/{to_type}/{to_id}")
def labeled_create(
    object_type: str,
    object_id: str,
    to_type: str,
    to_id: str,
    body: list[AssociationType],
    session: DB,
):
    if not body:
        raise HTTPException(400, "At least one association type is required")
    source = get_record(session, canonical(object_type), object_id)
    target = get_record(session, canonical(to_type), to_id)
    for spec in body:
        link(session, source, target, spec.associationTypeId)
    return {
        "fromObjectTypeId": OBJECT_TYPES[source.object_type][1],
        "fromObjectId": int(source.id),
        "toObjectTypeId": OBJECT_TYPES[target.object_type][1],
        "toObjectId": int(target.id),
        "labels": [ASSOCIATION_TYPES[spec.associationTypeId][3] for spec in body],
    }


@modern_objects.delete("/{object_type}/{object_id}/associations/{to_type}/{to_id}", status_code=204)
def remove_all(object_type: str, object_id: str, to_type: str, to_id: str, session: DB):
    source = get_record(session, canonical(object_type), object_id)
    target = get_record(session, canonical(to_type), to_id)
    unlink(session, source, target)
    return Response(status_code=204)
