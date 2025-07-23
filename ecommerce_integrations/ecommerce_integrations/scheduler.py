import frappe
import requests
import json
from datetime import datetime
from ecommerce_integrations.api import update_shipping_details, create_fulfillment


@frappe.whitelist()
def schedule_shipping_updates():
    """
    Schedule shipping updates to be sent to the third-party logistics provider.
    Uses frappe.enqueue for larger record sets.
    """
    try:
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={
            "custom_eshipz_tracking_number": ["not in", ["", "Shipment Not Created"]],
            "custom_tracking_id": ["not in", ["fulfilled", "By Hand Over"]],
            "shopify_order_id": ["!=", ""],
            "docstatus": 1,  # Only consider submitted invoices
            },
            fields=["name", "shopify_order_id", "custom_eshipz_tracking_number"]
        )

        if not invoices:
            frappe.log_error(title="Shipping Updates", message="No invoices found for shipping updates")
            return

        # Use frappe.enqueue for large record sets
        threshold = 30
        if len(invoices) > threshold:
            frappe.enqueue(
                "ecommerce_integrations.ecommerce_integrations.scheduler.process_shipping_updates",
                invoices=invoices,
                queue='long'
            )
        else:
            process_shipping_updates(invoices)

    except Exception:
        frappe.log_error(title="Sales Invoice Fulfillment Scheduler Error", message=frappe.get_traceback())


def process_shipping_updates(invoices):
    for invoice in invoices:
        try:
            order_id = invoice.shopify_order_id
            tracking_string = invoice.custom_eshipz_tracking_number

            response = update_shipping_details(order_id=order_id, tracking_string=tracking_string)
            # frappe.log_error(title="Shopify Response", message=f"Updated shipping details for invoice {invoice.name} with response: {response}")

            if response:
                frappe.db.set_value("Sales Invoice", invoice.name, "custom_tracking_id", response, update_modified=False)
                # frappe.db.commit()
            else:
                frappe.log_error(title="Shipping Updates", message=f"Failed to update shipping details for invoice {invoice.name}. No response received.")

        except Exception:
            frappe.log_error(title=f"Sales Invoice Fulfillment Error - {invoice.name}", message=frappe.get_traceback())