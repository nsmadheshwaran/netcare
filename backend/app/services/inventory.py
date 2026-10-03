"""All stock changes go through apply_movement(). Callers own the transaction (commit)."""
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Location, Product, StockLevel, StockMovement

# Sign applied to the (positive) quantity for each movement type. Adjustments take a signed delta.
SIGN = {"stock_in": 1, "customer_return": 1, "purchase_receipt": 1, "transfer_in": 1, "sale_cancel": 1, "service_part_return": 1,
        "stock_out": -1, "damaged": -1, "supplier_return": -1, "sale": -1, "transfer_out": -1,
        "service_part": -1}


# Inflows that bring in goods at a known cost and therefore move the average.
# Transfers are internal and never change it.
COST_BEARING_INFLOWS = {"stock_in", "purchase_receipt", "customer_return", "sale_cancel", "adjustment",
                        "service_part_return"}


def _total_on_hand(db: Session, product_id: int) -> Decimal:
    return Decimal(db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0))
                             .where(StockLevel.product_id == product_id)))


class StockError(HTTPException):
    def __init__(self, detail: str, code: int = status.HTTP_409_CONFLICT):
        super().__init__(code, detail)


def _lock_level(db: Session, org_id: int, product_id: int, location_id: int) -> StockLevel:
    q = (select(StockLevel)
         .where(StockLevel.product_id == product_id, StockLevel.location_id == location_id)
         .with_for_update())  # row lock on PostgreSQL; no-op on SQLite (which serialises writes)
    level = db.scalar(q)
    if level is None:
        level = StockLevel(organization_id=org_id, product_id=product_id, location_id=location_id,
                           quantity=Decimal("0"))
        db.add(level)
        db.flush()
    return level


def apply_movement(db: Session, *, org_id: int, user_id: int | None, product_id: int, location_id: int,
                   movement_type: str, quantity: Decimal, unit_cost: Decimal | None = None,
                   reference: str | None = None, note: str | None = None,
                   idempotency_key: str | None = None, allow_negative: bool = False) -> StockMovement:
    if idempotency_key:
        existing = db.scalar(select(StockMovement).where(StockMovement.organization_id == org_id,
                                                         StockMovement.idempotency_key == idempotency_key))
        if existing:
            if (existing.product_id, existing.location_id, existing.movement_type) != (
                    product_id, location_id, movement_type):
                raise StockError("Idempotency key already used for a different movement")
            return existing

    # Locked: the moving-average cost below is a read-modify-write on the product row.
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not product or product.organization_id != org_id or product.archived_at is not None:
        raise StockError("Product not found", status.HTTP_404_NOT_FOUND)
    if product.is_service:
        raise StockError("Services do not carry stock", status.HTTP_422_UNPROCESSABLE_CONTENT)
    location = db.get(Location, location_id)
    if not location or location.organization_id != org_id or not location.is_active:
        raise StockError("Location not found", status.HTTP_404_NOT_FOUND)

    if movement_type == "adjustment":
        delta = quantity
        if delta == 0:
            raise StockError("Adjustment quantity cannot be zero", status.HTTP_422_UNPROCESSABLE_CONTENT)
    elif movement_type in SIGN:
        if quantity <= 0:
            raise StockError("Quantity must be positive", status.HTTP_422_UNPROCESSABLE_CONTENT)
        delta = quantity * SIGN[movement_type]
    else:
        raise StockError(f"Unknown movement type {movement_type}", status.HTTP_422_UNPROCESSABLE_CONTENT)

    level = _lock_level(db, org_id, product_id, location_id)
    new_qty = Decimal(level.quantity) + delta
    if new_qty < 0 and not allow_negative:
        raise StockError(f"Insufficient stock: {level.quantity} available at {location.name}")

    avg = Decimal(product.avg_cost or 0)
    if delta > 0 and unit_cost is not None and movement_type in COST_BEARING_INFLOWS:
        on_hand = max(_total_on_hand(db, product_id), Decimal("0"))
        product.avg_cost = ((on_hand * avg + delta * Decimal(unit_cost)) / (on_hand + delta)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif unit_cost is None:
        unit_cost = avg  # outflows, transfers and uncosted adjustments are valued at current average cost
    level.quantity = new_qty

    mov = StockMovement(organization_id=org_id, product_id=product_id, location_id=location_id,
                        movement_type=movement_type, quantity_change=delta, balance_after=new_qty,
                        unit_cost=unit_cost, reference=reference, note=note,
                        idempotency_key=idempotency_key, created_by=user_id)
    db.add(mov)
    db.flush()
    return mov


def transfer(db: Session, *, org_id: int, user_id: int | None, product_id: int, from_location_id: int,
             to_location_id: int, quantity: Decimal, note: str | None = None,
             idempotency_key: str | None = None) -> tuple[StockMovement, StockMovement]:
    if from_location_id == to_location_id:
        raise StockError("Source and destination must differ", status.HTTP_422_UNPROCESSABLE_CONTENT)
    ref = f"TRANSFER {from_location_id}->{to_location_id}"
    out = apply_movement(db, org_id=org_id, user_id=user_id, product_id=product_id,
                         location_id=from_location_id, movement_type="transfer_out", quantity=quantity,
                         reference=ref, note=note,
                         idempotency_key=f"{idempotency_key}:out" if idempotency_key else None)
    inn = apply_movement(db, org_id=org_id, user_id=user_id, product_id=product_id,
                         location_id=to_location_id, movement_type="transfer_in", quantity=quantity,
                         reference=ref, note=note,
                         idempotency_key=f"{idempotency_key}:in" if idempotency_key else None)
    return out, inn
