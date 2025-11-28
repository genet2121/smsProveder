from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
from asgiref.sync import async_to_sync
from .services import SMSService
import logging

logger = logging.getLogger(__name__)

def index(request):
    """Simple index view to verify service is running"""
    return JsonResponse({
        "status": "running", 
        "service": "SMS Service", 
        "endpoints": {
            "send_sms": "/notifications/send-sms/",
            "mock_api": "/notifications/mock-api/send_sms"
        }
    })

@method_decorator(csrf_exempt, name='dispatch')
class SendSmsView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            phone = data.get('phone')
            message = data.get('message')
            
            if not phone or not message:
                return JsonResponse({"error": "Phone and message are required"}, status=400)
            
            # Use async_to_sync to call the async service method from a synchronous view
            success = async_to_sync(SMSService.send_custom_sms)(phone, message)
            
            if success:
                return JsonResponse({"status": "success", "message": "SMS sent"})
            else:
                return JsonResponse({"status": "error", "message": "Failed to send SMS"}, status=500)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class MockSavingApiView(View):
    def get(self, request):
        """Handle GET requests to the mock endpoint"""
        return JsonResponse({"status": "running", "message": "Mock SMS API is ready. Send POST requests here."})

    def post(self, request):
        """Mock endpoint to simulate the Saving API SMS handler"""
        try:
            data = json.loads(request.body)
            logger.info(f"MOCK API RECEIVED SMS REQUEST: {data}")
            return JsonResponse({"status": "success", "message": "Mock SMS accepted"})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
