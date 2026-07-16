import logging

from firebase_admin import messaging

logger = logging.getLogger(__name__)


def enviar_notificacion_pago(token_fcm: str, factura_uuid: str):
    """Send the payment push notification without affecting billing.

    FCM is an optional customer-facing notification.  The order has already
    been marked as paid before this background task runs, so a transient FCM
    or Internet failure must never bubble up through Starlette as an API error.
    """
    message = messaging.Message(
        data={
            "action": "ORDER_PAID",
            "factura_uuid": str(factura_uuid),
        },
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
