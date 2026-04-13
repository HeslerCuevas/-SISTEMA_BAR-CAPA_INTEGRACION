from firebase_admin import messaging

def enviar_notificacion_pago(token_fcm: str, factura_uuid: str):
    message = messaging.Message(
        data={
            "action": "ORDER_PAID",
            "factura_uuid": str(factura_uuid),
        },
        token=token_fcm,
    )
    response = messaging.send(message)
    return response