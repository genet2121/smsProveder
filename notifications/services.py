import asyncio
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Union
import logging
from django.conf import settings

from .utils import make_rest_request

# Configuration
SAVING_API_URL = getattr(settings, 'SAVING_API_URL', None)
SMS_API_KEY = getattr(settings, 'SMS_API_KEY', None)
SMS_RETRY_ATTEMPTS = getattr(settings, 'SMS_MAX_RETRIES', 3)
SMS_TIMEOUT = 30

logger = logging.getLogger(__name__)

class SMSService:

    
    @staticmethod
    def _create_headers() -> dict[str, str]:
        """Create standard headers for SMS requests"""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    
    @staticmethod
    def _generate_reference(prefix: str = "SMS") -> str:
        """Generate unique SMS reference with timestamp"""
        from uuid import uuid4
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]  # Include milliseconds
        random_suffix = uuid4().hex[:8]
        return f"{prefix}_{timestamp}_{random_suffix}"
    
    @staticmethod
    def _format_amount(amount: Union[float, Decimal, str]) -> str:
        """Format amount consistently for SMS display"""
        try:
            if isinstance(amount, str):
                amount = float(amount)
            elif isinstance(amount, Decimal):
                amount = float(amount)
            return f"{amount:,.2f}"
        except (ValueError, TypeError):
            return "0.00"
    
    @staticmethod
    def _validate_phone(phone: str) -> bool:
        """Validate phone number format"""
        if not phone or not isinstance(phone, str):
            return False
        # Remove spaces and check length
        phone_clean = phone.strip().replace(" ", "")
        if phone_clean.startswith("+"):
            phone_clean = phone_clean[1:]
        return len(phone_clean) >= 9 and phone_clean.isdigit()
    
    @staticmethod
    def _validate_message(message: str) -> str:
        """Validate and clean message content"""
        if not message or not isinstance(message, str):
            return ""
        
        # Clean up the message
        message = message.strip()
        
        # Remove excessive whitespace
        message = re.sub(r'\s+', ' ', message)
        
        # Limit message length to avoid SMS API issues (160 chars standard, but allow up to 300)
        if len(message) > 300:
            message = message[:297] + "..."
        
        # Remove any potentially problematic characters
        message = message.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        
        return message
    
    @staticmethod
    def _normalize_ethiopian_phone(phone: str) -> Optional[str]:
        """
        Normalize Ethiopian phone number to GeezSMS format (must start with 2519)
        Accepts formats: +251911223344, 251911223344, 0911223344, 911223344
        """
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        
        # Remove leading + if present
        if phone_clean.startswith("+"):
            phone_clean = phone_clean[1:]
        
        # Handle different formats
        if phone_clean.startswith("251"):
            # Already has country code
            pass
        elif phone_clean.startswith("0"):
            # Remove leading 0 and add country code
            phone_clean = "251" + phone_clean[1:]
        elif phone_clean.startswith("9") and len(phone_clean) == 9:
            # Just the 9 digits, add country code
            phone_clean = "251" + phone_clean
        else:
            logger.warning(f"Unable to normalize phone: {phone}")
            return None
        
        # Verify it's a valid Ethiopian mobile (should be 2519XXXXXXXX)
        if phone_clean.startswith("2519") and len(phone_clean) == 12:
            return phone_clean
        
        logger.warning(f"Invalid Ethiopian phone format: {phone}")
        return None
    
    @staticmethod
    async def _send_geezsms(phone: str, message: str) -> bool:
        """Send SMS via GeezSMS API"""
        try:
            if not SMS_API_KEY:
                logger.error("GeezSMS: SMS_API_KEY not configured")
                return False
            
            # Normalize phone to GeezSMS format
            normalized_phone = SMSService._normalize_ethiopian_phone(phone)
            if not normalized_phone:
                logger.error(f"GeezSMS: Failed to normalize phone {phone}")
                return False
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            
            # GeezSMS expects these exact field names
            sms_data = {
                "token": SMS_API_KEY,
                "phone": normalized_phone,
                "msg": message
            }
            
            logger.info(f"Sending GeezSMS to {normalized_phone[:8]}****")
            
            # Retry logic with exponential backoff
            for attempt in range(SMS_RETRY_ATTEMPTS):
                try:
                    response = await asyncio.wait_for(
                        make_rest_request(headers, SAVING_API_URL, "POST", sms_data),
                        timeout=SMS_TIMEOUT,
                    )
                    
                    if response and response.status_code == 200:
                        # Log the full response to see what GeezSMS actually returned
                        response_json = response.json() if response.text else {}
                        print(f"✅GeezSMS Response: {response_json}")
                        logger.info(f"GeezSMS API Response: {response_json}")
                        logger.info(f"GeezSMS sent successfully to {normalized_phone[:8]}****")
                        return True
                    else:
                        status_code = response.status_code if response else "No Response"
                        response_text = response.text if response else "N/A"
                        logger.warning(
                            f"GeezSMS attempt {attempt + 1} failed: status={status_code}, response={response_text[:200]}"
                        )
                except Exception as e:
                    logger.error(
                        f"GeezSMS attempt {attempt + 1} error: {e}",
                        exc_info=True,
                    )
                
                if attempt < SMS_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(min(2 ** attempt, 10))
            
            logger.error(f"All GeezSMS attempts failed for {normalized_phone[:8]}****")
            return False
            
        except Exception as e:
            logger.exception(f"GeezSMS service error: {e}", exc_info=True)
            return False
    
    
    @staticmethod
    async def send_sms(reference: str, payload: dict[str, Any], phone: str = None) -> bool:

        try:
            if not SAVING_API_URL:
                logger.error("SMS config error: SAVING_API_URL not configured")
                return False

            # Validate phone if provided
            if phone and not SMSService._validate_phone(phone):
                logger.warning("SMS validation error: invalid phone format %s", phone)
                return False

            headers = SMSService._create_headers()
            sms_url = f"{SAVING_API_URL}/send_sms"

            sms_data = {
                "reference": reference,
                "payload": payload,
            }

            logger.info("Sending SMS: ref=%s phone=%s", reference, phone or "in_payload")

            # Retry logic with exponential backoff
            for attempt in range(SMS_RETRY_ATTEMPTS):
                try:
                    response = await asyncio.wait_for(
                        make_rest_request(headers, sms_url, "POST", sms_data),
                        timeout=SMS_TIMEOUT,
                    )
                    if response and response.status_code == 200:
                        logger.info("SMS sent successfully: ref=%s", reference)
                        return True
                    else:
                        status_code = response.status_code if response else "No Response"
                        logger.warning(
                            "SMS attempt %s failed: status=%s ref=%s",
                            attempt + 1,
                            status_code,
                            reference,
                        )
                except Exception as e:
                    logger.error(
                        "SMS attempt %s error: %s ref=%s",
                        attempt + 1,
                        e,
                        reference,
                        exc_info=True,
                    )

                if attempt < SMS_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(min(2 ** attempt, 10))  # Capped exponential backoff

            logger.error("All SMS attempts failed: ref=%s", reference)
            return False

        except Exception as e:
            logger.exception("SMS service error: %s", e, exc_info=True)
            return False
    
    # ==================== TRANSACTION SMS METHODS ====================
    
    @staticmethod
    async def send_transaction_sms(reference: str, product_name: str, balance: Union[float, Decimal], 
                                  bank_name: str, phone: str = None) -> bool:
        """Send basic transaction SMS notification"""
        payload = {
            "product_name": product_name,
            "saving_balance": SMSService._format_amount(balance),
            "bank_name": bank_name,
            "type": "transaction"
        }
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_deposit_sms(phone: str, amount: Union[float, Decimal], balance: Union[float, Decimal],
                              product_name: str, bank_name: str, reference: str, customer_name: str = None) -> bool:
        """Send deposit confirmation SMS"""
        payload = {
            "phone": phone,
            "transaction_type": "DEPOSIT",
            "amount": SMSService._format_amount(amount),
            "product_name": product_name,
            "saving_balance": SMSService._format_amount(balance),
            "bank_name": bank_name,
            "type": "deposit_confirmation"
        }
        if customer_name:
            payload["customer_name"] = customer_name
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_withdrawal_sms(phone: str, amount: Union[float, Decimal], balance: Union[float, Decimal],
                                 product_name: str, bank_name: str, reference: str, fee_amount: Union[float, Decimal] = 0, 
                                 customer_name: str = None) -> bool:
        """Send withdrawal confirmation SMS"""
        payload = {
            "phone": phone,
            "transaction_type": "WITHDRAWAL",
            "amount": SMSService._format_amount(amount),
            "product_name": product_name,
            "saving_balance": SMSService._format_amount(balance),
            "bank_name": bank_name,
            "type": "withdrawal_confirmation"
        }
        if fee_amount and float(fee_amount) > 0:
            payload["fee_amount"] = SMSService._format_amount(fee_amount)
        if customer_name:
            payload["customer_name"] = customer_name
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_transfer_sms(reference: str, amount: Union[float, Decimal], debit_product: str, 
                               credit_product: str, debit_balance: Union[float, Decimal], 
                               credit_balance: Union[float, Decimal], bank_name: str, 
                               recipient_name: str = None, phone: str = None) -> bool:
        """Send transfer SMS notification"""
        payload = {
            "transaction_type": "TRANSFER",
            "amount": SMSService._format_amount(amount),
            "debit_product_name": debit_product,
            "credit_product_name": credit_product,
            "saving_balance": SMSService._format_amount(debit_balance),
            "credit_saving_balance": SMSService._format_amount(credit_balance),
            "bank_name": bank_name,
            "type": "transfer_confirmation"
        }
        if recipient_name:
            payload["recipient_name"] = recipient_name
        return await SMSService.send_sms(reference, payload, phone)
    
    # ==================== BULK DISBURSEMENT SMS METHODS ====================
    
    @staticmethod
    async def send_bulk_authorization_sms(phone: str, authorizer_name: str, batch_reference: str,
                                         transaction_count: int, total_amount: Union[float, Decimal],
                                         product_name: str = None) -> bool:
        """Send bulk disbursement authorization SMS"""
        reference = SMSService._generate_reference("BULK_AUTH")
        message = (f"{authorizer_name} authorized bulk disbursement {batch_reference} "
                  f"with {transaction_count} transactions totaling {SMSService._format_amount(total_amount)} ETB")
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "bulk_authorization",
            "authorizer_name": authorizer_name,
            "batch_reference": batch_reference,
            "transaction_count": transaction_count,
            "total_amount": SMSService._format_amount(total_amount)
        }
        if product_name:
            payload["product_name"] = product_name
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_bulk_rejection_sms(phone: str, rejector_name: str, batch_reference: str,
                                     transaction_count: int, total_amount: Union[float, Decimal],
                                     reason: str = None) -> bool:
        """Send bulk disbursement rejection SMS"""
        reference = SMSService._generate_reference("BULK_REJ")
        message = (f"{rejector_name} rejected bulk disbursement {batch_reference} "
                  f"with {transaction_count} transactions totaling {SMSService._format_amount(total_amount)} ETB")
        if reason:
            message += f". Reason: {reason}"
            
        payload = {
            "phone": phone,
            "message": message,
            "type": "bulk_rejection",
            "rejector_name": rejector_name,
            "batch_reference": batch_reference,
            "transaction_count": transaction_count,
            "total_amount": SMSService._format_amount(total_amount)
        }
        if reason:
            payload["rejection_reason"] = reason
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_bulk_disbursement_received_sms(phone: str, recipient_name: str, 
                                                 amount: Union[float, Decimal], sender_name: str,
                                                 batch_reference: str, product_name: str = None,
                                                 transaction_time: str = None) -> bool:
 

        reference = SMSService._generate_reference("BULK_RECV")
        
        # Enhanced messaging with professional formatting
        time_info = f" at {transaction_time}" if transaction_time else ""
        product_info = f" to your {product_name}" if product_name else ""
        
        message = (f"SUCCESS BULK TRANSFER RECEIVED!\n"
                  f"MONEY Amount: {SMSService._format_amount(amount)} ETB\n"
                  f"👤 From: {sender_name}\n"
                  f"TIME Time: {transaction_time or 'now'}{product_info}\n"
                  f"LIST Ref: {batch_reference}")
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "bulk_received_enhanced",
            "recipient_name": recipient_name,
            "amount": SMSService._format_amount(amount),
            "sender_name": sender_name,
            "batch_reference": batch_reference,
            "enhanced": True
        }
        if product_name:
            payload["product_name"] = product_name
        if transaction_time:
            payload["transaction_time"] = transaction_time
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_bulk_status_sms(phone: str, sender_name: str, batch_id: Union[int, str], 
                                  transaction_count: int, total_amount: Union[float, Decimal],
                                  status: str, processing_time_minutes: float = None,
                                  rejection_reason: str = None) -> bool:
  
        reference = SMSService._generate_reference("BULK_STATUS")
        
        # Status-specific messaging
        if status.upper() == "COMPLETED":
            status_emoji = "SUCCESS"
            status_text = "BULK DISBURSEMENT COMPLETE!"
            action_text = "transfers completed"
            details = "SUCCESS All recipients notified"
        elif status.upper() == "REJECTED":
            status_emoji = "ERROR"
            status_text = "BULK DISBURSEMENT REJECTED"
            action_text = "transfers rejected"
            details = f"❗ Reason: {rejection_reason or 'Authorization denied'}\nINFO Your funds remain safe"
        else:
            status_emoji = "CHART"
            status_text = f"BULK DISBURSEMENT {status.upper()}"
            action_text = "transactions processed"
            details = f"REFRESH Status: {status}"
        
        # Build comprehensive message
        message_parts = [
            f"{status_emoji} {status_text}",
            f"👤 {sender_name}",
            f"CHART Batch: {batch_id}",
            f"SUCCESS {transaction_count} {action_text}",
            f"MONEY Total: {SMSService._format_amount(total_amount)} ETB"
        ]
        
        if processing_time_minutes is not None:
            message_parts.append(f"⏱️ Processing: {processing_time_minutes:.1f} minutes")
            
        message_parts.append(details)
        
        message = "\n".join(message_parts)
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "bulk_status_enhanced",
            "sender_name": sender_name,
            "batch_id": str(batch_id),
            "transaction_count": transaction_count,
            "total_amount": SMSService._format_amount(total_amount),
            "status": status,
            "enhanced": True
        }
        if processing_time_minutes is not None:
            payload["processing_time_minutes"] = processing_time_minutes
        if rejection_reason:
            payload["rejection_reason"] = rejection_reason
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_bulk_rejection_sms(phone: str, recipient_name: str, amount: Union[float, Decimal],
                                     sender_name: str, rejection_reason: str, batch_reference: str,
                                     next_steps: str = None) -> bool:
        """
        MOBILE **ENHANCED BULK REJECTION SMS**
        
        Professional rejection notification with guidance and next steps
        """
        reference = SMSService._generate_reference("BULK_REJ")
        
        message_parts = [
            "ERROR TRANSFER NOT APPROVED",
            f"MONEY Expected: {SMSService._format_amount(amount)} ETB",
            f"👤 From: {sender_name}",
            f"❗ Reason: {rejection_reason}",
            f"LIST Ref: {batch_reference}"
        ]
        
        if next_steps:
            message_parts.append(f"INFO Next: {next_steps}")
            
        message = "\n".join(message_parts)
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "bulk_rejection_enhanced",
            "recipient_name": recipient_name,
            "amount": SMSService._format_amount(amount),
            "sender_name": sender_name,
            "rejection_reason": rejection_reason,
            "batch_reference": batch_reference,
            "enhanced": True
        }
        if next_steps:
            payload["next_steps"] = next_steps
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_csv_upload_confirmation_sms(phone: str, batch_id: Union[int, str], 
                                              transaction_count: int, total_amount: Union[float, Decimal],
                                              upload_time: str = None, estimated_completion_time: str = None) -> bool:

        reference = SMSService._generate_reference("CSV_UPLOAD")
        
        message_parts = [
            "DOCUMENT CSV UPLOAD SUCCESSFUL",
            f"CHART Batch ID: {batch_id}",
            f"SUCCESS Transactions: {transaction_count}",
            f"MONEY Total: {SMSService._format_amount(total_amount)} ETB",
            f"TIME Uploaded: {upload_time or 'now'}",
            "REFRESH Processing starts immediately"
        ]
        
        if estimated_completion_time:
            message_parts.append(f"⏱️ Est. completion: {estimated_completion_time}")
            
        message_parts.append("MOBILE You'll receive authorization notifications")
        
        message = "\n".join(message_parts)
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "csv_upload_confirmation",
            "batch_id": str(batch_id),
            "transaction_count": transaction_count,
            "total_amount": SMSService._format_amount(total_amount),
            "enhanced": True
        }
        if upload_time:
            payload["upload_time"] = upload_time
        if estimated_completion_time:
            payload["estimated_completion_time"] = estimated_completion_time
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_non_subscriber_invitation_sms(phone: str, sender_name: str, expected_amount: Union[float, Decimal],
                                                product_name: str, financial_institution_name: str,
                                                batch_reference: str) -> bool:

        reference = SMSService._generate_reference("NON_SUB_INV")
        
        message_parts = [
            "SUCCESS MONEY WAITING FOR YOU!",
            f"MONEY {SMSService._format_amount(expected_amount)} ETB from {sender_name}",
            f"BANK Subscribe to {product_name} ({financial_institution_name}) to receive",
            "FAST Quick registration needed",
            "INFO Free subscription, instant activation",
            f"LIST Ref: {batch_reference}",
            "LAUNCH Don't miss out - subscribe now!"
        ]
        
        message = "\n".join(message_parts)
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "non_subscriber_invitation",
            "sender_name": sender_name,
            "expected_amount": SMSService._format_amount(expected_amount),
            "product_name": product_name,
            "financial_institution_name": financial_institution_name,
            "batch_reference": batch_reference,
            "enhanced": True
        }
        
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_batch_processing_update_sms(phone: str, batch_id: Union[int, str], 
                                              progress_percentage: int, successful_count: int,
                                              failed_count: int, current_amount: Union[float, Decimal]) -> bool:
 
        reference = SMSService._generate_reference("BATCH_PROGRESS")
        
        if progress_percentage == 100:
            status_emoji = "SUCCESS"
            status_text = "BATCH PROCESSING COMPLETE"
            next_step = "REFRESH Ready for authorization"
        else:
            status_emoji = "REFRESH"
            status_text = "BATCH PROCESSING UPDATE"
            next_step = ""
        
        message_parts = [
            f"{status_emoji} {status_text}",
            f"CHART Batch: {batch_id}",
            f"DART {progress_percentage}% complete",
            f"SUCCESS Success: {successful_count}",
            f"ERROR Failed: {failed_count}",
            f"MONEY Processed: {SMSService._format_amount(current_amount)} ETB",
            f"TIME Time: {datetime.now().strftime('%I:%M %p')}"
        ]
        
        if next_step:
            message_parts.append(next_step)
            
        message = "\n".join(message_parts)
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "batch_processing_update",
            "batch_id": str(batch_id),
            "progress_percentage": progress_percentage,
            "successful_count": successful_count,
            "failed_count": failed_count,
            "current_amount": SMSService._format_amount(current_amount),
            "enhanced": True
        }
        
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_selective_authorization_summary_sms(phone: str, sender_name: str, 
                                                      batch_id: Union[int, str], authorized_count: int,
                                                      rejected_count: int, authorized_amount: Union[float, Decimal],
                                                      fee_amount: Union[float, Decimal] = 0) -> bool:

        reference = SMSService._generate_reference("SEL_AUTH_SUM")
        
        message_parts = [
            "LIST SELECTIVE AUTHORIZATION COMPLETE",
            f"👤 {sender_name}",
            f"CHART Batch: {batch_id}",
            f"SUCCESS Authorized: {authorized_count}"
        ]
        
        if rejected_count > 0:
            message_parts.append(f"ERROR Rejected: {rejected_count}")
            
        message_parts.append(f"MONEY Amount: {SMSService._format_amount(authorized_amount)} ETB")
        
        if fee_amount and float(fee_amount) > 0:
            message_parts.append(f"CARD Fee: {SMSService._format_amount(fee_amount)} ETB")
            
        message_parts.extend([
            f"TIME Time: {datetime.now().strftime('%I:%M %p')}",
            "MOBILE Recipients notified"
        ])
        
        if rejected_count > 0:
            message_parts.append("REFRESH Rejected transactions can be retried")
            
        message = "\n".join(message_parts)
        
        payload = {
            "phone": phone,
            "message": message,
            "type": "selective_authorization_summary",
            "sender_name": sender_name,
            "batch_id": str(batch_id),
            "authorized_count": authorized_count,
            "rejected_count": rejected_count,
            "authorized_amount": SMSService._format_amount(authorized_amount),
            "enhanced": True
        }
        if fee_amount and float(fee_amount) > 0:
            payload["fee_amount"] = SMSService._format_amount(fee_amount)
            
        return await SMSService.send_sms(reference, payload, phone)
    
    # ==================== JOINT ACCOUNT SMS METHODS ====================
    
    @staticmethod
    async def send_joint_invitation_sms(phone: str, inviter_name: str, account_name: str, 
                                       product_name: str = None, expires_days: int = 7) -> bool:
        """Send joint account invitation SMS"""
        reference = SMSService._generate_reference("JA_INV")
        message = f"You've been invited by {inviter_name} to join joint account '{account_name}'"
        if expires_days:
            message += f". Expires in {expires_days} days"
            
        payload = {
            "phone": phone,
            "message": message,
            "type": "joint_invitation",
            "inviter_name": inviter_name,
            "account_name": account_name,
            "expires_days": expires_days
        }
        if product_name:
            payload["product_name"] = product_name
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_joint_approval_sms(phone: str, approver_name: str, account_name: str,
                                     transaction_type: str, amount: Union[float, Decimal],
                                     transaction_reference: str = None) -> bool:
        """Send joint account transaction approval SMS"""
        reference = SMSService._generate_reference("JA_APP")
        message = (f"{approver_name} approved {transaction_type.lower()} of "
                  f"{SMSService._format_amount(amount)} ETB from '{account_name}'")
        if transaction_reference:
            message += f" (Ref: {transaction_reference})"
            
        payload = {
            "phone": phone,
            "message": message,
            "type": "joint_approval",
            "approver_name": approver_name,
            "account_name": account_name,
            "transaction_type": transaction_type,
            "amount": SMSService._format_amount(amount)
        }
        if transaction_reference:
            payload["transaction_reference"] = transaction_reference
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_joint_rejection_sms(phone: str, rejector_name: str, account_name: str,
                                      transaction_type: str, amount: Union[float, Decimal],
                                      reason: str = None, transaction_reference: str = None) -> bool:
        """Send joint account transaction rejection SMS"""
        reference = SMSService._generate_reference("JA_REJ")
        message = (f"{rejector_name} rejected {transaction_type.lower()} of "
                  f"{SMSService._format_amount(amount)} ETB from '{account_name}'")
        if reason:
            message += f". Reason: {reason}"
        if transaction_reference:
            message += f" (Ref: {transaction_reference})"
            
        payload = {
            "phone": phone,
            "message": message,
            "type": "joint_rejection",
            "rejector_name": rejector_name,
            "account_name": account_name,
            "transaction_type": transaction_type,
            "amount": SMSService._format_amount(amount)
        }
        if reason:
            payload["rejection_reason"] = reason
        if transaction_reference:
            payload["transaction_reference"] = transaction_reference
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_joint_withdrawal_request_sms(phone: str, initiator_name: str, account_name: str,
                                               amount: Union[float, Decimal], required_approvals: int,
                                               expires_at: str = None, transaction_reference: str = None) -> bool:
        """Send joint account withdrawal request SMS to authorizers"""
        reference = SMSService._generate_reference("JA_WD_REQ")
        message = (f"{initiator_name} requests withdrawal of {SMSService._format_amount(amount)} ETB "
                  f"from '{account_name}'. {required_approvals} approval(s) needed")
        if expires_at:
            message += f". Expires: {expires_at}"
        if transaction_reference:
            message += f" (Ref: {transaction_reference})"
            
        payload = {
            "phone": phone,
            "message": message,
            "type": "joint_withdrawal_request",
            "initiator_name": initiator_name,
            "account_name": account_name,
            "amount": SMSService._format_amount(amount),
            "required_approvals": required_approvals
        }
        if expires_at:
            payload["expires_at"] = expires_at
        if transaction_reference:
            payload["transaction_reference"] = transaction_reference
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_joint_deposit_sms(phone: str, depositor_name: str, account_name: str,
                                    amount: Union[float, Decimal], new_balance: Union[float, Decimal],
                                    transaction_reference: str = None) -> bool:
        """Send joint account deposit SMS to all members"""
        reference = SMSService._generate_reference("JA_DEP")
        message = (f"{depositor_name} deposited {SMSService._format_amount(amount)} ETB "
                  f"to '{account_name}'. New balance: {SMSService._format_amount(new_balance)} ETB")
        if transaction_reference:
            message += f" (Ref: {transaction_reference})"
            
        payload = {
            "phone": phone,
            "message": message,
            "type": "joint_deposit",
            "depositor_name": depositor_name,
            "account_name": account_name,
            "amount": SMSService._format_amount(amount),
            "new_balance": SMSService._format_amount(new_balance)
        }
        if transaction_reference:
            payload["transaction_reference"] = transaction_reference
            
        return await SMSService.send_sms(reference, payload, phone)
    
    # ==================== GENERIC & UTILITY SMS METHODS ====================
    
    @staticmethod
    async def send_custom_sms(phone: str, message: str, message_type: str = "notification",
                             additional_data: dict[str, Any] = None) -> bool:
        """Send custom SMS with flexible payload"""
        if not SMSService._validate_phone(phone):
            logger.warning("Custom SMS: Invalid phone %s", phone)
            return False
            
        # Validate and clean the message
        clean_message = SMSService._validate_message(message)
        if not clean_message:
            logger.warning("Custom SMS: Empty or invalid message for %s***", phone[:4])
            return False
        
        # Check if we're using GeezSMS
        if SAVING_API_URL and "geezsms.com" in SAVING_API_URL:
            return await SMSService._send_geezsms(phone, clean_message)
            
        reference = SMSService._generate_reference("CUSTOM")
        payload = {
            "phone": phone,
            "message": clean_message,
            "type": message_type
        }
        
        if additional_data:
            payload.update(additional_data)
            
        return await SMSService.send_sms(reference, payload, phone)
    
    @staticmethod
    async def send_notification_sms(phone: str, message: str) -> bool:
        """Send simple notification SMS (backward compatibility)"""
        # Validate and clean the message
        clean_message = SMSService._validate_message(message)
        if not clean_message:
            logger.warning("SMS: Empty or invalid message for %s***", phone[:4])
            return False
            
        return await SMSService.send_custom_sms(phone, clean_message, "notification")
    
    @staticmethod
    async def send_subscription_sms(reference: str, customer_name: str, product_name: str,
                                   bank_name: str, subscription_type: str = "ordinary", phone: str = None) -> bool:
        """Send subscription confirmation SMS"""
        payload = {
            "customer_name": customer_name,
            "product_name": product_name,
            "bank_name": bank_name,
            "type": f"{subscription_type}_subscription"
        }
        return await SMSService.send_sms(reference, payload, phone)
    
    # ==================== BATCH SMS METHODS ====================
    
    @staticmethod
    async def send_multiple_sms(sms_requests: list) -> dict[str, bool]:
        """
        Send multiple SMS messages in parallel
        
        Args:
            sms_requests: List of dicts with keys: phone, message, type, additional_data (optional)
            
        Returns:
            Dict mapping phone numbers to success status
        """
        results = {}
        tasks = []
        
        for sms_request in sms_requests:
            phone = sms_request.get('phone')
            message = sms_request.get('message')
            message_type = sms_request.get('type', 'notification')
            additional_data = sms_request.get('additional_data')
            
            if phone and message:
                task = SMSService.send_custom_sms(phone, message, message_type, additional_data)
                tasks.append((phone, task))
            else:
                results[phone or 'invalid'] = False
        
        # Execute all SMS tasks in parallel
        if tasks:
            task_results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            for (phone, _), result in zip(tasks, task_results):
                results[phone] = result if not isinstance(result, Exception) else False
        
        return results
