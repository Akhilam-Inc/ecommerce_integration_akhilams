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
        invoices = frappe.get_all("Sales Invoice", 
                                filters={
                                    "custom_eshipz_tracking_number": ["!=", ""],
                                    "custom_tracking_id": ["=", ""],
                                    "shopify_order_id": ["!=", ""],
                                    "docstatus": 1  # Only get submitted documents
                                }, 
                                fields=["name", "shopify_order_id", "custom_eshipz_tracking_number"])

        if not invoices:
            frappe.logger().debug("No invoices found for shipping updates")
            return

        for invoice in invoices:
            try:
                # Prepare the data for the API request
                data = {
                    "order_id": invoice.shopify_order_id,
                    "tracking_string": invoice.custom_eshipz_tracking_number,
                }

                # Send the data to the third-party logistics provider
                response = update_shipping_details(data)

                if response:
                    # Update the custom_tracking_id field directly in the database
                    frappe.db.set_value("Sales Invoice", invoice.name, "custom_tracking_id", response)
                    
                    # Commit the transaction to ensure changes are saved
                    frappe.db.commit()
                    
                    frappe.logger().info(f"Sales Invoice {invoice.name} fulfilled successfully with tracking ID {response}")
                else:
                    frappe.logger().error(f"Failed to update shipping details for invoice {invoice.name}. No response received.")
            
            except Exception as e:
                frappe.logger().error(f"Error processing invoice {invoice.name}: {str(e)}")
                frappe.log_error(title=f"Sales Invoice Fulfillment Error - {invoice.name}", message=frappe.get_traceback())

    except Exception as e:
        frappe.log_error(title="Sales Invoice Fulfillment Error", message=frappe.get_traceback())
