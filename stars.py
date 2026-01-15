
# Telegram Stars invoice helper (use Telegram Payments API)
def stars_invoice(user_id, amount_stars=500):
    return {
        "title": "Premium 30 Days",
        "description": "30-day Premium access",
        "payload": f"stars:{user_id}:{amount_stars}",
        "currency": "XTR",
        "prices": [{"label": "Premium", "amount": amount_stars}]
    }
