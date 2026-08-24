"""Minimal ToyyibPay REST client — create a bill, and verify its paid status
server-to-server.

Docs: https://toyyibpay.com/apireference/ (community-documented; ToyyibPay
doesn't publish a versioned OpenAPI spec). Two calls are used here:

- createBill: creates a payable bill, returns a BillCode. The hosted
  payment page is https://toyyibpay.com/{BillCode}.
- getBillTransactions: given a BillCode, returns its transaction list —
  used to confirm a payment actually succeeded rather than trusting the
  callback POST at face value (anyone can POST to a public callback URL
  claiming success; only ToyyibPay's own records are trustworthy).

Set TOYYIBPAY_BASE_URL to https://dev.toyyibpay.com to test against their
sandbox before switching to the live https://toyyibpay.com.
"""
from __future__ import annotations

import os

import httpx

_BASE_URL = os.environ.get("TOYYIBPAY_BASE_URL", "https://toyyibpay.com").rstrip("/")
_SECRET_KEY = os.environ.get("TOYYIBPAY_SECRET_KEY")
_CATEGORY_CODE = os.environ.get("TOYYIBPAY_CATEGORY_CODE")


class ToyyibPayError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(_SECRET_KEY and _CATEGORY_CODE)


def _require_config() -> None:
    if not is_configured():
        raise ToyyibPayError(
            "ToyyibPay 未配置（缺少环境变量 TOYYIBPAY_SECRET_KEY / TOYYIBPAY_CATEGORY_CODE）"
        )


def payment_url(bill_code: str) -> str:
    return f"{_BASE_URL}/{bill_code}"


async def create_bill(
    *,
    amount_cents: int,
    reading_token: str,
    return_url: str,
    callback_url: str,
    payer_name: str,
    payer_email: str,
) -> str:
    """Create a bill for one reading unlock and return its BillCode."""
    _require_config()
    payload = {
        "userSecretKey": _SECRET_KEY,
        "categoryCode": _CATEGORY_CODE,
        "billName": "印度占星解读",
        "billDescription": "解锁完整命盘解读",
        "billPriceSetting": 1,  # 1 = fixed price (set by us, not the payer)
        "billPayorInfo": 1,
        "billAmount": str(amount_cents),
        "billReturnUrl": return_url,
        "billCallbackUrl": callback_url,
        "billExternalReferenceNo": reading_token,
        "billTo": (payer_name or "客人")[:100],
        "billEmail": payer_email or "guest@example.com",
        "billPhone": "",
        "billSplitPayment": 0,
        "billPaymentChannel": "0",  # 0 = FPX + credit card
        "billContentEmail": "感谢你的支持，付款完成即可查看完整解读。",
        "billChargeToCustomer": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{_BASE_URL}/index.php/api/createBill", data=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise ToyyibPayError(f"无法连接支付服务: {exc}") from exc

    if not isinstance(data, list) or not data or "BillCode" not in data[0]:
        raise ToyyibPayError(f"创建订单失败，ToyyibPay 返回: {data}")
    return data[0]["BillCode"]


async def bill_is_paid(bill_code: str) -> bool:
    """Ask ToyyibPay directly whether this bill has a successful payment."""
    _require_config()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_BASE_URL}/index.php/api/getBillTransactions",
                data={"billCode": bill_code, "billpaymentStatus": 1},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise ToyyibPayError(f"无法确认付款状态: {exc}") from exc
    # billpaymentStatus=1 filters for successful transactions only, so a
    # non-empty list already means "at least one successful payment".
    return isinstance(data, list) and len(data) > 0
