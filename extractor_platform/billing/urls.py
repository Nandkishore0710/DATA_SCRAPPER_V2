from django.urls import path
from .views import (
    CreateRazorpayOrder, VerifyRazorpayPayment,
    CreatePayPalOrder, CapturePayPalOrder
)

urlpatterns = [
    path('order/create/', CreateRazorpayOrder.as_view(), name='create-razorpay-order'),
    path('order/verify/', VerifyRazorpayPayment.as_view(), name='verify-razorpay-payment'),
    
    path('paypal/create/', CreatePayPalOrder.as_view(), name='create-paypal-order'),
    path('paypal/capture/', CapturePayPalOrder.as_view(), name='capture-paypal-order'),
]
