from django.urls import path
from .views import SendSmsView, MockSavingApiView, index

urlpatterns = [
    path('', index, name='index'),
    path('send-sms/', SendSmsView.as_view(), name='send-sms'),
    path('mock-api/send_sms', MockSavingApiView.as_view(), name='mock-sms'),
]
