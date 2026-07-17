import logging

import firebase_admin
from firebase_admin import messaging

logger = logging.getLogger(__name__)


def _firebase_is_ready() -> bool:
    """Avoid attempting delivery before the Gateway lifespan initialized FCM."""
    try:
        firebase_admin.get_app()
        return True
    except ValueError:
        return False


def enviar_notificacion_pago(token_fcm: str, factura_uuid: str):
    """Send the payment push notification without affecting billing.

    FCM is an optional customer-facing notification.  The order has already
    been marked as paid before this background task runs, so a transient FCM
    or Internet failure must never bubble up through Starlette as an API error.
    """
    if not _firebase_is_ready():
        logger.error(
            "Cannot send payment notification for order %s: Firebase Admin is not initialized.",
            factura_uuid,
        )
        return None

    message = messaging.Message(
        data={
            "action": "ORDER_PAID",
            "factura_uuid": str(factura_uuid),
            "payment_status": "PAID",
        },
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                title="Payment confirmed",
                body="Your table order has been paid. Thank you for visiting.",
                channel_id="order_updates",
            ),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(
                        title="Payment confirmed",
                        body="Your table order has been paid. Thank you for visiting.",
                    ),
                    sound="default",
                    content_available=True,
                ),
            ),
        ),
        token=token_fcm,
    )
    try:
        response = messaging.send(message)
        logger.info("Payment notification sent for order %s.", factura_uuid)
        return response
    except Exception as exc:
        logger.warning(
            "Payment notification could not be sent for order %s; "
            "billing remains completed: %s",
            factura_uuid,
            exc,
        )
        return None


def enviar_notificacion_pago_rechazado(token_fcm: str, factura_uuid: str):
    """Tell the mobile app that CAJA rejected the payment request."""
    if not _firebase_is_ready():
        logger.error(
            "Cannot send payment rejection notification for order %s: Firebase Admin is not initialized.",
            factura_uuid,
        )
        return None

    message = messaging.Message(
        data={
            "action": "ORDER_PAYMENT_FAILED",
            "factura_uuid": str(factura_uuid),
            "payment_status": "REJECTED",
        },
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                title="Payment unsuccessful",
                body="The bar rejected this table order. Please contact your server.",
                channel_id="order_updates",
            ),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(
                        title="Payment unsuccessful",
                        body="The bar rejected this table order. Please contact your server.",
                    ),
                    sound="default",
                    content_available=True,
                )
            ),
        ),
        token=token_fcm,
    )
    try:
        return messaging.send(message)
    except Exception as exc:
        logger.warning("Payment rejection notification failed for %s: %s", factura_uuid, exc)
        return None
