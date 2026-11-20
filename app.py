import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

FLW_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY")
FLW_SECRET_HASH = os.environ.get("FLUTTERWAVE_SECRET_HASH")
FLW_BASE_URL = "https://api.flutterwave.com/v3"

# The PythonAnywhere webhook URL this relay forwards confirmed payments to
PMS_WEBHOOK_URL = os.environ.get("PMS_WEBHOOK_URL")
PMS_WEBHOOK_SECRET = os.environ.get("PMS_WEBHOOK_SECRET")  # shared secret, see below


@app.route("/init-payment", methods=["POST"])
def init_payment():
    """Called directly by the guest's browser. Starts a Flutterwave
    transaction and returns the checkout link."""
    data = request.get_json()

    headers = {"Authorization": f"Bearer {FLW_SECRET_KEY}"}
    payload = {
        "tx_ref": data["tx_ref"],
        "amount": str(data["amount"]),
        "currency": "NGN",
        "redirect_url": data["redirect_url"],
        "customer": {"email": data["email"]},
    }

    response = requests.post(f"{FLW_BASE_URL}/payments", json=payload, headers=headers)
    result = response.json()

    if result.get("status") != "success":
        return jsonify({"success": False, "error": result.get("message")}), 400

    return jsonify({"success": True, "link": result["data"]["link"]})


@app.route("/webhooks/flutterwave", methods=["POST"])
def flutterwave_webhook():
    """Flutterwave calls THIS relay, not PythonAnywhere directly,
    since PythonAnywhere's free tier can still RECEIVE anything fine —
    it's only outbound calls that are restricted. But Flutterwave is
    calling the relay here simply because this is where we registered
    the webhook URL in their dashboard."""

    incoming_hash = request.headers.get("verif-hash", "")
    if not incoming_hash or incoming_hash != FLW_SECRET_HASH:
        return jsonify({"error": "Invalid signature"}), 401

    event = request.get_json()
    data = event.get("data", {})

    if data.get("status") == "successful":
        transaction_id = str(data.get("id"))

        headers = {"Authorization": f"Bearer {FLW_SECRET_KEY}"}
        verify_response = requests.get(
            f"{FLW_BASE_URL}/transactions/{transaction_id}/verify", headers=headers
        )
        verification = verify_response.json()
        v_data = verification.get("data", {})

        if verification.get("status") == "success" and v_data.get("status") == "successful":
            # Forward the confirmed result to PythonAnywhere as a plain,
            # incoming POST — this direction is never restricted.
            requests.post(
                PMS_WEBHOOK_URL,
                json={
                    "tx_ref": v_data.get("tx_ref"),
                    "amount": v_data.get("amount"),
                },
                headers={"X-Relay-Secret": PMS_WEBHOOK_SECRET},
                timeout=10,
            )

    return jsonify({"status": "received"}), 200


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "relay is running"})