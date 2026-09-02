import os
import uuid
from datetime import datetime
from typing import Any, Dict
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import require_donor
from app.database import get_db
from app.sslcommerz import (
    SSLCommerzAPIError,
    SSLCommerzConfigurationError,
    sanitize_sslcommerz_response,
    sslcommerz_client,
)

router = APIRouter(prefix="/api/sslcommerz", tags=["SSLCOMMERZ Payments"])

SUCCESS_STATUSES = {"VALID", "VALIDATED"}


def _frontend_url() -> str:
    configured = os.getenv("SSLCOMMERZ_FRONTEND_URL", "").strip()
    return (configured or "http://127.0.0.1:5173").rstrip("/")


def _callback_base_url() -> str:
    configured = os.getenv("SSLCOMMERZ_CALLBACK_BASE_URL", "").strip()
    return (configured or "http://127.0.0.1:8000").rstrip("/")


async def _request_values(request: Request) -> Dict[str, str]:
    """Read SSLCOMMERZ callback values from either POST form or query string."""
    values: Dict[str, str] = {key: value for key, value in request.query_params.items()}
    if request.method.upper() == "POST":
        try:
            form = await request.form()
            values.update({key: str(value) for key, value in form.items()})
        except Exception:
            # A malformed callback is handled by the caller as missing fields.
            pass
    return values


def _redirect(status: str, tracking_id: str | None = None, message: str | None = None):
    query: Dict[str, str] = {"payment": status, "gateway": "sslcommerz"}
    if tracking_id:
        query["tracking_id"] = tracking_id
    if message:
        query["message"] = message
    return RedirectResponse(f"{_frontend_url()}/?{urlencode(query)}", status_code=303)


def _get_payment_and_donation(db: Session, tran_id: str):
    payment = db.query(models.SSLCommerzPayment).filter(
        models.SSLCommerzPayment.tran_id == tran_id
    ).first()
    if not payment:
        return None, None
    donation = db.query(models.Donation).filter(
        models.Donation.id == payment.donation_id
    ).first()
    return payment, donation


def _amount_matches(expected: float, received: Any) -> bool:
    try:
        return abs(float(expected) - float(received)) <= 0.01
    except (TypeError, ValueError):
        return False


def _complete_validated_payment(
    db: Session,
    donation: models.Donation,
    payment: models.SSLCommerzPayment,
    result: Dict[str, Any],
) -> None:
    status = str(result.get("status") or "").upper()
    if status not in SUCCESS_STATUSES:
        raise HTTPException(status_code=400, detail="SSLCOMMERZ did not validate this transaction")

    if str(result.get("tran_id") or "") != payment.tran_id:
        raise HTTPException(status_code=400, detail="SSLCOMMERZ transaction ID does not match")
    if not _amount_matches(donation.amount, result.get("amount")):
        raise HTTPException(status_code=400, detail="SSLCOMMERZ transaction amount does not match")
    if str(result.get("currency") or "BDT").upper() != "BDT":
        raise HTTPException(status_code=400, detail="SSLCOMMERZ transaction currency does not match")

    first_completion = donation.gateway_transaction_id.startswith("PENDING-")
    if first_completion:
        campaign = db.query(models.Campaign).filter(
            models.Campaign.id == donation.campaign_id
        ).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        campaign.collected_amount += donation.amount

    bank_tran_id = str(result.get("bank_tran_id") or payment.tran_id)
    card_type = str(result.get("card_type") or "SSLCOMMERZ")
    card_no = str(result.get("card_no") or "").strip()

    donation.gateway_transaction_id = bank_tran_id
    donation.payment_reference = card_no or card_type
    donation.payment_gateway = "SSLCOMMERZ"
    donation.payment_status = "Completed"

    payment.validation_id = result.get("val_id") or payment.validation_id
    payment.bank_tran_id = result.get("bank_tran_id") or payment.bank_tran_id
    payment.card_type = result.get("card_type") or payment.card_type
    payment.transaction_status = "Completed"
    payment.status_message = "SSLCOMMERZ payment validated"
    payment.validation_response = sanitize_sslcommerz_response(result)
    payment.last_synced_at = datetime.utcnow()


@router.get("/config")
def sslcommerz_configuration_status(
    current_user: models.User = Depends(require_donor),
):
    status = sslcommerz_client.configuration_status()
    callback_base = _callback_base_url()
    status.update({
        "callback_base_url": callback_base,
        "callback_is_public_https": callback_base.startswith("https://")
        and "127.0.0.1" not in callback_base
        and "localhost" not in callback_base,
    })
    return status


@router.post("/payments/create", response_model=schemas.SSLCommerzPaymentStartResponse)
def create_sslcommerz_donation_payment(
    payment_in: schemas.SSLCommerzPaymentCreate,
    current_user: models.User = Depends(require_donor),
    db: Session = Depends(get_db),
):
    if not sslcommerz_client.configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "SSLCOMMERZ is not configured. Add your Sandbox Store ID and Store Password "
                "to backend/.env, then restart the backend."
            ),
        )

    campaign = db.query(models.Campaign).filter(
        models.Campaign.id == payment_in.campaign_id,
        models.Campaign.status == "Active",
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Active campaign not found")

    tracking_id = f"DNT-{uuid.uuid4().hex[:12].upper()}"
    # SSLCOMMERZ documents a maximum transaction-ID length of 30 characters.
    tran_id = f"DN-{uuid.uuid4().hex[:24].upper()}"

    donation = models.Donation(
        campaign_id=campaign.id,
        donor_user_id=current_user.id,
        donor_name=current_user.organization_name or current_user.full_name,
        amount=payment_in.amount,
        payment_gateway="SSLCOMMERZ",
        payment_reference="SSLCOMMERZ Hosted Checkout",
        tracking_id=tracking_id,
        gateway_transaction_id=f"PENDING-{tran_id}",
        payment_status="Initiated",
    )
    db.add(donation)
    db.flush()

    payment = models.SSLCommerzPayment(
        donation_id=donation.id,
        tran_id=tran_id,
        transaction_status="Initiated",
    )
    db.add(payment)
    db.commit()
    db.refresh(donation)
    db.refresh(payment)

    callback_base = _callback_base_url()
    phone = (current_user.phone or "01700000000").strip()
    payload = {
        "total_amount": f"{payment_in.amount:.2f}",
        "currency": "BDT",
        "tran_id": tran_id,
        "success_url": f"{callback_base}/api/sslcommerz/success",
        "fail_url": f"{callback_base}/api/sslcommerz/fail",
        "cancel_url": f"{callback_base}/api/sslcommerz/cancel",
        "ipn_url": f"{callback_base}/api/sslcommerz/ipn",
        "product_name": f"Donation - {campaign.title}"[:255],
        "product_category": "donation",
        "product_profile": "general",
        "cus_name": current_user.full_name,
        "cus_email": current_user.email,
        "cus_add1": "Dhaka",
        "cus_city": "Dhaka",
        "cus_postcode": "1200",
        "cus_country": "Bangladesh",
        "cus_phone": phone,
        "shipping_method": "NO",
        "value_a": str(donation.id),
        "value_b": tracking_id,
        "value_c": str(campaign.id),
        "value_d": str(current_user.id),
    }

    try:
        result = sslcommerz_client.create_payment(payload)
    except (SSLCommerzAPIError, SSLCommerzConfigurationError) as exc:
        donation.payment_status = "Failed"
        payment.transaction_status = "Failed"
        payment.status_message = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payment.session_key = result.get("sessionkey")
    payment.gateway_page_url = result.get("GatewayPageURL")
    payment.create_response = sanitize_sslcommerz_response(result)
    payment.transaction_status = "Initiated"
    payment.status_message = "Checkout session created"
    payment.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "donation_id": donation.id,
        "tracking_id": tracking_id,
        "tran_id": tran_id,
        "session_key": payment.session_key,
        "gateway_url": payment.gateway_page_url,
        "payment_status": donation.payment_status,
    }


@router.api_route("/success", methods=["GET", "POST"])
async def sslcommerz_success(request: Request, db: Session = Depends(get_db)):
    values = await _request_values(request)
    tran_id = values.get("tran_id", "")
    val_id = values.get("val_id", "")
    payment, donation = _get_payment_and_donation(db, tran_id)
    if not payment or not donation:
        return _redirect("error", message="Payment record not found")
    if not val_id:
        payment.status_message = "Success callback did not include val_id"
        db.commit()
        return _redirect("pending", donation.tracking_id)

    try:
        result = sslcommerz_client.validate_payment(val_id)
        _complete_validated_payment(db, donation, payment, result)
        db.commit()
        return _redirect("success", donation.tracking_id)
    except (SSLCommerzAPIError, SSLCommerzConfigurationError, HTTPException) as exc:
        payment.status_message = str(getattr(exc, "detail", exc))
        payment.last_synced_at = datetime.utcnow()
        db.commit()
        return _redirect("pending", donation.tracking_id, "Payment needs verification")


@router.api_route("/fail", methods=["GET", "POST"])
async def sslcommerz_fail(request: Request, db: Session = Depends(get_db)):
    values = await _request_values(request)
    tran_id = values.get("tran_id", "")
    payment, donation = _get_payment_and_donation(db, tran_id)
    if payment and donation and donation.payment_status != "Completed":
        donation.payment_status = "Failed"
        payment.transaction_status = "Failed"
        payment.status_message = "SSLCOMMERZ checkout failed"
        payment.last_synced_at = datetime.utcnow()
        db.commit()
    return _redirect("failed", donation.tracking_id if donation else None)


@router.api_route("/cancel", methods=["GET", "POST"])
async def sslcommerz_cancel(request: Request, db: Session = Depends(get_db)):
    values = await _request_values(request)
    tran_id = values.get("tran_id", "")
    payment, donation = _get_payment_and_donation(db, tran_id)
    if payment and donation and donation.payment_status != "Completed":
        donation.payment_status = "Cancelled"
        payment.transaction_status = "Cancelled"
        payment.status_message = "SSLCOMMERZ checkout cancelled"
        payment.last_synced_at = datetime.utcnow()
        db.commit()
    return _redirect("cancelled", donation.tracking_id if donation else None)


@router.api_route("/ipn", methods=["GET", "POST"])
async def sslcommerz_ipn(request: Request, db: Session = Depends(get_db)):
    values = await _request_values(request)
    tran_id = values.get("tran_id", "")
    val_id = values.get("val_id", "")
    status = str(values.get("status") or "").upper()
    payment, donation = _get_payment_and_donation(db, tran_id)
    if not payment or not donation:
        return {"received": True, "updated": False, "reason": "payment_not_found"}

    if status in SUCCESS_STATUSES and val_id:
        try:
            result = sslcommerz_client.validate_payment(val_id)
            _complete_validated_payment(db, donation, payment, result)
            db.commit()
            return {"received": True, "updated": True, "status": "Completed"}
        except (SSLCommerzAPIError, SSLCommerzConfigurationError, HTTPException) as exc:
            payment.status_message = str(getattr(exc, "detail", exc))
            payment.last_synced_at = datetime.utcnow()
            db.commit()
            return {"received": True, "updated": False, "reason": "validation_failed"}

    if status in {"FAILED", "CANCELLED", "CANCEL"} and donation.payment_status != "Completed":
        donation.payment_status = "Cancelled" if status.startswith("CANCEL") else "Failed"
        payment.transaction_status = donation.payment_status
        payment.status_message = f"SSLCOMMERZ IPN status: {status}"
        payment.last_synced_at = datetime.utcnow()
        db.commit()
    return {"received": True, "updated": True, "status": donation.payment_status}


@router.post("/donations/{donation_id}/sync", response_model=schemas.DonationHistoryResponse)
def sync_sslcommerz_donation(
    donation_id: int,
    current_user: models.User = Depends(require_donor),
    db: Session = Depends(get_db),
):
    donation = db.query(models.Donation).filter(
        models.Donation.id == donation_id,
        models.Donation.donor_user_id == current_user.id,
    ).first()
    if not donation:
        raise HTTPException(status_code=404, detail="Donation not found")

    payment = db.query(models.SSLCommerzPayment).filter(
        models.SSLCommerzPayment.donation_id == donation.id
    ).first()
    if not payment:
        raise HTTPException(status_code=400, detail="This donation is not an SSLCOMMERZ payment")

    try:
        result = sslcommerz_client.query_by_transaction_id(payment.tran_id)
    except (SSLCommerzAPIError, SSLCommerzConfigurationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payment.query_response = sanitize_sslcommerz_response(result)
    payment.last_synced_at = datetime.utcnow()

    elements = result.get("element") or []
    if isinstance(elements, dict):
        elements = [elements]
    matching = next(
        (item for item in elements if str(item.get("tran_id") or "") == payment.tran_id),
        elements[0] if elements else None,
    )

    if matching:
        remote_status = str(matching.get("status") or "").upper()
        payment.transaction_status = remote_status or payment.transaction_status
        if remote_status in SUCCESS_STATUSES and matching.get("val_id"):
            validated = sslcommerz_client.validate_payment(str(matching["val_id"]))
            _complete_validated_payment(db, donation, payment, validated)
        elif remote_status == "FAILED" and donation.payment_status != "Completed":
            donation.payment_status = "Failed"

    db.commit()
    db.refresh(donation)

    refunded_amount = 0.0
    utilized_amount = float(sum(
        row.amount for row in db.query(models.DonationUtilization).filter(
            models.DonationUtilization.donation_id == donation.id
        ).all()
    ))
    net_amount = max(0.0, float(donation.amount) - refunded_amount)
    return {
        **schemas.DonationResponse.model_validate(donation).model_dump(),
        "payment_gateway": "SSLCOMMERZ",
        "gateway_payment_id": payment.session_key or payment.tran_id,
        "gateway_transaction_id": payment.bank_tran_id or payment.tran_id,
        "refunded_amount": refunded_amount,
        "net_amount": net_amount,
        "utilized_amount": utilized_amount,
        "available_amount": max(0.0, net_amount - utilized_amount),
    }
