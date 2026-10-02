"""PDF downloads and business logo upload."""
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from reportlab.lib.utils import ImageReader

from ..deps import OrgContext, get_org_context, require
from ..models import Customer
from ..models_finance import MoneyAccount
from ..models_trade import Payment, PurchaseInvoice, Quotation, SalesInvoice, Supplier
from ..services import pdf_docs
from ..services.trade import get_owned

router = APIRouter(tags=["documents"])
MAX_LOGO = 300 * 1024


def _pdf(body: bytes, name: str, download: bool) -> Response:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    disp = "attachment" if download else "inline"
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'{disp}; filename="{name}.pdf"'})


@router.get("/invoices/{inv_id}/pdf")
def invoice_pdf(inv_id: int, ctx: OrgContext = Depends(require("sales.view")),
                layout: str = Query("a4", pattern="^(a4|thermal)$"), download: bool = False):
    inv = get_owned(ctx, SalesInvoice, inv_id, "Invoice")
    customer = ctx.db.get(Customer, inv.customer_id)
    body = pdf_docs.thermal_receipt_pdf(ctx.org, inv, customer) if layout == "thermal" \
        else pdf_docs.sales_document_pdf(ctx.org, inv, customer, kind="invoice")
    return _pdf(body, inv.number or f"draft-{inv.id}", download)


@router.get("/quotations/{qid}/pdf")
def quotation_pdf(qid: int, ctx: OrgContext = Depends(require("sales.view")), download: bool = False):
    q = get_owned(ctx, Quotation, qid, "Quotation")
    return _pdf(pdf_docs.sales_document_pdf(ctx.org, q, ctx.db.get(Customer, q.customer_id), kind="quotation"),
                q.number, download)


@router.get("/payments/{payment_id}/pdf")
def payment_pdf(payment_id: int, ctx: OrgContext = Depends(require("payments.view")), download: bool = False):
    p = get_owned(ctx, Payment, payment_id, "Payment")
    party = ctx.db.get(Customer, p.customer_id) if p.customer_id else ctx.db.get(Supplier, p.supplier_id)
    allocs = []
    if not p.voided_at:
        for a in p.allocations:
            doc = ctx.db.get(SalesInvoice, a.sales_invoice_id) if a.sales_invoice_id \
                else ctx.db.get(PurchaseInvoice, a.purchase_invoice_id)
            label = doc.number if isinstance(doc, SalesInvoice) else f"{doc.supplier_invoice_number} ({doc.number})"
            allocs.append((label, a.amount))
    account = ctx.db.get(MoneyAccount, p.account_id) if p.account_id else None
    return _pdf(pdf_docs.payment_receipt_pdf(ctx.org, p, party.name, allocs, account.name if account else None),
                p.number, download)


def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


@router.post("/organization/logo", status_code=204)
async def upload_logo(file: UploadFile = File(...), ctx: OrgContext = Depends(require("org.manage"))):
    data = await file.read(MAX_LOGO + 1)
    if len(data) > MAX_LOGO:
        raise HTTPException(413, "Logo must be 300 KB or smaller")
    mime = _image_type(data)  # check the bytes, not the file name or declared type
    if mime is None:
        raise HTTPException(422, "Logo must be a PNG or JPEG image")
    try:
        w, h = ImageReader(io.BytesIO(data)).getSize()
    except Exception:
        raise HTTPException(422, "The image could not be read")
    if w > 4000 or h > 4000:
        raise HTTPException(422, "Logo dimensions must be at most 4000 x 4000 pixels")
    ctx.org.logo, ctx.org.logo_mime = data, mime
    ctx.audit("upload_logo", "organization", ctx.org_id, {"bytes": len(data), "type": mime})
    ctx.db.commit()


@router.get("/organization/logo")
def get_logo(ctx: OrgContext = Depends(get_org_context)):
    if not ctx.org.logo:
        raise HTTPException(404, "No logo uploaded")
    return Response(ctx.org.logo, media_type=ctx.org.logo_mime,
                    headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.delete("/organization/logo", status_code=204)
def delete_logo(ctx: OrgContext = Depends(require("org.manage"))):
    ctx.org.logo = ctx.org.logo_mime = None
    ctx.audit("delete_logo", "organization", ctx.org_id)
    ctx.db.commit()
