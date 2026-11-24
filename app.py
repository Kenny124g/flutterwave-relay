import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={
    r"/init-payment": {"origins": "https://hotelsprototype.pythonanywhere.com"},
    r"/verify-now": {"origins": "https://hotelsprototype.pythonanywhere.com"},
})

FLW_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY")
FLW_SECRET_HASH = os.environ.get("FLUTTERWAVE_SECRET_HASH")
FLW_BASE_URL = "https://api.flutterwave.com/v3"

PMS_WEBHOOK_URL = os.environ.get("PMS_WEBHOOK_URL")
PMS_WEBHOOK_SECRET = os.environ.get("PMS_WEBHOOK_SECRET")


def verify_and_forward(transaction_id):
    headers = {"Authorization": f"Bearer {FLW_SECRET_KEY}"}
    response = requests.get(f"{FLW_BASE_URL}/transactions/{transaction_id}/verify", headers=headers)
    verification = response.json()
    v_data = verification.get("data", {})
    status = v_data.get("status")

    print(f"[VERIFY] transaction_id={transaction_id} flutterwave_status={status} full_response={verification}", flush=True)

    if verification.get("status") == "success" and status == "successful":
        try:
            fwd_response = requests.post(
                PMS_WEBHOOK_URL,
                json={"tx_ref": v_data.get("tx_ref"), "amount": v_data.get("amount"), "event": "successful"},
                headers={"X-Relay-Secret": PMS_WEBHOOK_SECRET},
                timeout=15,
            )
            print(f"[FORWARD] sent to PMS, status_code={fwd_response.status_code}, body={fwd_response.text}", flush=True)
        except Exception as e:
            print(f"[FORWARD ERROR] {type(e).__name__}: {e}", flush=True)

    elif status in ("cancelled", "failed"):
        try:
            fwd_response = requests.post(
                PMS_WEBHOOK_URL,
                json={"tx_ref": v_data.get("tx_ref"), "event": status},
                headers={"X-Relay-Secret": PMS_WEBHOOK_SECRET},
                timeout=15,
            )
            print(f"[FORWARD] sent to PMS, status_code={fwd_response.status_code}, body={fwd_response.text}", flush=True)
        except Exception as e:
            print(f"[FORWARD ERROR] {type(e).__name__}: {e}", flush=True)
    else:
        print(f"[VERIFY] status={status!r} — not successful/cancelled/failed, no action taken", flush=True)

    return v_data


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


@app.route("/verify-now", methods=["POST"])
def verify_now():
    """Called by the guest's browser right after returning from checkout,
    to get an immediate answer instead of waiting on the webhook alone."""
    data = request.get_json()
    transaction_id = data.get("transaction_id")
    if not transaction_id:
        return jsonify({"success": False, "error": "transaction_id required"}), 400

    v_data = verify_and_forward(transaction_id)
    return jsonify({"success": True, "status": v_data.get("status"), "tx_ref": v_data.get("tx_ref")})


@app.route("/webhooks/flutterwave", methods=["POST"])
def flutterwave_webhook():
    """Flutterwave calls THIS relay (not PythonAnywhere directly), since
    that's where we registered the webhook URL in their dashboard."""
    incoming_hash = request.headers.get("verif-hash", "")
    if not incoming_hash or incoming_hash != FLW_SECRET_HASH:
        return jsonify({"error": "Invalid signature"}), 401

    event = request.get_json()
    data = event.get("data", {})

    if data.get("status") in ("successful", "cancelled", "failed"):
        verify_and_forward(str(data.get("id")))

    return jsonify({"status": "received"}), 200


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "relay is running"})