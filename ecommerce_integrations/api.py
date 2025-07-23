import requests
import json
import frappe
import time
from datetime import datetime
import backoff

class ShopifyRateLimit:
    def __init__(self, max_retries=5):
        self.max_retries = max_retries

    def on_backoff(details):
        frappe.logger().info(f"Backing off {details['wait']:0.1f} seconds after {details['tries']} tries")

    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        max_tries=10,
        on_backoff=on_backoff
    )
    def call_shopify_api(self, session, url, method='get', data=None, headers=None):
        if method.lower() == 'get':
            response = session.get(url, headers=headers)
        else:
            response = session.post(url, json=data, headers=headers)
            
        if 'exceeded' in response.text.lower():
            raise requests.exceptions.RequestException("Rate limit exceeded")
            frappe.log_error(title="Shopify Fulfillment", message=f"Response: {response.text}")

            
        return response

shopify_api = ShopifyRateLimit()

def call_shopify_api(session, url, method='get', data=None, headers=None):
    rate_limiter.wait_if_needed()
    if method.lower() == 'get':
        return session.get(url, headers=headers)
    return session.post(url, json=data, headers=headers)

def parse_tracking_info(tracking_string):
    if not tracking_string:
        return None, None
    
    tracking_string = tracking_string.strip()
    parts = [p.strip() for p in tracking_string.split("-", 1)]
    
    if len(parts) == 2:
        tracking_number, carrier = parts
        if not carrier:
            return tracking_number, None
        return tracking_number, carrier
    return parts[0], None

def get_shopify_settings():
    settings = frappe.get_doc("Shopify Setting")
    if not settings.enable_shopify:
        frappe.log_error(title="Shopify Integration", message="Shopify integration is disabled")
        frappe.throw("Shopify integration is disabled")
    if not settings.password or not settings.shopify_url:
        frappe.log_error(title="Shopify Integration", message="Missing Shopify credentials. Please set Access Token and Store URL in Shopify Settings")
        frappe.throw("Missing Shopify credentials. Please set Access Token and Store URL in Shopify Settings")
    return settings

def get_shopify_order(session, store_url, order_id, headers):
    order_url = f"https://{store_url}/admin/api/2025-01/orders/{order_id}.json"
    response = shopify_api.call_shopify_api(session=session, url=order_url, method='get', headers=headers)
    
    if response.status_code != 200:
        frappe.log_error(title="Shopify Order not Found", message=response.text)
        frappe.throw(f"Order {order_id} not found in Shopify: {response.text}")
    
    return response.json()

settings = get_shopify_settings()
session = requests.Session()
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Shopify-Access-Token": settings.get_password('password')
}
store_url = settings.shopify_url

def create_fulfillment(session=session, store_url=store_url, order_id=None, headers=headers):
    # Get fulfillment orders
    fulfillment_order_url = f"https://{store_url}/admin/api/2024-10/orders/{order_id}/fulfillment_orders.json"
    response = shopify_api.call_shopify_api(session=session, url=fulfillment_order_url, method='get', headers=headers)
    frappe.log_error(title="Shopify Fulfillment", message=f"Response: {response.text}")

    if response.status_code != 200:
        frappe.log_error(title="Shopify Fulfillment", message=f"Failed to get fulfillment order ID: {response.text}")
        frappe.throw(f"Failed to get fulfillment order ID: {response.text}")
    
    fulfillment_orders = response.json().get('fulfillment_orders', [])
    if not fulfillment_orders:
        frappe.throw(f"No fulfillment orders found for order {response.json()}")
    
    fulfillment_order_id = fulfillment_orders[0]['id']
    
    # Create fulfillment using GraphQL
    graphql_url = f"https://{store_url}/admin/api/2025-01/graphql.json"
    graphql_query = {
        "query": """
            mutation fulfillmentCreateV2($fulfillment: FulfillmentV2Input!) {
                fulfillmentCreateV2(fulfillment: $fulfillment) {
                    fulfillment {
                        id
                        status
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
        """,
        "variables": {
            "fulfillment": {
                "lineItemsByFulfillmentOrder": {
                    "fulfillmentOrderId": f"gid://shopify/FulfillmentOrder/{fulfillment_order_id}"
                }
            }
        }
    }
    
    response = shopify_api.call_shopify_api(session=session, url=graphql_url, method='post', data=graphql_query, headers=headers)
    response_data = response.json()
    frappe.log_error(title="Shopify Fulfillment", message=f"Response: {response_data}")
    
    if response.status_code != 200 or 'errors' in response_data:
        frappe.throw(f"Failed to create fulfillment: {response.text}")
        frappe.log_error(title="Shopify Fulfillment", message=f"Response: {response_data}")

    
    fulfillment_data = response_data['data']['fulfillmentCreateV2']['fulfillment']
    if not fulfillment_data:
        error_message = response_data['data']['fulfillmentCreateV2']['userErrors'][0]['message']
        frappe.throw(f"Failed to create fulfillment: {error_message}")
        frappe.log_error(title="Shopify Fulfillment", message=f"Response: {error_message}")

    return fulfillment_data['id'].split('/')[-1]


@frappe.whitelist()
def update_shipping_details(order_id, tracking_string):
    settings = get_shopify_settings()
    tracking_number, carrier = parse_tracking_info(tracking_string)
    
    session = requests.Session()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Shopify-Access-Token": settings.get_password('password')
    }
    store_url = settings.shopify_url
    
    try:
        # Get order details
        order_data = get_shopify_order(session, store_url, order_id, headers)
        
        # Get or create fulfillment
        if not order_data['order']['fulfillments']:
            fulfillment_id = create_fulfillment(session, store_url, order_id, headers)
        else:
            fulfillment_id = order_data['order']['fulfillments'][0]['id']
        
        # Update tracking information
        tracking_info = {
            "fulfillment": {
                "tracking_info": {
                    "number": tracking_number,
                    "company": carrier,
                },
                "notify_customer": True
            }
        }
        
        update_tracking_url = f"https://{store_url}/admin/api/2025-01/fulfillments/{fulfillment_id}/update_tracking.json"
        response = shopify_api.call_shopify_api(
            session=session,
            url=update_tracking_url,
            method='post',
            data=tracking_info,
            headers=headers
        )
        
        if response.status_code == 200:
            fulfillment_status = get_fulfillment_status(response.text)
            if fulfillment_status:
                # frappe.log_error(title="Shopify Fulfillment", message=f"Response: {response.text}, fulfillment_status: {fulfillment_status}")
                return fulfillment_status
        else:
            frappe.throw(f"Failed to update Shopify: {response.text}")
            frappe.log_error(title="Shopify Fulfillment Response Error", message=f"Response: {response.text},'fulfillment_id': {fulfillment_id}")

        
    finally:
        session.close()

def get_fulfillment_status(response_text):
    try:
        data = json.loads(response_text)
        line_items = data.get("fulfillment", {}).get("line_items", [])

        for item in line_items:
            status = item.get("fulfillment_status")
            if status:  # non-null, non-empty
                return status

    except Exception as e:
        frappe.log_error(f"Error extracting fulfillment_status: {str(e)}")

    return None  # fallback if not found or error

