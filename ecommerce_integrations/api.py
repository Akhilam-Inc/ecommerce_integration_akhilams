import requests 
import json 
import frappe

def parse_tracking_info(tracking_string):
    if not tracking_string:
        return None, None
    
    # Clean up any extra spaces and handle trailing/leading spaces
    tracking_string = tracking_string.strip()
    
    # Split on the last hyphen and handle spaces around it
    parts = [p.strip() for p in tracking_string.split("-", 1)]
    
    if len(parts) == 2:
        tracking_number, carrier = parts
        # Handle trailing hyphen case
        if not carrier:
            return tracking_number, None
        # Handle carrier with internal hyphens
        return tracking_number, carrier
            
    # Single part - either tracking number or carrier
    return parts[0], None

def get_shopify_settings():
    settings = frappe.get_doc("Shopify Setting")
    if not settings.enable_shopify:
        frappe.throw("Shopify integration is disabled")
    if not settings.password or not settings.shopify_url:
        frappe.throw("Missing Shopify credentials. Please set Access Token and Store URL in Shopify Settings")
    return settings

def get_shopify_order(order_id):
    """Retrieve order details from Shopify"""
    settings = get_shopify_settings()
    
    # Setup Shopify API session
    session = requests.Session()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Shopify-Access-Token": settings.get_password('password')
    }

    store_url = settings.shopify_url
    
    # Fetch the order from Shopify
    order_url = f"https://{store_url}/admin/api/2025-01/orders/{order_id}.json"
    response = session.get(order_url, headers=headers)

    if response.status_code != 200:
        frappe.throw(f"Order {order_id} not found in Shopify: {response.text}")

    order_data = response.json()
    session.close()
    return order_data


@frappe.whitelist()
def update_shipping_details(order_id, tracking_string):
    """Update order fulfillment in Shopify with tracking details"""
    
    settings = get_shopify_settings()
    
    # Extract tracking number and carrier
    try:
        tracking_number, carrier = parse_tracking_info(tracking_string)
    except ValueError:
        frappe.throw("Invalid tracking format. Expected 'tracking_number-carrier'")

    
    order_data = get_shopify_order(order_id)

    session = requests.Session()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Shopify-Access-Token": settings.get_password('password')
    }

    store_url = settings.shopify_url

    # Check if the order has any fulfillments
    if not order_data['order']['fulfillments']:
        
        # Get the fulfillment order ID
        fulfillment_order_url = f"https://{store_url}/admin/api/2025-01/orders/{order_id}/fulfillment_orders.json"
        response = session.get(fulfillment_order_url, headers=headers)

        if response.status_code != 200:
            frappe.throw(f"Failed to get fulfillment order ID: {response.text}")

        fulfillment_order_data = response.json()
        fulfillment_order_id = fulfillment_order_data['fulfillment_orders'][0]['id']

        # Request the fulfillment using GraphQL
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
        response = session.post(graphql_url, headers=headers, data=json.dumps(graphql_query))
        if response.status_code != 200 or 'errors' in response.json():
            frappe.throw(f"Failed to request fulfillment: {response.text}")

        if response.json()['data']['fulfillmentCreateV2']['fulfillment']:
            fulfillment_id = response.json()['data']['fulfillmentCreateV2']['fulfillment']['id']
            fulfillment_id = fulfillment_id.split('/')[-1]
        else:
            frappe.throw(f"Failed to request fulfillment: {response.json()['data']['fulfillmentCreateV2']['userErrors'][0]['message']}")
    else:
        fulfillment_id = order_data['order']['fulfillments'][0]['id']

    # Update tracking information
    tracking_info = {
        "number": tracking_number,
        "company": carrier,
    }
    update_tracking_data = {
        "fulfillment": {
            "tracking_info": tracking_info,
            "notify_customer": True
        }
    }
    if fulfillment_id:
        update_tracking_url = f"https://{store_url}/admin/api/2025-01/fulfillments/{fulfillment_id}/update_tracking.json"
        response = session.post(update_tracking_url, headers=headers, data=json.dumps(update_tracking_data))
        if response.status_code == 200:
            return(f"Order {order_id} marked as fulfilled in Shopify with tracking: {tracking_number} ({carrier})")
        else:
            frappe.throw(f"Failed to update Shopify: {response.text}")
    else:
        frappe.throw("Order not fulfilled yet")

    # Close Shopify session
    session.close()
