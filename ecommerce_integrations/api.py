import requests 
import json 
import frappe
import time
from datetime import datetime

class RateLimiter:
    def __init__(self, calls_per_second=2):
        self.calls_per_second = calls_per_second
        self.last_call_time = None
    
    def wait_if_needed(self):
        current_time = datetime.now()
        if self.last_call_time:
            elapsed = (current_time - self.last_call_time).total_seconds()
            if elapsed < (1.0 / self.calls_per_second):
                time.sleep((1.0 / self.calls_per_second) - elapsed)
        self.last_call_time = current_time

rate_limiter = RateLimiter()

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
        frappe.throw("Shopify integration is disabled")
    if not settings.password or not settings.shopify_url:
        frappe.throw("Missing Shopify credentials. Please set Access Token and Store URL in Shopify Settings")
    return settings

def get_shopify_order(session, store_url, order_id, headers):
    order_url = f"https://{store_url}/admin/api/2025-01/orders/{order_id}.json"
    # response = call_shopify_api(session, order_url, headers=headers)
    response = call_shopify_api(session=session, url=order_url,method='get',headers=headers)
    
    if response.status_code != 200:
        frappe.throw(f"Order {order_id} not found in Shopify: {response.text}")
    
    return response.json()

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
        order_data = get_shopify_order(session, store_url, order_id, headers)
        
        if not order_data['order']['fulfillments']:
            fulfillment_order_url = f"https://{store_url}/admin/api/2025-01/orders/{order_id}/fulfillment_orders.json"
            # response = call_shopify_api(session, fulfillment_order_url, headers=headers)
            response = call_shopify_api(session=session, url=fulfillment_order_url,method='get',headers=headers)
            
            if response.status_code != 200:
                frappe.throw(f"Failed to get fulfillment order ID: {response.text}")
            
            fulfillment_order_id = response.json()['fulfillment_orders'][0]['id']
            
            graphql_url = f"https://{store_url}/admin/api/2025-01/graphql.json"
            graphql_query = {
                "query": "mutation fulfillmentCreateV2($fulfillment: FulfillmentV2Input!) { fulfillmentCreateV2(fulfillment: $fulfillment) { fulfillment { id status } userErrors { field message } } }",
                "variables": {
                    "fulfillment": {
                        "lineItemsByFulfillmentOrder": {
                            "fulfillmentOrderId": f"gid://shopify/FulfillmentOrder/{fulfillment_order_id}"
                        }
                    }
                }
            }
            response = call_shopify_api(session=session, url=graphql_url,method='post',data=graphql_query,headers=headers)
            # response = call_shopify_api(session, graphql_url, method='post', data=graphql_query, headers=headers)
            response_data = response.json()
            
            if response.status_code != 200 or 'errors' in response_data:
                frappe.throw(f"Failed to request fulfillment: {response.text}")
            
            if response_data['data']['fulfillmentCreateV2']['fulfillment']:
                fulfillment_id = response_data['data']['fulfillmentCreateV2']['fulfillment']['id'].split('/')[-1]
            else:
                frappe.throw(f"Failed to request fulfillment: {response_data['data']['fulfillmentCreateV2']['userErrors'][0]['message']}")
        else:
            fulfillment_id = order_data['order']['fulfillments'][0]['id']
        
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
        response = call_shopify_api(session=session, url=update_tracking_url, method='post', data=tracking_info, headers=headers)
        
        if response.status_code == 200:
            return f"Order {order_id} marked as fulfilled in Shopify with tracking: {tracking_number} ({carrier})"
        
        frappe.throw(f"Failed to update Shopify: {response.text}")
        
    finally:
        session.close()
