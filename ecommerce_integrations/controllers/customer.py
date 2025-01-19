from typing import Any, Dict

import frappe
from frappe import _

class EcommerceCustomer:
	def __init__(self, customer_id: str, customer_id_field: str, integration: str):
		self.customer_id = customer_id
		self.customer_id_field = customer_id_field
		self.integration = integration

	def is_synced(self) -> bool:
		"""Check if customer on Ecommerce site is synced with ERPNext"""

		return bool(frappe.db.exists("Shopify Platform Customer", {"customer_id": self.customer_id}))

	def get_customer_doc(self):
		"""Get ERPNext customer document."""
		if self.is_synced():
			return frappe.get_last_doc("Shopify Platform Customer", {"customer_id": self.customer_id})
		else:
			raise frappe.DoesNotExistError()

	def sync_customer(self, customer_name: str, customer: Dict[str, Any], default_customer: None) -> None:
		"""Create shopify platform customer in ERPNext if one does not exist already."""
		customer = frappe.get_doc(
			{
				"doctype": "Shopify Platform Customer",
				"name": self.customer_id,
				"customer_id": self.customer_id,
				"default_customer": default_customer,
				"full_name": customer_name,
				"first_name": customer.get("first_name"),
				"last_name": customer.get("last_name"),
				"email": customer.get("email"),
			}
		)

		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

	def get_customer_address_doc(self, address_type: str):
		try:
			customer = self.get_customer_doc().name
			addresses = frappe.get_all("Address", {"link_name": customer, "address_type": address_type})
			if addresses:
				address = frappe.get_last_doc("Address", {"name": addresses[0].name})
				return address
		except frappe.DoesNotExistError:
			return None

	def create_customer_address(self, address: Dict[str, str]) -> None:
		"""Create address from dictionary containing fields used in Address doctype of ERPNext."""

		customer_doc = self.get_customer_doc()

		frappe.get_doc(
			{
				"doctype": "Address",
				**address,
				"links": [{"link_doctype": "Shopify Platform Customer", "link_name": customer_doc.name}],
			}
		).insert(ignore_mandatory=True)

	def create_customer_contact(self, contact: Dict[str, str]) -> None:
		"""Create contact from dictionary containing fields used in Address doctype of ERPNext."""

		customer_doc = self.get_customer_doc()

		frappe.get_doc(
			{
				"doctype": "Contact",
				**contact,
				"links": [{"link_doctype": "Shopify Platform Customer", "link_name": customer_doc.name}],
			}
		).insert(ignore_mandatory=True)
