import frappe
import requests
import json
from datetime import datetime
from ecommerce_integrations.ecommerce_integrations.api import update_shipping_details, create_fulfillment

@frappe.whitelist()
def schedule_shipping_updates():
    """
    Schedule shipping updates to be sent to the third-party logistics provider.
    """
    try:
    # Fetch the list of orders that need shipping updates
        orders = frappe.get_all("Sales Order", 
                                filters={"delivery_status": ["in", ["Partly Delivered", "Fully Delivered"]],
                                        "custom_shopify_fulfillment_id": ["!=", ""],
                                        "shopify_order_id": ["!=", ""]}, 
                                fields=["name", "shopify_order_id"])

        for order in orders:

            # Prepare the data for the API request
            data = {
                "order_id": order.shopify_order_id,
                # "tracking_string": "",
            }

            # Send the data to the third-party logistics provider
            response = create_fulfillment(data)

            if response:
                sales_order = frappe.get_doc("Sales Order", order.name)
                
                # Update the custom_shopify_fulfillment_id field with the response
                sales_order.custom_shopify_fulfillment_id = response
                
                # Save the document with update flag
                sales_order.save(ignore_permissions=True)
                frappe.log_error(title="Saled Order Fulfillment", message="Sales Order Fulfilled Successfully")

                # frappe.msgprint(f"Shipping details for {order.name} updated successfully.")
            else:
                frappe.log_error(title="Saled Order Fulfillment Error", message=frappe.get_traceback())

    except Exception as e:
        frappe.log_error(title="Saled Order Fulfillment Error", message=frappe.get_traceback())
        
